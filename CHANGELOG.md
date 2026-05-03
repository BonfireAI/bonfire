# Changelog

All notable changes to `bonfire-ai` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

- Pre-v0.1.0a1 commit history on the `v0.1` branch contains internal-tracker
  references (e.g., `BON-NNN`) in commit subjects. This is accepted as
  historical for the v0.1.0a1 alpha release. New commits comply with
  [CONTRIBUTING.md](CONTRIBUTING.md) per repo policy.

[0.1.0a1]: https://github.com/BonfireAI/bonfire/releases/tag/v0.1.0a1
