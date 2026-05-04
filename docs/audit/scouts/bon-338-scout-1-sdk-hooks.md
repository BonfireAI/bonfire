# Scout-1 / BON-338 / SDK Hooks — Report

**SDK version:** `claude_agent_sdk==0.1.60`, bundled Claude Code CLI `2.1.111`. All citations from installed SDK; URLs fetched 2026-04-18.

## 1. Hook Types Available

Python SDK exposes **10 hook events** via `HookEvent` literal union (`types.py:216-227`):

```
PreToolUse | PostToolUse | PostToolUseFailure | UserPromptSubmit |
Stop | SubagentStop | PreCompact | Notification | SubagentStart |
PermissionRequest
```

**Python SDK does NOT expose `SessionStart`/`SessionEnd` as callback hooks** — TypeScript has them, Python does not. Use shell-command hook in `.claude/settings.json` + `setting_sources=["project"]`, or trigger on first message.

### Per-event input schemas

| Event | TypedDict (types.py line) | Extra fields | Can block? |
|---|---|---|---|
| PreToolUse | 265-271 | tool_name, tool_input, tool_use_id, agent_id/type | **Yes — primary security gate** |
| PostToolUse | 274-281 | tool_name, tool_input, tool_response, tool_use_id | No (can inject context) |
| PostToolUseFailure | 284-292 | tool_name, tool_input, tool_use_id, error | No |
| UserPromptSubmit | 295-299 | prompt | Yes (decision: "block") |
| Stop | 302-306 | stop_hook_active | Yes |
| SubagentStop | 309-316 | stop_hook_active, agent_id, agent_transcript_path | Yes |
| PreCompact | 319-324 | trigger, custom_instructions | Yes |
| Notification | 327-333 | message, title, notification_type | No |
| SubagentStart | 336-341 | agent_id, agent_type | No |
| PermissionRequest | 344-350 | tool_name, tool_input, permission_suggestions | Yes |

### Callback signature (`types.py:520-527`)

```python
HookCallback = Callable[
    [HookInput, str | None, HookContext],
    Awaitable[HookJSONOutput],
]
```

Args: `input_data`, `tool_use_id`, `context` (currently `{"signal": None}`).

**Return type:** `HookJSONOutput = AsyncHookJSONOutput | SyncHookJSONOutput` (types.py:448-507). `{}` is valid = "allow, no mods."

**Registration via `HookMatcher` (types.py:531-545):** `matcher` regex, `hooks` list, `timeout` default 60s. Stored in `ClaudeAgentOptions.hooks: dict[HookEvent, list[HookMatcher]]`.

## 2. Denial Semantics — **Load-bearing for BON-338**

Two different denial wire-formats. `PreToolUse` uses `hookSpecificOutput`, not top-level `decision`.

### PreToolUse deny (BON-338 path)

`PreToolUseHookSpecificOutput` (types.py:369-376) carries `permissionDecision: Literal["allow","deny","ask"]` + `permissionDecisionReason`.

```python
return {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "rm -rf / blocked by Bonfire security hook",
    }
}
```

**What the agent sees on deny:** CLI surfaces `permissionDecisionReason` to the model as tool-call feedback. NOT a silent drop, NOT unrecoverable. Docs verbatim:

> "When a hook returns `permissionDecision: 'deny'`: 1) Tool call is blocked — does not execute. 2) Claude sees the reason. 3) Model can retry. 4) Not a hard stop — unless you use `'continue': false`."

Convert to hard stop: add `"continue_": False` + `stopReason`.

### Decision precedence

`deny > defer > ask > allow`. Multiple hooks compose safely — any deny wins.

### Other events

`PostToolUse`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact` use top-level `decision: Literal["block"]` + `reason` on `SyncHookJSONOutput` (types.py:499-501).

### `updatedInput` — sanitize instead of deny

`PreToolUseHookSpecificOutput.updatedInput` (types.py:375) lets hook rewrite input. **Must also return `permissionDecision: "allow"`**. Useful lever: instead of denying `git push --force main`, rewrite to `git push origin feature-branch`.

## 3. Async Support

**Python hooks MUST be `async def`** — callback type is `Callable[..., Awaitable[HookJSONOutput]]`. Plain `def` raises at dispatch time. Wrap blocking I/O in `asyncio.to_thread()`.

### Fire-and-forget mode

`AsyncHookJSONOutput` (types.py:448-460):
```python
asyncio.create_task(send_to_audit_log(input_data))
return {"async_": True, "asyncTimeout": 30000}
```

Cannot block, modify, or inject context — agent has moved on. Only for pure side effects. **NOT applicable to BON-338's deny path.**

### Performance

Hooks invoked over control protocol (JSON-line channel). Each PreToolUse adds one round-trip per tool call. Default timeout 60s per `HookMatcher.timeout`.

## 4. Ordering With `allowed_tools`

**Hooks run FIRST.** Flow: Hooks → Deny rules → Permission mode → Allow rules → canUseTool.

### Implications for BON-338

- **Hook returning `deny` always wins.** Even with `allowed_tools=["Bash"]` and `permissionMode="bypassPermissions"`, PreToolUse deny blocks. This is the correct defense-in-depth layer over BON-337's allow-lists.
- **Hook returning `allow` does NOT override later deny rule.** Deny rules hold in every mode, including `bypassPermissions`. Hook's `"allow"` is pre-approval skipping permission prompt, NOT bypass of `disallowed_tools`.
- **Hook returning `{}` passes through** — allow-list, permission mode, canUseTool continue normally. **Recommended default for BON-338:** return `deny` on match; pass through otherwise.
- **Hooks run under `bypassPermissions`.** Bonfire can enforce destructive-command denylist even when operator sets `bypassPermissions` for velocity.

### Within single PreToolUse event

Multiple hooks execute in array order. Decisions combined with `deny > defer > ask > allow`. Chain order matters only for side effects.

## 5. Hook Context

PreToolUse receives:
- `session_id: str`
- `transcript_path: str` (on-disk JSONL transcript — hook can read for audit)
- `cwd: str`
- `permission_mode: str` (optional)
- `hook_event_name: "PreToolUse"`
- `tool_name: str` — `"Bash"`, `"Write"`, `"mcp__playwright__..."`
- `tool_input: dict[str, Any]` — raw args (e.g. `{"command": "rm -rf /", "timeout": 30000}`)
- `tool_use_id: str`
- `agent_id: str` (optional) — present in sub-agent
- `agent_type: str` (optional) — e.g. `"general-purpose"`

### CANNOT see directly

- **User identity / auth principal** — `ClaudeAgentOptions.user` exists but not passed to hooks. Must smuggle via closure (factory capturing `role="Warrior"`).
- **Full transcript in memory** — only `transcript_path`.
- **Other concurrent tool calls** — each invocation isolated; use `agent_id` as partition key.
- **Tool's return value** — that's PostToolUse.

## 6. Error Handling — Fail-Closed at Control Layer

**Uncaught exception:** SDK catches at `_internal/query.py:369-379`:
```python
except Exception as e:
    error_response: SDKControlResponse = {
        "type": "control_response",
        "response": {"subtype": "error", "request_id": request_id, "error": str(e)},
    }
```

Tool call does NOT proceed, but behavior is less specified than clean deny.

### BON-338 guidance

1. **Never raise from security hook.** Wrap body in try/except. On error return explicit `permissionDecision: "deny"` with reason `f"security-hook-error: {exc!r}"`.
2. **Log exceptions separately** before returning deny.
3. **Unit test exception path** — inject malformed input, assert envelope denies.

### Timeouts

60s default per `HookMatcher.timeout`. CLI enforces. Keep pattern-matching O(microseconds). Set generous timeout if hook calls external audit service.

**Shell-command hook exit codes** (0 = stdout JSON, 2 = blocking error, 1/other = non-blocking) DO NOT apply to Python SDK callback hooks — different path through JSON control protocol.

## 7. Stateful Hooks & Arg Modification

### Stateful — YES via closures

```python
def make_bash_rate_limiter(max_per_minute: int = 30):
    calls: list[float] = []
    async def hook(input_data, tool_use_id, context):
        if input_data["tool_name"] != "Bash":
            return {}
        now = time.monotonic()
        calls[:] = [t for t in calls if now - t < 60.0]
        if len(calls) >= max_per_minute:
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Bash rate limit: {max_per_minute}/min exceeded",
            }}
        calls.append(now)
        return {}
    return hook
```

**Concurrency caveat:** parallel sub-agent hooks interleave over same control channel. Wrap mutations in `asyncio.Lock` or use `input_data["agent_id"]` as partition key.

### Arg modification — YES via `updatedInput`

```python
async def redirect_to_sandbox(input_data, tool_use_id, context):
    if input_data["hook_event_name"] != "PreToolUse" or input_data["tool_name"] != "Write":
        return {}
    original_path = input_data["tool_input"].get("file_path", "")
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",  # REQUIRED
            "updatedInput": {
                **input_data["tool_input"],  # preserve unchanged fields
                "file_path": f"/sandbox{original_path}",
            },
        }
    }
```

Gotchas: `updatedInput` replaces entire input object; spread `**input_data["tool_input"]` to keep other fields. Without `permissionDecision: "allow"`, silently ignored.

## 8. Private V1 Existing Wiring

**No hooks currently configured in either Bonfire tree.**

- `bonfire-public/src/bonfire/dispatch/sdk_backend.py:99-110` — builds `ClaudeAgentOptions` with 10 kwargs. **No `hooks` kwarg.**
- `bonfire/src/bonfire/dispatch/sdk_backend.py:187-199` — same for private V1. No `hooks`, no `can_use_tool`.
- Grep for `HookMatcher|HookCallback|PreToolUse|PostToolUse|hook_callback|hooks=` across both `src/` trees — **zero hits outside SDK itself**.

**Clean seam:** Natural injection — new `ClaudeSDKBackend.__init__` kwarg `security_hooks: Sequence[HookCallback] | None = None`, plumbed into `ClaudeAgentOptions(hooks={"PreToolUse": [HookMatcher(matcher="Bash|Write|Edit", hooks=list(security_hooks))]}, ...)`.

### Notes

1. **Keep `allowed_tools` from BON-337.** Hook is outer gate; allow-list is inner. Deny-rules (`disallowed_tools`) hold even in `bypassPermissions`.
2. **Respect try-boundary in `sdk_backend.execute`.** Backend's top-level try/except (sdk_backend.py:76-85) converts any raise into FAILED envelope. **Security hook that raises will NOT propagate** — SDK catches first and replies with control-error. Hook itself must be the failsafe. Wrap-and-deny internally.

## Sources

### Installed SDK (ground truth)

- `.venv/.../claude_agent_sdk/types.py:216-227` — HookEvent union
- `types.py:231-365` — all hook input TypedDicts
- `types.py:369-507` — all hook output TypedDicts
- `types.py:520-527` — HookCallback signature
- `types.py:531-545` — HookMatcher
- `types.py:1212` — ClaudeAgentOptions.hooks
- `_internal/query.py:36-52` — async_/continue_ → async/continue
- `_internal/query.py:133-157` — hook init wire format
- `_internal/query.py:318-332` — callback dispatch
- `_internal/query.py:369-379` — exception → control_response error
- `_internal/client.py:27-43, 124-126` — _convert_hooks_to_internal_format
- `_cli_version.py` — CLI 2.1.111; `_version.py` — SDK 0.1.60

### Documentation (fetched 2026-04-18)

- [code.claude.com/docs/en/agent-sdk/hooks](https://code.claude.com/docs/en/agent-sdk/hooks)
- [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)
- [code.claude.com/docs/en/agent-sdk/permissions](https://code.claude.com/docs/en/agent-sdk/permissions)
- [github.com/anthropics/claude-agent-sdk-python/issues/381](https://github.com/anthropics/claude-agent-sdk-python/issues/381)

### Bonfire wiring

- `bonfire-public/src/bonfire/dispatch/sdk_backend.py:99-110` — no hooks
- `bonfire/src/bonfire/dispatch/sdk_backend.py:187-199` — no hooks in V1 either
- Zero grep hits for hooks across both trees
