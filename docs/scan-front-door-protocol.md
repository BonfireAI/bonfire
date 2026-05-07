# The Front Door — WebSocket protocol

This document specifies the wire protocol used by the `bonfire scan` command's
"Front Door" onboarding theater. The browser UI served at `/` opens a single
WebSocket to `/ws`; this protocol describes the JSON messages exchanged on
that socket between the Python server (`FrontDoorServer`) and the inline JS
client in `ui.html`.

The spec is intended for two readers:

1. A future driver (CLI, headless test harness, alternative UI) that wants to
   speak the same protocol without re-deriving it from source.
2. Anyone modifying the protocol; this is the document the change must keep
   in sync.

Every event and message below cites the file and line range that emits or
handles it. Citations are against branch `v0.1` at the time of writing.

## 1. Overview

The Front Door is a single-session, single-client WebSocket protocol that
runs **three sequential acts** ("Scan", "Conversation", "Config Generation")
inside one browser tab. The server starts, opens a browser to a localhost
HTTP page, then streams scan discoveries and Falcor (the companion's)
narration over the WebSocket. Once scanning completes, the server asks three
profiling questions; the browser sends free-text answers; the server
synthesizes a `bonfire.toml` and broadcasts it back.

- **Transport**: `ws://127.0.0.1:<port>/ws`. HTTP `GET /` returns the bundled
  `ui.html`; any other path returns 404.
  Source: `src/bonfire/onboard/server.py:147-162`.
- **Encoding**: every frame is a JSON-encoded object with a string `type`
  field used as a discriminator. Non-string frames are dropped silently;
  non-JSON string frames log a warning and are discarded.
  Source: `src/bonfire/onboard/server.py:171-178`.
- **Direction**: most traffic is server → client (broadcast). The only
  client → server frame is `user_message`.
- **Lifecycle**: the server tracks connections; when the first client
  connects, `client_connected` fires and the flow begins; when the last
  client disconnects after at least one had connected, `shutdown_event`
  fires and `bonfire scan` exits.
  Source: `src/bonfire/onboard/server.py:164-187`,
  `src/bonfire/cli/commands/scan.py:33-45`.
- **Message models**: all message types are Pydantic models in
  `src/bonfire/onboard/protocol.py`; the same module exposes
  `parse_client_message` / `parse_server_message` for tests.
  Source: `src/bonfire/onboard/protocol.py:40-162`.

The flow's composition root is `run_front_door` in
`src/bonfire/onboard/flow.py:39-115`. It runs the scan orchestrator
interleaved with narration, runs the scripted conversation engine, and
finally calls `generate_config` and broadcasts a `config_generated` event.

## 2. Server → Client events

All seven server-emitted message types are registered in the server-type
table at `src/bonfire/onboard/protocol.py:125-133`. Each subsection below
gives the JSON schema (key, type, required), the trigger, and a citation
that resolves to the exact emit site.

### 2.1 `scan_start`

| Field    | Type        | Required | Notes                               |
|----------|-------------|----------|-------------------------------------|
| `type`   | `"scan_start"` | yes   | discriminator                       |
| `panels` | `list[str]` | yes      | ordered list of panel slugs         |

**Fires**: exactly once, immediately when scanning begins. The list is the
six built-in panel names in fixed order:
`["project_structure", "cli_toolchain", "claude_memory", "git_state", "mcp_servers", "vault_seed"]`.

**Source (model)**: `src/bonfire/onboard/protocol.py:51-55`.
**Source (emit)**: `src/bonfire/onboard/orchestrator.py:75-77`
(panel names assembled from `_get_scanners()` at lines 43-52, then
`await emit(ScanStart(panels=panel_names))`).
**Source (client)**: `src/bonfire/onboard/ui.html:349`. The JS only updates
the connection-status banner; it does not pre-create panels from this list.
The panels are static DOM at `ui.html:265-270` and the JS gates rendering on
a hardcoded `KNOWN_PANELS` array (`ui.html:362`).

### 2.2 `scan_update`

| Field    | Type    | Required | Notes                                  |
|----------|---------|----------|----------------------------------------|
| `type`   | `"scan_update"` | yes | discriminator                          |
| `panel`  | `str`   | yes      | panel slug (one of the six)            |
| `label`  | `str`   | yes      | the row's left-column label            |
| `value`  | `str`   | yes      | the row's right-column value           |
| `detail` | `str`   | no       | optional secondary text; defaults `""` (see note below on emit truth) |

**Note on `detail` (parser tolerance vs emit truth)**: "Required: no"
describes the parser. The field has a default of `""` on the Pydantic
model (`src/bonfire/onboard/protocol.py:65`), so `parse_server_message`
accepts frames that omit it and clients should not require it. On the
wire, however, `flow.scan_emit` calls `event.model_dump()`
(`src/bonfire/onboard/flow.py:58`), and Pydantic's `model_dump()`
serializes every field on the model — so the server **always** emits
`detail`, with the empty string `""` for events that did not set it.
Drivers should tolerate absence (per the protocol) but in practice will
always observe the field.

**Fires**: many times per scan, interleaved across panels in parallel. Each
event is one discovery row in one panel. The orchestrator runs all six
scanner modules concurrently via `asyncio.gather`
(`src/bonfire/onboard/orchestrator.py:79-80`); the `flow.scan_emit` callback
broadcasts every event and additionally interleaves a Falcor narration
(`src/bonfire/onboard/flow.py:56-65`).

**Source (model)**: `src/bonfire/onboard/protocol.py:58-65`.
**Source (emitters, one per scanner)**:

- `project_structure`: `src/bonfire/onboard/scanners/project_structure.py:67-73`
- `cli_toolchain`: `src/bonfire/onboard/scanners/cli_toolchain.py:127-132`
  (built), `:142` (emit)
- `claude_memory`: `src/bonfire/onboard/scanners/claude_memory.py:67`,
  `:101`, `:107`, `:114`, `:153-159`, `:166-173`, `:193-199`, `:218-225`
- `git_state`: `src/bonfire/onboard/scanners/git_state.py:107-110`
  (helper) — used at `:113`, `:121`, `:131`, `:147`, `:158`, `:160`, `:168`
- `mcp_servers`: `src/bonfire/onboard/scanners/mcp_servers.py:226-232`
- `vault_seed`: `src/bonfire/onboard/scanners/vault_seed.py:91`, `:96`,
  `:121-127`, `:136`, `:148`, `:156-162`, `:179-186`, `:191`, `:196`,
  `:207`, `:235-242`

**Source (client)**: `src/bonfire/onboard/ui.html:350` dispatches to
`addScanItem` at `ui.html:364-374`, which silently drops events whose
`panel` is not in the hardcoded `KNOWN_PANELS` list.

### 2.3 `scan_complete`

| Field        | Type    | Required | Notes                          |
|--------------|---------|----------|--------------------------------|
| `type`       | `"scan_complete"` | yes | discriminator                   |
| `panel`      | `str`   | yes      | panel slug that just finished  |
| `item_count` | `int`   | yes      | number of `scan_update`s emitted on this panel; on scanner exception the orchestrator logs and reports `0` |

**Fires**: once per panel, when that panel's scanner returns (or raises).
Order across panels is non-deterministic — they finish in whatever order
their `asyncio.gather` task completes.

**Source (model)**: `src/bonfire/onboard/protocol.py:72-77`.
**Source (emit)**: `src/bonfire/onboard/orchestrator.py:104-110`
(`_run_one`: `count = await module.scan(...)` in a `try/except` that resets
`count` to `0` on failure, then `await emit(ScanComplete(...))`).
**Source (client)**: `src/bonfire/onboard/ui.html:351` dispatches to
`markPanelComplete` at `ui.html:376-383`, which adds the `complete` CSS
class and appends ` [N]` to the panel header.

### 2.4 `all_scans_complete`

| Field         | Type    | Required | Notes                                        |
|---------------|---------|----------|----------------------------------------------|
| `type`        | `"all_scans_complete"` | yes | discriminator                                |
| `total_items` | `int`   | yes      | sum of `item_count` across all six panels    |

**Fires**: exactly once, after all six scanners have returned and the
orchestrator has summed their counts. Always follows the last
`scan_complete` for the run.

**Source (model)**: `src/bonfire/onboard/protocol.py:80-84`.
**Source (emit)**: `src/bonfire/onboard/orchestrator.py:80-84`.
**Source (client)**: `src/bonfire/onboard/ui.html:352` updates the
status banner to "<N> findings catalogued".

### 2.5 `conversation_start`

| Field  | Type    | Required | Notes        |
|--------|---------|----------|--------------|
| `type` | `"conversation_start"` | yes | discriminator |

**Fires**: exactly once, after a `0.5 s` pause following
`all_scans_complete`. Marks the transition from Act I (Scan Theater) to
Act II (Conversation). It is the **first** message the conversation engine
emits, immediately followed by the first `falcor_message` (a `question`
subtype).

**Source (model)**: `src/bonfire/onboard/protocol.py:87-90`.
**Source (emit)**: `src/bonfire/onboard/conversation.py:389-396`
(`ConversationEngine.start` emits `ConversationStart()` then the Q1
`FalcorMessage`). Gated upstream by the `asyncio.sleep(0.5)` at
`src/bonfire/onboard/flow.py:69` and the `start()` call at
`src/bonfire/onboard/flow.py:92`.
**Source (client)**: `src/bonfire/onboard/ui.html:353` dispatches to
`activateChat` at `ui.html:387-412`, which compresses the scan grid and
fades in the chat panel.

### 2.6 `falcor_message`

| Field     | Type | Required | Notes                                                    |
|-----------|------|----------|----------------------------------------------------------|
| `type`    | `"falcor_message"` | yes | discriminator                                             |
| `text`    | `str` | yes     | display text (also used as the typewriter source)        |
| `subtype` | `Literal["narration", "question", "reflection"]` | yes | routes the client UI |

**Fires**: at multiple points; the `subtype` determines origin and intent.

- `subtype="narration"` — emitted by `NarrationEngine.get_narration` while
  scans are streaming, interleaved between `scan_update`s. The engine
  keeps a single rolling discovery counter (`_discovery_count`) that
  increments on every `ScanUpdate` regardless of tier
  (`src/bonfire/onboard/narration.py:252`). For each event it then
  classifies the tier and applies the modulo rule against the counter:
  Tier 3 always narrates; Tier 2 narrates when
  `_discovery_count % 3 == 0`; Tier 1 narrates when
  `_discovery_count % 4 == 0`
  (`src/bonfire/onboard/narration.py:230-242`). The counter is **global,
  not per-tier** — Tier 2 narrates on the 3rd, 6th, 9th, … discovery
  overall (only if that discovery itself is Tier 2), so consecutive
  narratable events can be much further apart than "every third Tier-2
  event" would imply. Skipped events return `None` and emit nothing.
  The interleaving call site is `src/bonfire/onboard/flow.py:60-64`
  (after each `ScanUpdate` is broadcast, the engine is asked for a
  narration and that too is broadcast if non-`None`).
- `subtype="question"` — emitted by the conversation engine: the first
  question follows `ConversationStart` in `start()`
  (`src/bonfire/onboard/conversation.py:395`); subsequent questions follow
  each non-final reflection in `handle_answer`
  (`src/bonfire/onboard/conversation.py:441-446`). Three are emitted per
  session. The text strings are `_Q1_TEXT`/`_Q2_TEXT`/`_Q3_TEXT` at
  `src/bonfire/onboard/conversation.py:33-40`.
- `subtype="reflection"` — emitted once per user answer (three per
  session) by the conversation engine after analyzing each answer.
  Source: `src/bonfire/onboard/conversation.py:425-430`. Short answers
  (< 3 words) yield the canned `_BRIEF_REFLECTION` instead of a tailored
  one (`src/bonfire/onboard/conversation.py:417-419`).

**Source (model)**: `src/bonfire/onboard/protocol.py:93-98`.
**Source (client)**: `src/bonfire/onboard/ui.html:354-357`. The JS routes
`narration` to `setNarration` (which writes to the dedicated narration
strip with a typewriter effect) and the other two subtypes to
`addChatMessage('falcor', ...)` (which appends to the chat log). The
client therefore treats `question` and `reflection` identically; the
distinction is preserved in the protocol for any future driver that wants
to render them differently or distinguish them in transcripts.

### 2.7 `config_generated`

| Field         | Type            | Required | Notes                                         |
|---------------|-----------------|----------|-----------------------------------------------|
| `type`        | `"config_generated"` | yes | discriminator                                  |
| `config_toml` | `str`           | yes      | the generated `bonfire.toml` body              |
| `annotations` | `dict[str, str]` | yes     | key = `"<section>.<field>"`, value = source description (e.g. `"Scan: project_structure"`, `"Conversation"`) |

**Fires**: exactly once, after the third reflection completes, synthesizing
the conversation profile and accumulated `ScanUpdate` list into a TOML
config. Always the last server message of a successful session.

**Source (model)**: `src/bonfire/onboard/protocol.py:101-106`.
**Source (build)**: `src/bonfire/onboard/config_generator.py:248-322`
(`generate_config`). Annotation keys are populated by each section
builder (`_build_persona`, `_build_project`, `_build_tools`, `_build_git`,
`_build_claude_memory`, `_build_mcp`, `_build_vault`).
**Source (emit)**: `src/bonfire/onboard/flow.py:107-110` (event built,
broadcast, then the TOML is also written to disk as `bonfire.toml` at
`flow.py:112`).
**Source (client)**: `src/bonfire/onboard/ui.html:358` updates the status
banner to "config generated". The client does **not** render the TOML or
its annotations — the file on disk is the surfaced artifact today; the
event payload is reserved for future drivers / a richer UI.

## 3. Client → Server messages

The client-type registry has exactly one entry:
`src/bonfire/onboard/protocol.py:135-137`.

### 3.1 `user_message`

| Field  | Type | Required | Notes                |
|--------|------|----------|----------------------|
| `type` | `"user_message"` | yes | discriminator         |
| `text` | `str` | yes     | user's free-text answer; `sendMessage()` calls `.trim()` on the input before sending (`src/bonfire/onboard/ui.html:434`), so leading/trailing whitespace is stripped — the field is **not** verbatim user keystrokes |

**Sent**: each time the user clicks "Send" or presses Enter in the chat
input during Act II. The session expects exactly three of these (one per
question); a fourth would raise `RuntimeError` from the conversation
engine, which the server catches and logs but does not surface to the
client.

**Source (sender)**: `src/bonfire/onboard/ui.html:433-439`
(`sendMessage()` builds the JSON, calls `ws.send(...)`, mirrors the text
into the local chat log).
**Source (handler)**: `src/bonfire/onboard/flow.py:82-89` (`on_message`
filters by `data.get("type") == "user_message"`, extracts `text`, calls
`conversation.handle_answer`). The handler is installed on the server only
**after** `ConversationEngine.start` has emitted Q1
(`src/bonfire/onboard/flow.py:96`). Until that assignment happens,
`FrontDoorServer._on_message` is `None` and `_ws_handler` gates each
incoming frame with `if self._on_message is not None:`
(`src/bonfire/onboard/server.py:179`); when the predicate is false the
frame is silently dropped (no logging, no error response). Any
`user_message` sent before Q1 lands is therefore lost without a trace
on the wire.
**Source (model)**: `src/bonfire/onboard/protocol.py:114-118`.

When a callback **is** installed and raises, `_ws_handler` logs the
exception via `logger.exception("on_message callback failed")` and
continues reading from the socket
(`src/bonfire/onboard/server.py:180-183`).

## 4. State machine

The server drives the entire state machine. The client is a pure presenter
that reacts to incoming events; aside from the three `user_message` sends,
it makes no state decisions of its own.

```
                     [ TCP connect to /ws ]
                              |
                              v
                  +-----------------------+
                  |  Act I: Scan Theater  |
                  +-----------------------+
                              |
                  scan_start (panels[6])
                              |
                              v
        +------------------------------------------------------+
        | Six panels run concurrently in asyncio.gather. The   |
        | wire interleaves these three event types arbitrarily |
        | between panels for the duration of Act I:            |
        |                                                      |
        |   scan_update     (one row from any panel)           |
        |   falcor_message  (subtype=narration; emitted by     |
        |                    flow.scan_emit immediately after  |
        |                    a scan_update, when the engine    |
        |                    decides to narrate)               |
        |   scan_complete   (panel=<one of six>; emitted by    |
        |                    _run_one as soon as that panel's  |
        |                    scan() returns)                   |
        |                                                      |
        | A panel's scan_complete may fire while other panels  |
        | are still emitting scan_updates and narrations. The  |
        | only guarantee is that a panel's own scan_updates    |
        | precede its own scan_complete.                       |
        +------------------------------------------------------+
                              |
                  all_scans_complete (total_items)   # the only barrier
                              |
                  ~ 0.5 s pause (server-side)
                              |
                              v
                  +-----------------------+
                  |  Act II: Conversation |
                  +-----------------------+
                              |
                  conversation_start
                              |
                  falcor_message (subtype=question)   # Q1
                              |
                          <-- user_message            # A1
                              |
                  falcor_message (subtype=reflection)
                              |
                  falcor_message (subtype=question)   # Q2
                              |
                          <-- user_message            # A2
                              |
                  falcor_message (subtype=reflection)
                              |
                  falcor_message (subtype=question)   # Q3
                              |
                          <-- user_message            # A3
                              |
                  falcor_message (subtype=reflection)
                              |
                              v
                  +-----------------------+
                  |  Act III: Config Gen  |
                  +-----------------------+
                              |
                  config_generated (config_toml + annotations)
                              |
                  bonfire.toml written to project root
                              |
                              v
                       [ client may close ]
                              |
                  shutdown_event fires server-side
```

Source for this ordering: `src/bonfire/onboard/flow.py:39-115` (top-level
flow), `src/bonfire/onboard/orchestrator.py:60-84` (Act I event order),
`src/bonfire/onboard/conversation.py:389-446` (Act II event order),
`src/bonfire/onboard/flow.py:107-114` (Act III).

`all_scans_complete` is the only Act-I barrier. A driver that gates further
work on having seen `scan_complete` (for any panel, or for "the last"
panel) is buggy: per `src/bonfire/onboard/orchestrator.py:104-110`,
`_run_one` emits `ScanComplete` from inside that panel's own coroutine
the moment its `scan()` returns, while sibling panels in the same
`asyncio.gather` (`src/bonfire/onboard/orchestrator.py:79-80`) may still
be emitting `ScanUpdate`s. Drivers MUST treat `all_scans_complete` as the
sole transition signal out of Act I.

If the browser disconnects during Act I, the scan keeps running on the
server (the orchestrator is already in flight); subsequent broadcasts
become silent no-ops because `FrontDoorServer.broadcast` early-returns
when no clients remain (`src/bonfire/onboard/server.py:107-110`). The
flow then proceeds into Act II and hangs at `await
conversation_done.wait()` (`src/bonfire/onboard/flow.py:99-101`) until
Ctrl-C — the comment in `flow.py` calls this out as accepted v1
behavior.

## 5. Asymmetries and gaps

This section names every place the protocol's two ends do not match
exactly, so a future driver author does not waste time chasing
ghost messages.

- **`subtype="question"` vs `subtype="reflection"` are merged in the JS.**
  Both render via `addChatMessage('falcor', ...)`
  (`src/bonfire/onboard/ui.html:354-357`). Only `narration` is routed
  separately. A driver that wants to label or persist questions vs
  reflections must use the protocol-level `subtype`, not a UI signal.
- **`config_generated` payload is unrendered.** The browser only updates
  the status banner (`ui.html:358`); `config_toml` and `annotations` are
  not displayed. The file on disk (`bonfire.toml`, written at
  `flow.py:112`) is the user-facing artifact today.
- **`scan_start.panels` is informational only.** The browser ignores the
  list and gates rendering on a hardcoded `KNOWN_PANELS` array
  (`ui.html:362`). A driver that adds a seventh scanner would need to
  update that array or the panels would be silently dropped at
  `ui.html:365`.
- **No server-side ack for `user_message`.** The conversation engine's
  reflections double as implicit acknowledgement, but there is no
  protocol-level confirmation. A client cannot tell whether a message was
  received from the protocol alone; reconnection after a dropped frame is
  not supported.
- **No `error` / `warning` event type.** Scanner exceptions are swallowed
  by `_run_one` (`orchestrator.py:106-108`) and surface only as
  `scan_complete` with `item_count=0`. Other server-side failures (e.g.
  `on_message` raising) are logged (`server.py:182-183`) but never
  reported on the wire.
- **Connection lifecycle is single-session.** The server fires
  `shutdown_event` when the last connected client disconnects after at
  least one had ever connected (`server.py:185-187`); `bonfire scan`
  awaits this and exits (`scan.py:41`). Reconnecting a fresh tab during
  Act II does not resume — it would receive zero past events and the
  server would still be awaiting the next answer.
- **`parse_server_message` exists but has no production caller.** The
  helper at `src/bonfire/onboard/protocol.py:160-162` is documented "for
  testing"; the server never parses its own outgoing payloads. A driver
  on the client side may use it to validate received frames against the
  Pydantic models.
- **`parse_client_message` is in the same condition.** The helper at
  `src/bonfire/onboard/protocol.py:155-157` exists alongside
  `parse_server_message` but is bypassed by the production handler:
  `_ws_handler` calls `json.loads` directly
  (`src/bonfire/onboard/server.py:175`) and dispatches the resulting
  `dict` to the `on_message` callback without going through the Pydantic
  model. Client-side framing errors that the model would catch (missing
  fields, wrong types) therefore reach the application layer as raw
  `dict`s; `flow.on_message` handles this by ignoring frames whose
  `data.get("type") != "user_message"` (`flow.py:84-85`). A driver
  reusing this server should call `parse_client_message` itself if it
  wants Pydantic validation.

## 6. Versioning

There is **no** explicit protocol-version field. Today the protocol is
embedded in a single repo (server + bundled HTML/JS) so the two ends
upgrade together. If/when an external driver speaks this protocol against
an installed `bonfire-ai`, a `protocol_version` field on
`scan_start` is the obvious extension point — but adding it is out of
scope for this spec.
