# Cluster 351 — Scout (Artisan Lens)

**Stamp:** 2026-04-30T19:34:17Z
**Branch:** `antawari/cluster-351-scout-artisan`
**Base HEAD:** `81c9d21` (`origin/v0.1`)
**Scope:** D-FT cluster surfacing the dispatch + pipeline asymmetry left by the
parent ticket that wired `resolve_model_for_role` into three call sites
(`StageExecutor`, `PipelineEngine`, `WizardHandler`).
**Lens:** Artisan — code shape, refactor-fit, idiom alignment, seam discovery.
**Read-only.** No source edits.

---

## TL;DR (one paragraph)

The four cluster-351 D-FTs are not four independent fixes — they are four
viewpoints on a single missing seam: **`pipeline.py` does not carry an
`envelope.model` precedence step, so the line-451 assignment leaks a `model`
that nothing reads while the line-498 `DispatchOptions` chain re-resolves the
same answer with a different formula.** Land a `_resolve_model(spec_override,
envelope_model, role, settings, config) -> str` helper in
`bonfire.engine._model_resolver` (or as a `@staticmethod` on a small new
`ModelResolver` class), give pipeline + executor + wizard one shared call
site, and three of the four D-FTs collapse into one diff: the dead-weight
assignment vanishes (BON-613), the latent-coupling trap vanishes (BON-616),
and the `BonfireSettings()` per-instance pattern (BON-614) gets a natural
opt-in by accepting `settings` as a single threaded dependency. The TOML-raise
backward-compat surprise (BON-617) is a separate axis — the constructors
already take `settings: BonfireSettings | None`, so the proper fix is **not**
to swallow the raise, but to land a `BonfireSettings.from_environment()` (or
similar) factory the CLI composition root calls once at process boot, and let
the constructor fallback either raise loudly OR be removed entirely once
every internal caller threads settings through.

---

## A — Map of model-resolution flow (executor vs pipeline)

Three call sites, three slightly different precedence chains. Two reach
backend dispatch; one reaches a sub-dispatch inside a stage handler.

### A.1 Executor backend path

`src/bonfire/engine/executor.py`

| Stage | Line | Code | Contract |
|---|---|---|---|
| Build envelope | 191–198 | `Envelope(model=stage.model_override or "", ...)` | empty-string sentinel; resolver-friendly |
| Build options | 271–282 | `DispatchOptions(model=envelope.model or resolve_model_for_role(stage.role, self._settings) or self._config.model, ...)` | 3-tier precedence; `envelope.model` IS read |

The line-196 `or ""` is intentional — Sage code-synth memo cites
"independent convergence" between Warriors A and B that the line was needed
because `or self._config.model` would short-circuit and prevent the resolver
from being reached
(`code-synth-bon351.md:39`).

### A.2 Pipeline backend path

`src/bonfire/engine/pipeline.py`

| Stage | Line | Code | Contract |
|---|---|---|---|
| Build envelope | 451–458 | `Envelope(model=spec.model_override or self._config.model, ...)` | 2-tier; **envelope.model is dead-weight** |
| Build options | 502–513 | `DispatchOptions(model=spec.model_override or resolve_model_for_role(spec.role, self._settings) or self._config.model, ...)` | 3-tier; sources `spec.model_override` directly, NOT `envelope.model` |

The line-456 assignment matches the executor's pre-BON-351 contract but was
NOT updated to the empty-string sentinel. **Nothing downstream reads
`envelope.model` in pipeline-mode** — the `DispatchOptions.model` chain at
line 502–507 ignores it entirely, and the only `envelope.model` reads in the
codebase are:
- `src/bonfire/engine/executor.py:273` — sources from a freshly-built envelope
- `src/bonfire/handlers/wizard.py:325/362/413` — sources from a freshly-built
  `review_envelope`, NOT from the pipeline-supplied `envelope`

### A.3 Wizard handler sub-dispatch path

`src/bonfire/handlers/wizard.py`

| Stage | Line | Code | Contract |
|---|---|---|---|
| Build review envelope | 308–317 | `Envelope(model=stage.model_override or resolve_model_for_role(ROLE.value, self._settings) or self._config.model, ...)` | 3-tier; **resolver inside the envelope-build, not the options-build** |
| Build options | 324–332 | `DispatchOptions(model=review_envelope.model, ...)` | Single source — passes envelope.model verbatim |

This is **a third precedence shape** — the resolver lives in envelope-build
not options-build, and the call site uses the canonical `ROLE.value`
("reviewer") instead of `stage.role`. Test contract:
`tests/unit/test_wizard_handler.py:586` asserts `captured.get("role") ==
"reviewer"`.

### A.4 Cost-tracking dependency

`src/bonfire/dispatch/runner.py:109,192` — `DispatchCompleted(model=options.model, ...)`.
Cost-aggregation events flow from `DispatchOptions.model`, NOT `envelope.model`.
This means the line-456 dead-weight assignment in pipeline.py has **no
observable effect** on cost-tracking, session logs, dispatch retries, or
backend selection. It is genuinely unread.

---

## B — `BonfireSettings()` instantiation sites

Three constructors, identical pattern (`settings: BonfireSettings | None =
None`, fall back to `BonfireSettings()` when None). All three localize the
import inside `__init__` (presumably to avoid circular-import risk).

| Site | File:Line | Code |
|---|---|---|
| StageExecutor | `src/bonfire/engine/executor.py:80–92` | `settings: BonfireSettings \| None = None` then `self._settings = settings if settings is not None else _BonfireSettings()` |
| PipelineEngine | `src/bonfire/engine/pipeline.py:104–116` | identical pattern |
| WizardHandler | `src/bonfire/handlers/wizard.py:256–264` | identical pattern |

### B.1 Current contract (post-BON-351)

`BonfireSettings()` is a `pydantic_settings.BaseSettings` subclass
(`src/bonfire/models/config.py:140`) wired to:
- `toml_file = "bonfire.toml"` (from cwd, line 151)
- `env_prefix = "BONFIRE_"` (line 152)
- `env_nested_delimiter = "__"` (line 153)
- Source priority: init → env → TOML (line 176–180)

Failure modes when `settings=None` and the constructor is invoked:
1. **TOML present + malformed** — `tomllib.TOMLDecodeError` propagates from
   `TomlConfigSettingsSource.__call__`.
2. **TOML present + schema-invalid (e.g. `max_budget_usd = -1`)** — Pydantic
   `ValidationError` from `PipelineConfig._budget_non_negative`
   (`config.py:48–54`) or `_turns_positive` (`config.py:56–62`).
3. **Env vars present + bad coercion (e.g. `BONFIRE_BONFIRE__MAX_TURNS=foo`)**
   — Pydantic `ValidationError`.
4. **No TOML, no env, no kwargs** — defaults; succeeds silently.

### B.2 Pre-BON-351 contract

These three constructors did **not** touch the filesystem or env. Constructing
`StageExecutor(backend=..., bus=..., config=PipelineConfig())` was a pure
in-memory operation. Post-BON-351 it is an I/O call when `settings=None`. This
is the backward-compat surprise behind the TOML-fallback ticket.

### B.3 Test exposure

Forty-plus test invocations across `test_engine_executor.py`,
`test_engine_pipeline.py`, `test_engine_pipeline_tool_policy.py`, and
`test_wizard_handler.py` construct without `settings=` (e.g.
`test_engine_executor.py:216,222,229,...,1077`). All hit
`BonfireSettings()`. Today they pass because the worktree root has no
`bonfire.toml` and no `BONFIRE_*` env vars. **In a CI environment with a
malformed `BONFIRE_*` env var or a `bonfire.toml` accidentally on the
runner's cwd, every one of these 40+ tests would fail at construction
time** — a CI-fragility surface that did not exist pre-BON-351.

`tests/conftest.py` is empty (one-liner docstring) — no autouse `chdir(tmp_path)`
or env-scrubbing fixture exists.

`tests/unit/test_config.py` uses `monkeypatch.chdir(tmp_path)` per-test
(line 173, 181, 187, ...) — i.e. the dedicated config tests already know
they need to isolate cwd. The engine/wizard tests do not.

---

## C — Refactor-fit analysis

The four D-FTs sort into two orthogonal axes. Treating them as four
independent fixes will produce four independent diffs that step on each
other; treating them as two coordinated diffs lands all four cleanly.

### C.1 Axis 1 — model-resolution unification (BON-616 + BON-613)

Both tickets point at `pipeline.py:451`. They are **the same fix viewed from
two angles**:
- BON-613 frames it as "currently dead-weight, remove the assignment."
- BON-616 frames it as "latent coupling, future-trap, fix before something
  reads it."

A shared resolver helper satisfies both:
- The dead-weight goes away (BON-613 path-(a) — remove the assignment).
- The asymmetry goes away (BON-616 path-(c) — shared resolver helper).

The third option in BON-616 — "wire envelope.model into the resolver chain"
— is **not refactor-aligned**. The pipeline-mode envelope is already passed
to handlers; if a handler wants to read `envelope.model` it is legitimate to
do so (the wizard already reads `review_envelope.model`, just not
`envelope.model` from the pipeline). Setting `envelope.model` to a resolved
value upstream of handler dispatch in pipeline-mode would require either
threading `settings` into the envelope-build (today the pipeline does not
need it for envelope construction) or duplicating the resolver call. Both
fight the executor's existing contract (executor sets envelope.model = ""
then resolves at the options layer). Conclusion: **align pipeline to
executor, not the other way.**

### C.2 Axis 2 — settings threading (BON-614 + BON-617)

Both tickets point at the `BonfireSettings()` fallback. They are **the same
fix viewed from two angles**:
- BON-614 frames it as "wasteful, memoize or thread."
- BON-617 frames it as "raise contract is a backward-compat surprise."

Threading settings through a composition root satisfies both:
- One construction per process (BON-614 path-(a)).
- The single construction site is auditable for raise behavior (BON-617);
  per-stage code paths never re-trigger.

The "memoize at module scope" path (BON-614 path-(b)) is **anti-aligned with
testability** — module-level singletons resist `monkeypatch.chdir(tmp_path)`
and `monkeypatch.setenv(...)` because the cache is built before the
fixture runs. Composition-root threading is the test-friendly answer.

The "catch-and-substitute defaults" path (BON-617 path-(a)) is **anti-aligned
with the loud-failure principle** baked into the rest of the codebase
(`pipeline.py` PipelineEngine.run is the documented never-raise shell
(line 7: "PipelineEngine.run() NEVER raises"); but constructors are not
that shell). Silently swapping a malformed config for defaults is a
debugging trap.

### C.3 Refactor compatibility table

| Ticket | Shared-helper extraction | Composition-root threading | Conflict? |
|---|---|---|---|
| BON-613 (dead-weight) | LANDS — assignment removed when helper takes over | n/a | none |
| BON-616 (latent coupling) | LANDS — single helper means no asymmetry to mis-evolve | n/a | none |
| BON-614 (per-instance) | n/a | LANDS — single thread point | none |
| BON-617 (raise contract) | n/a | LANDS — single audit point for raise behavior | none |

The two diffs are independent — Axis 1 changes how options are built; Axis 2
changes who builds settings. They can land in either order; the
recommendation is Axis 1 first because it is the smaller, more contained
diff and exercises the helper seam.

---

## D — Recommended seam for shared model-resolver helper

### D.1 Where it lives

A new module: `src/bonfire/engine/_model_resolver.py` (leading underscore
because it is an engine-internal seam, not part of `bonfire.engine`'s
public surface).

Alternative: `src/bonfire/agent/tiers.py` already owns `resolve_model_for_role`
(`src/bonfire/agent/tiers.py:85`). The new helper layers ON TOP of that
function — it adds the override-precedence + config-fallback logic. Putting
the new helper in `agent/tiers.py` would couple two abstraction levels in one
module (the per-role tier resolver vs. the per-call-site precedence chain).
Recommend the new module.

### D.2 Proposed signature

```python
# src/bonfire/engine/_model_resolver.py

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.agent.tiers import resolve_model_for_role

if TYPE_CHECKING:
    from bonfire.models.config import BonfireSettings, PipelineConfig


def resolve_dispatch_model(
    *,
    explicit_override: str,
    role: str,
    settings: BonfireSettings,
    config: PipelineConfig,
) -> str:
    """Return the model string for a dispatch call site.

    Three-tier precedence (locked by Sage memo D2/D2(b)/D2(c)):
        1. ``explicit_override`` — per-stage / per-envelope escape hatch.
        2. ``resolve_model_for_role(role, settings)`` — role-based routing.
        3. ``config.model`` — pipeline default.

    Pure synchronous function. Never raises on string input.
    """
    return (
        explicit_override
        or resolve_model_for_role(role, settings)
        or config.model
    )
```

### D.3 Call-site collapses

After the helper lands, the three call sites collapse:

**`src/bonfire/engine/executor.py:271–276`** — replaces the inline `or` chain:
```python
options = DispatchOptions(
    model=resolve_dispatch_model(
        explicit_override=envelope.model,  # was set to stage.model_override or ""
        role=stage.role,
        settings=self._settings,
        config=self._config,
    ),
    ...
)
```

**`src/bonfire/engine/pipeline.py:502–507`** — replaces the inline `or` chain
AND **the line-456 dead-weight assignment is dropped** (envelope.model
either stays as the empty default or is set to `spec.model_override or ""`
to mirror the executor for handler-path consistency):
```python
options = DispatchOptions(
    model=resolve_dispatch_model(
        explicit_override=spec.model_override,
        role=spec.role,
        settings=self._settings,
        config=self._config,
    ),
    ...
)
```

**`src/bonfire/handlers/wizard.py:308–315`** — replaces the resolver-in-envelope-build:
```python
review_model = resolve_dispatch_model(
    explicit_override=stage.model_override or "",
    role=ROLE.value,  # canonical "reviewer", per memo D-CL.4
    settings=self._settings,
    config=self._config,
)
review_envelope = Envelope(
    task=prompt,
    agent_name="review-agent",
    model=review_model,
    metadata={"role": ROLE.value},
)
```

### D.4 What the helper deliberately does NOT do

- **Does NOT instantiate `BonfireSettings()`.** Settings flow in as a
  parameter; the helper is pure.
- **Does NOT normalize role strings.** The Sage memo D1 contract is
  call-site-vocabulary-agnostic; the inner `resolve_model_for_role`
  already normalizes (`tiers.py:99`). Re-doing it here would mask
  bugs in the call-site.
- **Does NOT cache.** Cache is a memoization concern, separable from
  precedence. If introduced, it belongs at the settings layer
  (composition-root threading), not at the per-call helper.

---

## E — In-repo idiom precedents

### E.1 Composition-root threading — the closest existing pattern

The CLI does **not** currently thread settings through (no
`BonfireSettings` reference in `src/bonfire/cli/`). The only place where
`BonfireSettings` is constructed deliberately as a single source is in
`tests/unit/test_config.py` (e.g. lines 174, 182, 188 — but each test
constructs its own).

**Implication:** This refactor is the FIRST in-repo composition-root
threading for `BonfireSettings`. There is no precedent to mirror; the
refactor sets the precedent. The closest analog is the `EventBus`
threading pattern (`src/bonfire/cli/commands/scan.py` and similar — bus
is constructed at the CLI boundary and passed in). The new pattern would
be: **CLI command constructs `BonfireSettings()` once, threads it into
`PipelineEngine` / `StageExecutor` / `WizardHandler` constructors at the
composition root.**

### E.2 Shared-helper extraction — analog patterns

- `src/bonfire/agent/tiers.py:85` — `resolve_model_for_role` itself is the
  precedent for "extract pure resolver into a stand-alone module function."
  Same pattern, one level lower. The proposed helper layers on top.
- `src/bonfire/dispatch/runner.py` — `execute_with_retry` is the
  shared-helper extraction precedent at the dispatch layer.
  `executor.py:283–290` and `pipeline.py:514–521` and
  `wizard.py:338–345` ALL call it. Three call sites, one helper. The
  proposed `resolve_dispatch_model` is the modeling-layer analog of
  `execute_with_retry` at the dispatch layer.

### E.3 Module-internal helpers — naming convention

Leading-underscore module files exist in the repo: e.g.
`src/bonfire/dispatch/_*` patterns are absent (dispatch uses
public-named submodules). However, leading-underscore CLASSES are used
inside test fixtures and in `tests/unit/test_engine_executor.py:43`
(`_ContextBuilderLike` Protocol). For a NEW module, the cleaner choice
is `src/bonfire/engine/model_resolver.py` (no leading underscore) and
EITHER export `resolve_dispatch_model` from `bonfire.engine.__init__` OR
keep it engine-internal by NOT re-exporting. Recommend NOT re-exporting
— if external code calls it, they get the resolver from
`bonfire.agent.tiers` directly.

### E.4 Sage memo discipline

`docs/audit/sage-decisions/bon-350-sage-20260427T182947Z.md` is the
canonical memo for the resolver primitive (D-CL.1: "the resolver is the
public primitive"). The new helper preserves D-CL.1 — `resolve_model_for_role`
remains the public primitive, the new helper is a thin precedence wrapper.

---

## F — Risk surface

### F.1 Tests that mock `BonfireSettings()` directly

Zero hits in `grep -rn "BonfireSettings()"` outside `test_config.py` and
`test_engine_executor.py` lines 1133, 1199. The two engine_executor
constructions are NOT mocks — they construct a real BonfireSettings to
verify resolver convergence (`tests/unit/test_engine_executor.py:1133` —
`TestVocabularyParity.test_warrior_and_implementer_resolve_same`).

**No test will break** if `BonfireSettings()` is removed from the three
constructors, IF settings are threaded through correctly.

### F.2 Tests that read `envelope.model` in pipeline-mode

`grep -rn "envelope.model" tests/unit/test_engine_pipeline.py` — zero hits
on the pipeline-supplied envelope. The pipeline tests assert
`backend.captured_options.model` (line 1283), not `envelope.model`. Removing
the line-456 assignment is **observably safe** for the existing pipeline
test suite.

### F.3 Tests that read `envelope.model` in executor-mode

`tests/unit/test_engine_executor.py:1003–1044` —
`test_executor_envelope_model_wins_over_resolver` asserts
`backend.captured_options.model == "ENVELOPE-OVERRIDE"` after setting
`stage.model_override="ENVELOPE-OVERRIDE"`. The executor's chain reads
`envelope.model`, which is built from `stage.model_override or ""` at line
196. **The proposed helper preserves this contract** (the call site
passes `envelope.model` as `explicit_override`).

### F.4 Tests that depend on the per-instance fallback

The 40+ tests instantiating `StageExecutor` / `PipelineEngine` /
`WizardHandler` without `settings=` rely on the silent default-construction
path. If a CI environment sets `BONFIRE_BONFIRE__MAX_BUDGET_USD=-1` (or
similar malformed value), every one of these tests fails at construction
time today. **The composition-root threading refactor either:**
- (a) Removes the fallback entirely → forces tests to pass `settings=` →
  big test diff but eliminates the CI fragility.
- (b) Keeps the fallback for backward-compat but adds a `tests/conftest.py`
  autouse fixture that does `monkeypatch.chdir(tmp_path)` and scrubs
  `BONFIRE_*` env vars → small test diff, eliminates fragility, preserves
  the silent-default ergonomics for external contributors who construct
  these classes without reading the docs.

Recommendation: **(b) for v0.1.0; (a) for v0.2.0** — the v0.1.0 tag is
proximate (per `docs/release-policy.md`) and a 40-test diff late in the
release-train is a worse risk than a small fixture addition.

### F.5 Backward-compat trip wires for downstream callers

External (PyPI-bound) consumers of `PipelineEngine`, `StageExecutor`, and
`WizardHandler` constructors:
- `bonfire.engine.PipelineEngine` is in the public surface (cited in
  `docs/architecture.md` as the pipeline keystone).
- `bonfire.engine.StageExecutor` is re-exported from `engine.pipeline` line
  33–35 explicitly for `patch/discover` — this means external test code may
  patch it.
- `bonfire.handlers.WizardHandler` is the published reviewer-stage handler.

The proposed change KEEPS the `settings: BonfireSettings | None = None`
parameter — it does NOT widen, narrow, or rename. External constructors
continue to work without modification. The behavioral change (when
`settings=None`) is internal-only.

### F.6 Linear-references in commit messages

Per repo CLAUDE.md "No internal-tracker references." The commit message
for this report uses no naked Linear IDs; the report itself stays
unpublished-internal-detail-free (uses `cluster-351-*` framing rather
than naked `BON-XXX` IDs in the report body where avoidable, and where
unavoidable they appear only in the mission-context section).

---

## G — Top 3 design questions for Sage

### G.1 Helper home — engine-internal or agent-tiers extension?

**Question:** Should `resolve_dispatch_model` live in
`src/bonfire/engine/model_resolver.py` (new module), or as a second
exported function from `src/bonfire/agent/tiers.py` (alongside
`resolve_model_for_role`)?

**Why it matters:** ADR-001 module-renames bind names; introducing a new
engine-internal module creates a precedent. Co-locating in `agent/tiers.py`
is one less file but couples two abstraction levels (per-role vs.
per-call-site). Decision affects the import statement at three call
sites and downstream-canon doc updates.

**My lean:** new engine module, no re-export from `bonfire.engine.__init__`.

### G.2 Settings fallback — keep or remove the `BonfireSettings()` constructor default?

**Question:** Should `StageExecutor(settings=None)` still silently construct
`BonfireSettings()` post-refactor, or should `settings` become a required
keyword-only parameter (no default)?

**Why it matters:** Public-API stability vs. CI-fragility. Required-kwarg
forces external consumers to thread settings (the right answer
architecturally) but breaks any external code that constructs without it.
v0.1.0 is proximate; the safer choice is to keep the fallback for v0.1
and tighten in v0.2. Decision drives test-fixture strategy
(F.4 above).

**My lean:** keep the fallback for v0.1.0; document the silent-default
contract; file a v0.2 ticket to make it required.

### G.3 Wizard handler — canonical-string call site or stage-role passthrough?

**Question:** The wizard handler today calls `resolve_model_for_role(ROLE.value,
self._settings)` — passing the canonical `"reviewer"` string, NOT
`stage.role` (which is whatever the workflow set, possibly `"wizard"`).
Post-refactor, should the helper be called with `stage.role` (matching
executor + pipeline) or `ROLE.value` (matching today's wizard)?

**Why it matters:** Sage memo D1 (BON-350) lines 78 and 55 lock both
vocabularies to the same tier (warrior↔implementer→FAST,
wizard↔reviewer→REASONING) — so the resolved model is identical either
way. But `tests/unit/test_wizard_handler.py:586` asserts
`captured.get("role") == "reviewer"`, which means the wizard test
ENFORCES the canonical-string call site. Pipeline + executor tests assert
the gamified passthrough. The asymmetry is deliberate but unstated in any
ADR. The shared helper inherits whichever call-site the wizard chooses.

**My lean:** keep wizard's `ROLE.value` (canonical); pipeline + executor
keep their gamified passthrough. The helper does NOT take a position —
each call site decides what to pass as `role`. Document the asymmetry
in an inline comment at the wizard call site citing memo D1 + the test
assertion.

---

## Sources (landscape research)

- [Pydantic Settings — Settings Management](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — confirms TOML-source raise contract behavior.
- [pydantic-settings issue #410 — reconsider adding Singleton option for BaseSettings](https://github.com/pydantic/pydantic-settings/issues/410) — community position: pydantic does not ship singleton, app-level dependency injection is the recommended path. Validates Axis-2 composition-root recommendation.

---

## Appendix — reading list for Sage

1. `src/bonfire/engine/pipeline.py:451–513` — the asymmetry surface.
2. `src/bonfire/engine/executor.py:191–282` — the executor's contract.
3. `src/bonfire/handlers/wizard.py:249–332` — the third precedence shape.
4. `src/bonfire/agent/tiers.py:85–112` — the underlying resolver.
5. `src/bonfire/models/config.py:140–180` — `BonfireSettings` source chain.
6. `tests/unit/test_engine_executor.py:953–1080` — executor resolver contract.
7. `tests/unit/test_engine_pipeline.py:1190–1308` — pipeline resolver contract.
8. `tests/unit/test_wizard_handler.py:540–588` — wizard resolver contract.
9. `code-synth-bon351.md:55–79` — origin of the four D-FTs.
