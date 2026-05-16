# Changelog

All notable changes to `bonfire-ai` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — UNRELEASED

The first stable release of `bonfire-ai`. Bonfire is a pipeline runtime
for AI agents — it wires role-bound stages over a typed event bus, enforces
TDD at the role boundary, and ships the four extension Protocols
(`AgentBackend`, `VaultBackend`, `QualityGate`, `StageHandler`) that
together form the trust triangle a production deployment composes against.
This section is staged ahead of the v0.1.0 tag-cut PR; when that PR lands
it will (a) bump `pyproject.toml` from `0.1.0a2` to `0.1.0`, (b) advance
the PyPI `Development Status` classifier from `3 - Alpha` to `4 - Beta`,
and (c) date this entry to its tag-cut day. The release-gate-ladder items
are closed in code or accepted-with-documentation per the policy in
[`docs/release-policy.md`](docs/release-policy.md); some still surface
follow-ups that ship in subsequent v0.1.x patches.

Two patches on top of [0.1.0a2] dominate the surface delta: a coordinated
hardening pass across the dispatch, scanner, persona, git, and Front Door
modules, and a performance pass that takes Vault ingest from
quadratic to linear. Everything else is sharpening: a clarified `bonfire
scan --no-browser` contract, a documented WebSocket protocol for the
onboarding flow, and the CI and pre-commit wiring that make "the suite
passes" mean what it should on the integration branch.

### Added

- **WebSocket protocol specification for `bonfire scan`.** A complete spec
  of the `FrontDoorServer` ↔ client message exchange ships at
  `docs/scan-front-door-protocol.md`. Every event and message in the spec
  carries a `file:line` citation back to its emit or handler site, so
  third-party clients can implement against the spec rather than
  re-deriving the protocol from source.
- **Headless scan driver script.** `scripts/petri_conversational_driver.py`
  is a minimal Python WebSocket client that drives `bonfire scan
  --no-browser` end-to-end without a browser — spawn, parse the URL, log
  every event, reply to onboarding questions, and exit cleanly on
  `config_generated`. Surfaces a `scan_phase` state-machine discriminator
  (`pending`/`scanning`/`conversing`/`done`) and a configurable
  per-message receive timeout (`--timeout-seconds`, default 120s).
- **Pre-commit configuration.** `.pre-commit-config.yaml` ships at the
  repo root with `ruff check` and `ruff format` hooks that mirror the CI
  gate. Run `pre-commit install` once after cloning to catch lint and
  format issues locally before pushing.

### Changed

- **Version bump to `0.1.0`.** PyPI classifier advances from `Development
  Status :: 3 - Alpha` to `4 - Beta` per
  [`docs/release-policy.md`](docs/release-policy.md). The
  `bonfire-ai==0.1.0` install is the first non-alpha drop.
- **BREAKING: `DispatchOptions.permission_mode` default flipped to
  `"default"` (SDK ask-mode).** The previous default `"dontAsk"` is now
  framed as defense-in-depth rather than the primary trust gate; explicit
  `permission_mode="dontAsk"` opt-ins in `handlers/wizard.py` and
  `handlers/sage_correction_bounce.py` continue to behave as before.
  Callers that today inherit the default will now run agents in
  SDK ask-mode. Handlers that need autonomous behavior must opt in
  explicitly. Review your call sites before upgrading from `0.1.0a*`.
- **`bonfire scan --no-browser` is documented as WebSocket-driven, not
  browser-suppressed.** The flag never disabled the Front Door server —
  it only suppressed `typer.launch(url)`. Help text, runtime echo, and
  module docstrings now say so. With `--no-browser` set, the wait line
  reads `Waiting for client connection at <ws_url>` instead of the prior
  `Waiting for browser connection...`. The default browser-launch path
  is unchanged.
- **`InMemoryVaultBackend.exists()` is now O(1).** A parallel hash-set
  index turns the previous linear scan into a constant-time membership
  check. n-entry ingest was O(n²) before this change; it is now O(n).
- **Vault query lowercasing is now cached.** `query()` no
  longer re-lowercases each entry's content on every call; a lazy
  parallel cache fills on first query, and ingest-heavy workloads that
  never query never pay the cost.
- **LanceDB `exists()` is filter-only.** The zero-vector ANN search is
  gone; existence checks no longer carry per-call embedding cost.
  Semantics preserved.
- **Cost-ledger parsing is memoized.** `cost.analyzer` now caches the
  parsed ledger keyed by `(mtime, size)`; repeated `bonfire cost`
  invocations within a session reuse the parsed structure. A new
  raw-dict aggregation path on cold queries skips the Pydantic
  round-trip.
- **CLI cold-start is ~6× faster.** `bonfire --version` and
  `bonfire --help` no longer drag `websockets`, `bonfire.onboard.server`,
  or `bonfire.cost.analyzer` into the import graph. Cold start measured
  ~451 ms before this change and ~73 ms after, on the same machine. A
  forbidden-modules contract test pins the boundary so future imports
  cannot silently re-inflate the cold path.
- **`dispatch/` package surface.** `ToolPolicy`, `DefaultToolPolicy`, and
  `SecurityHooksConfig` are now re-exported at `bonfire.dispatch` so
  contributors implementing custom tool policies do not have to reach
  into submodules. The package docstring is corrected to describe
  `TierGate` accurately as a no-op stub (the prior text claimed it
  enforced quotas, which it does not).
- **`bonfire scan` documentation rephrased as "WS-driven" instead of
  "browser-based".** The short-form docstrings on `scan` and `_run_scan`
  drop the browser-only framing.

### Fixed

- **Front Door server survives multiple `asyncio.run()` calls.**
  `FrontDoorServer.__init__` previously constructed its `asyncio.Event`
  instances eagerly, binding them to whichever loop was current at
  construction time. Embedders that reused a server across loops hit
  `RuntimeError: <Event> is bound to a different event loop` on the
  second `await`. Events are now created lazily inside `start()`, so
  every `start()` rebinds them to the current loop.
- **`bonfire persona set <name>` no longer corrupts `bonfire.toml` with
  hostile names.** All three TOML write sites route through a shared
  `escape_basic_string` helper; persona names containing quotes,
  newlines, control characters, or fake section headers are escaped
  rather than written through.
- **`PersonaLoader.load(name)` validates names with a slug pattern.**
  Path-traversal probes like `PersonaLoader.load("../../etc/passwd")`
  now short-circuit with a single WARNING and never touch the
  filesystem.
- **MCP scanner is bounded, symlink-safe, and non-blocking.**
  `_read_servers_from_config` enforces a 1 MiB size cap (overridable via
  `BONFIRE_MCP_SCAN_MAX_BYTES`), rejects symlinks whose resolved target
  escapes the home or project root, and reads via `asyncio.to_thread`
  to keep the event loop unblocked.
- **`git_state` scanner emits error events instead of silently dropping
  panels.** `_run_cmd`'s return type tightened to
  `tuple[int | None, str]`; non-zero git exit codes (corrupt
  `.git/HEAD`), `returncode is None`, and timeouts now produce a
  recognizable `ScanUpdate`. The scanner also treats a no-commit repo
  (where `git log` legitimately fails) as a benign empty state.
- **`rm -rf` security pattern matches ephemeral tokens at path-segment
  boundaries.** The previous substring lookahead let unsafe paths like
  `rm -rf __pycache__-backup/db` slip through DENY. The lookahead now
  requires the ephemeral token (`__pycache__`, `node_modules`, `.venv`,
  `dist`, `build`) to sit at a real path-segment boundary.
- **User-supplied security-hook regexes compile once.** Patterns are
  hoisted to compile time in the hook factory; the broken-pattern
  fail-safe DENY path is preserved.
- **Bounce-back stages count against `budget_usd`.** After a successful
  bounce-back, the pipeline previously credited only the retried
  stage's cost to `total_cost_usd`, silently dropping the bounce-target
  stage's cost. A run that should have halted at the budget cap could
  slip past it. `total_cost_usd` now includes both the bounce target
  and the retry, and the budget watchdog halts correctly.

### Security

- **Remote-URL sanitization is now `urlsplit`-based.** The previous
  five-step `re.sub` chain has been replaced with a single
  `urllib.parse.urlsplit` parse. SCP-style `git@host:path` URLs are
  rewritten to `ssh://host/path` first so the same parser handles both
  shapes. Userinfo and the entire query string are dropped, so
  `?token=...` and GHSA-style credentials no longer leak through scan
  output.
- **Git subprocess errors no longer echo subcommand args, stderr, or
  commit messages.** `_run_git` now raises a redacted `RuntimeError`
  naming only the subcommand and exit code. A new `verbose: bool = False`
  keyword opts in to full detail for debugging.
- **Claude-memory settings scan reports structure, not values.** When
  scanning `~/.claude/settings.json` and project-local equivalents,
  `model` is reported as `value="set"` (no literal); `permissions` is
  reported as `value=f"{N} key(s)"` with `detail` listing only the
  sorted top-level keys. Nested contents are never emitted.
- **SDK backend traceback redaction.** `ClaudeSDKBackend.execute` no
  longer stores `traceback.format_exc()` on persisted envelopes by
  default. The `ErrorDetail.traceback` field is a single-frame
  `file:line: ExceptionType: message` summary, so prompts and agent
  options can no longer leak through tracebacks into long-lived session
  JSONL. Set `BONFIRE_DEBUG_TRACEBACKS=1` to restore the full traceback
  during debugging.

### Internal

- CI now runs on the `v0.1` integration branch in addition to `main`, so
  required status checks actually fire on the branch where feature work
  lands.
- `ruff` is pinned to an exact version in both pre-commit and CI to keep
  the two surfaces from drifting.
- The release-gate Box image puts `claude-code` on `PATH` for the
  unprivileged `box` user and bakes in `python3-pytest` and
  `python3-yaml` so the in-box gate-verdict script can actually run.
  `claude --version` is asserted at image build time — a broken install
  now fails the build instead of surfacing as a runtime `exit:127`.
- W4.1 framing reconciled across `dispatch/tool_policy.py`,
  `docs/release-policy.md`, and `CLAUDE.md`: the `ToolPolicy` extension
  Protocol IS the user-configurable surface; no TOML loader ships in
  v0.1. Users override the default allow-list floor by implementing
  `ToolPolicy` and passing it into `StageExecutor` / `PipelineEngine`
  via the `tool_policy=` kwarg.

<!-- TODO restore the permalink line below when v0.1.0 tag actually cuts -->
<!-- [0.1.0]: https://github.com/BonfireAI/bonfire/releases/tag/v0.1.0 -->

## [0.1.0a2] — 2026-05-05

Lands the first declarative integration surface — Instruction Set Markup
(ISM) v1 — alongside the OIDC-driven PyPI release workflow and a cluster of
developer-environment compatibility fixes. First end-to-end exercise of the
new release pipeline.

### Added

- **Instruction Set Markup (ISM) v1.** Declarative third-party tool
  integrations as markdown + YAML documents instead of hand-coded Python.
  Frozen Pydantic schema in `src/bonfire/integrations/document.py`
  (`ISMDocument`, `ISMCategory` covering forge / ticketing / comms / vault /
  ide, `DetectionRule` discriminated union over command / env_var /
  file_match / python_import, `Credentials`, `Fallback`, `ISMSchemaError`).
  Two-tier loader at `src/bonfire/integrations/loader.py` with builtin +
  user discovery, mirroring `bonfire.persona.loader.PersonaLoader`. First
  reference adapter ships at
  `src/bonfire/integrations/builtins/github.ism.md` — forge category,
  declares `pr.open` / `pr.merge` / `pr.review` / `issue.close`, detects via
  `gh` CLI + `GITHUB_TOKEN` / `GH_TOKEN` env + `.git/config`. The wheel
  include in `pyproject.toml` is extended so `.ism.md` files ship.

### Changed

- The PyPI publishing workflow now (a) serializes per-tag publishes via a
  workflow-level `concurrency` block, (b) guards the build job on the ref
  being a tag so manual dispatches from non-tag refs do not attempt to
  publish, (c) pins `pypa/gh-action-pypi-publish` to a commit SHA rather
  than the floating `release/v1` ref, and (d) runs `twine check --strict`
  so a malformed long-description fails the build before publish.
- The release-gate Box Dockerfile is now compatible with hosts whose first-
  user UID is not 1000. The container's runtime user takes its UID/GID from
  the operator's host at build time via `--build-arg BOX_UID=$(id -u)`.
- `tests/e2e/scripts/e2e-runner.sh` mints its session UUID from the kernel
  random source (`/proc/sys/kernel/random/uuid`) rather than `uuidgen`,
  removing a userspace package dependency.

### Fixed

- `tests/unit/test_scan_cli.py::test_scan_help_shows_options` is now robust
  to ANSI escape codes Typer/Rich emit when `FORCE_COLOR=1` is set on CI
  runners.
- The shellcheck contract test for the release-gate runner script passes
  after a static-analysis false positive on the EXIT trap was silenced via
  an inline `disable=SC2154` directive.
- The lint backlog under `tests/unit/` is cleared: 16 mechanical ruff
  violations auto-fixed (import ordering, unused imports, mid-file imports),
  plus a `tests/**` per-file ignore for `E501` so docstring lines that
  quote real code-under-test signatures verbatim do not need to wrap.

## [0.1.0a1] — 2026-05-03

> Renamed from `[0.1.0]` to `[0.1.0a1]` 2026-05-03. The original `0.1.0`
> tag shipped on 2026-04-28; the alpha label is restored to honestly
> reflect that release-gate items in [`docs/release-gates.md`](docs/release-gates.md)
> remain open. Stable `v0.1.0` is the future tag once they all clear.

Frame shipped, operations deferred. Bonfire ships the pipeline engine,
the nine-role cadre, the four extension protocols, the persona system
(default + minimal + an optional example), the browser-based `bonfire
scan` onboarding, the cost ledger, and a deterministic merge-preflight
stage. Knowledge-graph storage ("the vault") and the `bonfire run`
end-to-end CLI verb are still in progress and ship in subsequent
0.1.x alpha releases.

### Added

- Pipeline engine with role-specialised stages: researcher, tester,
  implementer, verifier, publisher, reviewer, closer, synthesizer,
  analyst.
- Quality gates between stages with TDD enforcement at the role
  boundary (RED tests from the tester, GREEN code from the implementer,
  independent verification before publish).
- Per-role model routing through `resolve_model_for_role` with three
  capability tiers (`reasoning`, `fast`, `balanced`). Pure synchronous
  resolution; never raises on a string input.
- BYOK configuration via `bonfire.toml` with environment variable
  overlay (`BONFIRE_` prefix, `__` nested delimiter).
- CLI subcommands: `init`, `scan`, `status`, `resume`, `handoff`,
  `persona`, `cost`. The installed console script is `bonfire`.
- Browser-based onboarding scan (`bonfire scan`) over WebSocket.
- Persona system for display-only CLI output styling. Personas affect
  CLI presentation only — never agent prompts, never quality
  standards.
- Four `@runtime_checkable` extension protocols: `AgentBackend`,
  `VaultBackend`, `QualityGate`, `StageHandler`. Composition root
  verifies conformance at registration time.
- Priority-based prompt truncation with `PromptBlock` and U-shape
  ordering for long-context model use.
- `MergePreflightHandler` — a deterministic merge-preflight pipeline
  stage that runs the full pytest suite against the simulated merged
  tip before merge, detecting cross-wave interactions between sibling
  PRs targeting the same base. Six-verdict classifier with
  first-match-wins ordering: `green`, `pre_existing_debt` (allow with
  annotation), `cross_wave_interaction`, `pure_warrior_bug`,
  `pytest_collection_error`, `merge_conflict`. Wired into
  `standard_build()` between `wizard` and `steward` via
  `MergePreflightGate`. Backed by the new
  `bonfire.git.scratch.ScratchWorktreeFactory` primitive. See
  `docs/pipeline-stages.md` and `docs/product/discipline.md`.
- `GitHubClient.list_open_prs(base, *, exclude=None)` and the frozen
  `PRSummary` Pydantic model, used by the merge-preflight stage for
  sibling-batch detection. `MockGitHubClient` carries matching
  parity (`set_open_prs` configures canned data; `list_open_prs`
  returns it).
- `META_PREFLIGHT_CLASSIFICATION` and
  `META_PREFLIGHT_TEST_DEBT_NOTED` metadata-key constants on
  `bonfire.models.envelope`.
- Per-role model tier resolution wired through the dispatch engine
  (envelope-level `model` precedence preserved; falls back to the
  configured tier on absence).
- `py.typed` marker file shipped in the wheel, satisfying PEP 561 for
  the `Typing :: Typed` classifier.

### Changed

- **Cadre display rename (BREAKING).** The verifier role's gamified
  display name moves from `"Assayer"` to `"Cleric"`; the closer role's
  from `"Herald"` to `"Steward"`. Generic identifiers (`verifier`,
  `closer`) and professional names (`Verify Agent`, `Release Agent`)
  are unchanged. The workflow alias key `"assayer"` in
  `GAMIFIED_TO_GENERIC` becomes `"cleric"`; `"herald"` becomes
  `"steward"`. The closer pipeline-stage name in `standard_build()` is
  now `"steward"` (was `"herald"`). Update any code that pinned the
  prior strings; no backward-compatibility alias ships.
- **Closer handler module rename (BREAKING).** `bonfire.handlers.herald`
  is renamed to `bonfire.handlers.steward`; the class `HeraldHandler`
  becomes `StewardHandler`. Envelope metadata keys `"herald_verdict"`
  and `"herald_pr"` are renamed to `"steward_verdict"` and
  `"steward_pr"` respectively. Imports update from
  `from bonfire.handlers.herald import HeraldHandler` to
  `from bonfire.handlers.steward import StewardHandler`. Git history
  for the file is preserved through `git mv`. A lineage breadcrumb in
  the new module's docstring records the predecessor name.
- **Wizard PR review heading.** The fail-safe review-body H1 emitted
  by the reviewer handler is now plain `## Code Review` (was
  `## Wizard Code Review`). Bonfire does not stamp its cadre vocabulary
  onto a downstream repo's PR surface. The matching source-scan
  exemption in the test suite is removed; the assertion now holds
  without special-casing.
- **Default persona becomes Falcor (BREAKING wire-protocol change).**
  Bonfire now ships **Falcor**, the luckdragon — gentle, encouraging,
  the friendly voice at your shoulder while the work runs. The
  predecessor persona (Passelewe, the Chamberlain) was retired; the
  character lives only as a lore breadcrumb at
  `docs/_lore/passelewe.md`. The persona builtins directory
  `src/bonfire/persona/builtins/passelewe/` was deleted; a new
  `src/bonfire/persona/builtins/falcor/` ships with a distinct phrase
  bank in the gentle/encouraging register. `Config.persona` default
  flips from `"default"` to `"falcor"`. The Front Door wire-protocol
  message class `PasseleweMessage` is renamed to `FalcorMessage`; the
  WebSocket type literal `"passelewe_message"` becomes
  `"falcor_message"`. **No backward-compatibility alias ships** -- v0
  consumers update in lockstep. The `default` and `minimal` builtins
  remain available as user-selectable alternates via
  `bonfire persona set <name>`. The scan-narration line library at
  `src/bonfire/onboard/narration.py` retains its existing wry
  observational tone; a re-tone pass to match Falcor's register is
  deferred to a follow-up.
- **CLI sweep-guard hack removed.** The `_DEFAULT_PERSONA = "passe" +
  "lewe"` string-concatenation hack in `src/bonfire/cli/app.py` and
  `src/bonfire/cli/commands/persona.py` is gone -- `_DEFAULT_PERSONA`
  is now the bare literal `"falcor"`. The rename-sweep test continues
  to ban `"passelewe"` in src/ (the predecessor persona is gone, so
  any reference is stale).
- Default `base_branch` value updated from `"master"` to `"main"`
  across the git layer and pipeline configuration.
- `Development Status` PyPI classifier advanced from `3 - Alpha` to
  `4 - Beta` per `docs/release-policy.md`.
- `__version__` is now resolved at import time via
  `importlib.metadata.version("bonfire-ai")`, with a hard-coded
  fallback for editable / unbuilt checkouts. Single source of truth
  for the installed version.

### Fixed

- Re-exported `ModelCost` from `bonfire.cost.__init__` so external
  consumers can `from bonfire.cost import ModelCost` without reaching
  into the submodule.

### Removed

- `rich` runtime dependency. The package was declared but never
  imported; removing it shrinks the install footprint and removes
  unused transitive deps (markdown-it-py, mdurl, Pygments, etc.). May
  return as an optional dependency in a future release if rich-rendered
  CLI output is wired.

### Known Limitations

- The default `VaultBackend` implementation lands in a later 0.1.x
  release. The protocol is stable; the storage backend is not.
- The end-to-end `bonfire run` workflow is incomplete; pipeline
  stages exist but the orchestrator is wired progressively across
  0.1.x.
- CI matrix runs only Python 3.12 today. The `Programming Language ::
  Python :: 3.13` classifier will be claimed once 3.13 is added to
  CI and stays green.

### Notes

- Pre-v0.1.0a2 commit history on the `v0.1` branch contains internal-tracker
  references (e.g., `BON-NNN`) in commit subjects. This is accepted as
  historical through the v0.1.0a2 alpha release; the public tree's strict
  enforcement begins with the next post-alpha sweep. New commits from that
  point on comply with [CONTRIBUTING.md](CONTRIBUTING.md) per repo policy.

[0.1.0a1]: https://github.com/BonfireAI/bonfire/releases/tag/v0.1.0a1
[0.1.0a2]: https://github.com/BonfireAI/bonfire/releases/tag/v0.1.0a2
