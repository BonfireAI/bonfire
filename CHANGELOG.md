# Changelog

All notable changes to `bonfire-ai` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-28

First public functional release. Bonfire ships pipeline primitives, BYOK
model routing, persona-driven CLI output, the browser-based onboarding
scan, and a deterministic merge-preflight stage. Knowledge-graph storage
("the vault") and the end-to-end project workflow remain in progress and
will ship in subsequent 0.1.x releases.

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
  `standard_build()` between `wizard` and `herald` via
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

[0.1.0]: https://github.com/BonfireAI/bonfire/releases/tag/v0.1.0
