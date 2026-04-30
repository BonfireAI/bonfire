# Scout Report — Cluster-351 Follow-Up — Machinist Lens

**Stamp:** 2026-04-30T19:37:14Z
**Lane:** bonfire-public · `antawari/cluster-351-scout-machin`
**Base:** `origin/v0.1` @ `81c9d21`
**Lens:** Machinist (runtime + mechanical guarantees, allocation profile, error
propagation, fork-safety). Competing with Artisan (code shape) and Psychologist
(caller intent). Sage synthesizes.
**Tickets in scope:** BON-617, BON-616, BON-614, BON-613.

This report is **read-only mechanical analysis**. No source edits. No tests
written. Numbers cite either the installed pydantic-settings code, upstream
benchmarks (footnoted), or the `bonfire-public` worktree at the SHA above.

---

## TL;DR

- **Per-pipeline `BonfireSettings()` count today: exactly 2** in production
  composition (`PipelineEngine.__init__`, `WizardHandler.__init__`).
  `StageExecutor.__init__` is a third constructor but carries 0 production
  call sites today — it is test-instantiated only. The "10 stages = 10
  constructions" framing in the ticket prose is wrong; a 10-stage pipeline
  builds 1 `BonfireSettings()` at engine init plus 1 at wizard-handler init.
- **Estimated cost per `BonfireSettings()`: ~1–10 ms** (TOML parse ≈ 50–200 µs
  for Bonfire's small file size¹, env scan + pydantic validation of nested
  models dominates the rest²). Not a hot-path — not a perf disaster — but
  bigger than zero and on the synchronous startup path.
- **`envelope.model` is set, never read in pipeline-mode dispatch.** Cost
  telemetry is sourced from `options.model`, not `envelope.model`. BON-613 is
  load-bearing-zero and BON-616 is latent coupling, not active coupling.
- **TOML failure modes are pydantic-settings-native, NOT Bonfire-domain.**
  Missing file → silent `{}`; malformed TOML → `tomllib.TOMLDecodeError`
  uncaught; unreadable → `OSError` uncaught. BON-617's "raise contract"
  question is whether the constructor should wrap these in a Bonfire-shape
  exception (`BonfireConfigError` or similar) and at what point in the
  composition root the failure should surface.
- **Recommended steady-state path:** thread settings from a single composition
  root (NEW CLI factory, ≤ 2 hops) rather than module-scope memoization.
  Memoization fixes the wrong problem (Bonfire isn't construction-bound) and
  introduces fork-safety + test-isolation hazards we don't pay for today.

---

## A — `BonfireSettings()` construction cost

### What runs on each `BonfireSettings()` call

`BonfireSettings.__init__` (inheriting `BaseSettings.__init__`) runs:

1. **`settings_customise_sources`** (`models/config.py:163-180`): builds three
   source instances. The third —
   `TomlConfigSettingsSource(settings_cls)` — does the synchronous file read
   in its own `__init__`:
   - `.venv/.../pydantic_settings/sources/providers/toml.py:55-56`:
     `self.toml_data = self._read_files(self.toml_file_path)`
   - `_read_files` checks `is_file()` (`base.py:216`); if False, returns `{}`
     silently.
   - If True, `_read_file` opens the file in binary mode and calls
     `tomllib.load(toml_file)` (`toml.py:64`).

2. **Source iteration & merge.** Each source is invoked, results merged
   right-to-left (init → env → toml).

3. **Pre-validation hook.** `_migrate_schema(mode="before")`
   (`models/config.py:182-188`) walks `_LEGACY_MIGRATIONS` and rewrites the
   merged dict in place.

4. **Pydantic v2 validation.** Five nested models (`PipelineConfig`,
   `VaultConfig`, `GitConfig`, `ModelsConfig`, `dict[str, AgentConfig]`) plus
   two `field_validator`s (`_budget_non_negative`, `_turns_positive`).

### Cost references

- `tomllib.load()` parses small TOML files in **~50–200 µs** range. Cited
  benchmark: tomli parses `data.toml` 5000× in 0.838 s ≈ 167 µs/parse³. The
  Bonfire TOML schema is ~5 sections × ~5 keys = small; expect the lower end.
- Pydantic v2 BaseSettings full instantiation has been profiled at
  **~35–120 ms** in the wild for typical microservice configs⁴; the dominant
  cost is env-var scanning + validation of nested models, not the TOML parse.
- For Bonfire's ~5 nested models with primitive fields, expect
  **~1–10 ms total per `BonfireSettings()`** including env scan, TOML read,
  and validation. This is non-zero but not in the dispatch hot path.

> **Cannot run a microbenchmark here** (Bash denied in this scout shell). The
> numbers above are scoped to the cited literature; Sage should request
> Wizard run a `timeit` capture before any optimization is greenlit. See G3.

---

## B — Per-pipeline construction count: today vs after each fix path

### Today (origin/v0.1 @ 81c9d21)

Three constructors call `BonfireSettings()` when their `settings=None`:

| File | Line | Class | Production call sites |
|---|---|---|---|
| `src/bonfire/engine/pipeline.py` | 116 | `PipelineEngine.__init__` | 1 (every pipeline run) |
| `src/bonfire/handlers/wizard.py` | 264 | `WizardHandler.__init__` | 1 (every pipeline run that registers wizard handler) |
| `src/bonfire/engine/executor.py` | 92 | `StageExecutor.__init__` | 0 (test-only — `grep StageExecutor( src/` returns no hits, only `tests/`) |

**Production count today: 2 `BonfireSettings()` per pipeline run.** Not 10.
Not "every dispatch site." The "long pipeline with many dispatches"
phrasing in the BON-614 prose is wrong — `pipeline.py:_run_inner` reuses
`self._settings` for every stage; settings are not rebuilt per-stage.

CLI today (`src/bonfire/cli/commands/`) imports `BonfireSettings` exactly
zero times. There is no composition root yet that pre-builds settings — the
two production callers default-construct because no caller passes them.

### After BON-614 path (a) — thread through composition root

CLI builds `BonfireSettings()` once, passes through engine factory:

| Stage | New `BonfireSettings()` calls |
|---|---|
| CLI command | 1 |
| Engine factory | 0 (receives settings) |
| `PipelineEngine.__init__` | 0 (receives settings) |
| `WizardHandler.__init__` | 0 (receives settings) |

**Production count after: 1 per pipeline run.**

### After BON-614 path (b) — module-scope memoization

A `_get_settings()` cached function at module scope:

| Stage | First call | Subsequent calls |
|---|---|---|
| Process lifetime | 1 | 0 |

**Production count after: 1 per Python process** (across N pipelines in same
process). But this carries fork-safety + test-isolation costs (see C below).

### Why the count framing matters

A 1× → 0.5× cost reduction at startup isn't worth re-architecting around if
the absolute cost is single-digit-ms. The mechanical case for path (a) isn't
performance — it is **single source of truth for Settings** and **failure
isolation** (BON-617 surfaces the failure exactly once, in the composition
root, not at engine-init AND wizard-init).

---

## C — Memoize-vs-thread tradeoff matrix

| Dimension | (a) Thread through composition root | (b) Module-scope memoize |
|---|---|---|
| **Construction count** | 1 / pipeline | 1 / process |
| **Steady-state RAM** | 1 instance / pipeline | 1 instance / process (lives forever) |
| **Test isolation** | Trivial — pass test settings | **HAZARD** — `_cached_settings` survives between tests; needs `monkeypatch` to reset module global, or `fixture(autouse=True)` to clear |
| **Mock-friendliness** | Trivial — `kwarg=test_settings` | Awkward — must patch module global |
| **Fork-safety (multiprocessing fork)** | Safe — child re-builds via composition root | **HAZARD** — module global inherited by child; if parent had a stale TOML cache it propagates⁵ |
| **Spawn-safety** | Safe — fresh interpreter, fresh build | Safe — module re-imports |
| **Threading distance** | CLI → factory → engine + handler (≤ 2 hops) | 0 (callers reference module-scope helper) |
| **Existing CLI threading sites** | **0 today** — CLI never references `BonfireSettings` (greenfield wire-up) | 0 — no callers exist |
| **Failure isolation** | 1 site to catch `BonfireSettings()` exceptions | Implicit — first caller eats the raise; later callers get inconsistent state if memoize-on-success-only |
| **Implementation effort** | Add a settings-aware factory in `cli/`, add `settings: BonfireSettings | None = None` kwargs are already in place (Sage D-CL.1) | Add `@functools.cache` decorated factory in `models/config.py`; remove the inline `else _BonfireSettings()` from three constructors |
| **Diff size** | New file (`cli/factory.py` or similar) + 1 wire site per CLI command | ~10 LOC: one factory function + 3 constructor edits |
| **Loud-fail readiness** | Composition root surfaces config error before pipeline starts | Lazy — first `_get_settings()` call raises; if that's mid-stage, partial state hazard from BON-617 |

### Recommendation (Machinist)

**Path (a)** is the Machinist's pick by a wide margin:

1. **Test-isolation hazard is real.** Bonfire's pytest layout
   (`tests/unit/test_config.py:226-291`) already uses `monkeypatch.chdir`
   per-test to point at fresh `bonfire.toml` fixtures. Module-scope memoize
   would require an autouse fixture to clear `_cache_clear()`, an unforced
   move that fights the existing test pattern.
2. **Fork-safety is real.** The forge has *no* multi-process pipeline today,
   but pythonspeed.com's "module-level globals are preserved" guidance⁵ is
   directly applicable — the moment Bonfire grows a `concurrent.futures`
   Pool or a fork-based dispatcher, the memoize cache leaks parent state.
3. **The performance gain is rounding error.** 1× construction at single-
   digit ms vs 2× — saving 5 ms once per pipeline run (which itself takes
   minutes-to-hours in agent dispatch) is not worth the hazard surface.
4. **Threading distance is minimal.** Zero existing threading sites means
   zero refactor cost — we ADD a CLI-side factory rather than retrofit a
   sprawling layer. Under 50 LOC.

---

## D — Error-propagation paths from constructor-time validation failure

### What can raise during `BonfireSettings()`

1. **Malformed `bonfire.toml`** → `tomllib.TOMLDecodeError`. Source:
   `pydantic_settings/sources/providers/toml.py:64`. Propagates uncaught
   through `TomlConfigSettingsSource.__init__` → `BonfireSettings.__init__`.

2. **Permission/IO error reading `bonfire.toml`** → `OSError`
   (`PermissionError`, `IsADirectoryError`, etc.). Source:
   `toml.py:61` — `file_path.open(mode='rb')`. Same propagation path.

3. **Validation failure** (e.g. `max_budget_usd: -1.0` in TOML or env) →
   `pydantic.ValidationError`. Source: `models/config.py:48-62` field
   validators.

4. **Schema migration corruption** — `_migrate_legacy_keys` mutates the dict;
   non-dict `bonfire` section silently bypasses (`config.py:115-116`). No
   raise here.

5. **Missing `bonfire.toml`** → no raise (silent `{}` per
   `pydantic_settings/sources/base.py:216-217`). Defaults apply.

### Today's partial-state surface

When `BonfireSettings()` raises mid-`PipelineEngine.__init__` at line 116:

```python
def __init__(
    self,
    *,
    backend: AgentBackend,
    bus: EventBus,
    config: PipelineConfig,
    handlers: dict[str, StageHandler] | None = None,
    gate_registry: dict[str, QualityGate] | None = None,
    context_builder: ContextBuilder | None = None,
    project_root: Any | None = None,
    tool_policy: ToolPolicy | None = None,
    settings: BonfireSettings | None = None,
) -> None:
    from bonfire.models.config import BonfireSettings as _BonfireSettings
    self._backend = backend          # set
    self._bus = bus                  # set
    self._config = config            # set
    self._handlers = handlers or {}  # set
    self._gates = gate_registry or {}  # set
    self._context_builder = context_builder or ContextBuilder()  # set
    self._project_root = project_root  # set
    self._tool_policy = tool_policy  # set
    self._settings = settings if settings is not None else _BonfireSettings()  # RAISES
```

State at raise:
- Eight `self._*` slots are populated.
- The `PipelineEngine` instance is half-built — Python releases it to GC
  because the constructor raised.
- The `EventBus` passed in is **already subscribed** (callers wire
  observers before construction); the partially-built engine never emits
  `PipelineStarted`, but the bus is live. **No leak today** because
  `PipelineEngine` doesn't subscribe its own listeners — but if it ever
  does (e.g. if BON-616 path (a) caches a resolver-on-init), the
  subscription would dangle.
- `WizardHandler` may already be in `handlers` dict — its own `__init__`
  ran first and **also** built its own `BonfireSettings()`. So if the
  pipeline engine's TOML read raises, the wizard handler **already
  consumed its own raise budget** earlier in composition. Two raise sites,
  same root cause — **observers see two ValidationErrors for one bad
  TOML**.

### After BON-617 cleanup

Three plausible BON-617 paths (Sage to choose):

1. **Wrap raise in domain exception.** `BonfireSettings()` becomes a class
   factory that catches `(TOMLDecodeError, OSError, ValidationError)` and
   re-raises as `BonfireConfigError`. Pro: domain-clean. Con: pydantic's
   own machinery will keep raising native types in some paths (env-var
   parsing, init-kwarg validation); we'd have to wrap selectively.
2. **Move construction to composition root only.** Per path (a) above —
   raise once, in the CLI, where typer's exception handler can render it.
3. **Status-quo + document the contract.** `BonfireSettings()` raises
   pydantic-settings-native exceptions; callers must catch. Lowest-effort
   but inconsistent with the existing `cli/commands/persona.py:38`
   pattern that explicitly catches `(tomllib.TOMLDecodeError, OSError)`.

The Machinist preference is **path 2** — composition-root single raise site
naturally subsumes BON-614 path (a). This is the convergence argument: BON-
614 path (a) and BON-617 are the same fix viewed from two angles.

---

## E — `envelope.model` resolver dispatch perf

### Today (origin/v0.1 @ 81c9d21)

**`envelope.model` is set in two places, read in one.**

Set:
- `engine/executor.py:196`: `model=stage.model_override or ""` (post-S351
  flip — empty string sentinel).
- `engine/pipeline.py:456`: `model=spec.model_override or self._config.model`
  (the asymmetric site — BON-616 flag).

Read:
- `engine/executor.py:273`: `model=(envelope.model or
  resolve_model_for_role(stage.role, self._settings) or self._config.model)`
  — the precedence chain head.

Crucially, `engine/pipeline.py:498-513` reconstructs `options.model`
**independently** of `envelope.model`:

```python
options = DispatchOptions(
    model=(
        spec.model_override
        or resolve_model_for_role(spec.role, self._settings)
        or self._config.model
    ),
    ...
)
```

Then dispatches via `runner.execute_with_retry`. The runner emits
`DispatchStarted`/`DispatchCompleted` with `model=options.model`
(`runner.py:109,192`). Backends read `options.model`
(`sdk_backend.py:110`, `pydantic_ai_backend.py:57`). **No code path reads
`envelope.model` after `pipeline.py:451`.**

That is BON-613 (dead-weight) and BON-616 (asymmetry — the executor uses
envelope.model as the precedence-chain head; the pipeline mutates it but
ignores its own mutation).

### Resolver dispatch perf (today)

- `resolve_model_for_role` is **pure** — no I/O, no cache, no async
  (`agent/tiers.py:85-112`). Body: 1 `.strip().lower()`, 1 `try/except` for
  `AgentRole(...)`, 2 dict lookups (`MappingProxyType`), 1 `getattr`.
  Estimated cost: **~1–5 µs** per call.
- Per stage: 1 resolver call. 10-stage pipeline: 10 calls. Total: **~10–50
  µs.** Not a hot path. The cost is irrelevant.

### After BON-616 path (a) — wire envelope.model into pipeline-mode

If we made the pipeline mirror the executor (set `envelope.model` =
resolver output, then read it back at `options.model`):

```python
envelope = Envelope(
    ...,
    model=spec.model_override or resolve_model_for_role(spec.role, self._settings) or "",
)
options = DispatchOptions(
    model=envelope.model or self._config.model,
    ...
)
```

Per-stage cost is identical (one resolver call); the win is
**single-source-of-truth for what model the dispatch runs**. The cost
ledger's `DispatchRecord.model` is already sourced from `options.model` —
no telemetry change.

If instead BON-616 path (b) just *deletes* the envelope.model assignment at
`pipeline.py:456` (kill the dead write entirely), perf is unchanged — and
the latent coupling vanishes. **Path (b) is mechanically equivalent and
diff-tighter.** Sage should consider it.

---

## F — Steady-state allocation profile after all 4 fixes (recommended path)

Recommended path: **path (a) for BON-614 + BON-617** (composition-root
single source) and **path (b) for BON-613 + BON-616** (delete dead write).

### Per-pipeline allocation count (10-stage pipeline)

| Object | Count | Lifetime | Notes |
|---|---|---|---|
| `BonfireSettings` | **1** | pipeline run | constructed in CLI factory; passed to engine + wizard |
| `PipelineEngine` | 1 | pipeline run | |
| `WizardHandler` | 1 | pipeline run | (when wizard stage is registered) |
| `Envelope` (initial) | 1 | pipeline run | |
| `Envelope` (per-stage, post-iteration) | 10–30 | pipeline run | depends on iteration count and bounce; immutable copies via `with_*` |
| `Envelope.model` mutations | **0** | n/a | post-fix, no in-place model mutation; precedence chain resolves to `options.model` directly. Envelope's `model: str` field is set once at init or carries `""` |
| `DispatchOptions` | 10 | per-stage | one per backend dispatch; pure dataclass-like |
| `DispatchResult` | 10 | per-stage | runner output |
| `DispatchStarted` / `DispatchCompleted` events | 20 | per-stage | observer-fanned |
| `DispatchRecord` (cost ledger) | 10 | persistent | sourced from `event.model` (= `options.model`); model field non-empty post-fix |
| `ModelCost` (analyzer output) | k unique models | on-demand | from `model_costs()` aggregator |
| `resolve_model_for_role` calls | 10 | per-stage | pure, ~1–5 µs each |
| `BonfireSettings()` raise sites | **1** | pipeline run | CLI factory wraps in `BonfireConfigError` (or surfaces directly to typer) |
| TOML file reads | **1** | pipeline run | once at CLI startup; pipeline reuses |
| pydantic env scans | **1** | pipeline run | same |

### Net deltas vs today

- BonfireSettings: 2 → 1 (−1)
- TOML reads: 2 → 1 (−1)
- `envelope.model` mutation in pipeline-mode: 1/stage → 0/stage (−10
  set-write operations; reads were already 0/stage)
- Construction-time raise sites: 2 → 1 (−1; cleaner failure mode)
- New CLI files: ~1 (composition root factory)
- Net LOC delta: probably +30 / −5 (small)

### What the ledger looks like (cost telemetry)

`DispatchRecord.model` is now reliably non-empty for all stages because
`options.model` always resolves through `(spec.model_override OR resolver
OR config.model)` — the empty-string bucket in `model_costs()` shrinks
toward zero for new runs (legacy records still group under `""`, which
`analyzer.py:142-145` documents as intentional).

---

## G — Top 3 design questions for Sage about runtime/mechanical guarantees

### G1 — Composition root or memoization for BON-614?

The Machinist lens says path (a) — single composition-root `BonfireSettings`
threaded through CLI → engine factory → handler factory. But this presumes
the CLI gets a `bonfire run` command soon (today: `cli/commands/` has
`init`, `cost`, `handoff`, `persona`, `resume`, `scan`, `status` — no
`run`). **Q: Is the v0.1 plan to land a `bonfire run` command before BON-
614 ships, or do we need the factory in `engine/__init__.py` instead?**
This determines whether path (a) is a pure-add or a chicken-and-egg.

### G2 — BON-617 raise-contract scope: domain wrap, surface-once, or
status-quo-document?

The Machinist preference is "surface once at composition root" because it
aligns with BON-614 path (a) — single raise site. But that leaves the
question: **what about callers who construct `BonfireSettings()` outside
the CLI** (e.g. tests, programmatic SDK usage, external Apache-2.0
contributors writing their own pipelines)? **Q: Is `BonfireSettings()` a
public API (raises pydantic-native types — caller's responsibility), or
private (raises domain `BonfireConfigError` — Bonfire's responsibility)?**
ADR-001 binds the naming; this is a contract question that needs an ADR
or Sage decision.

### G3 — BON-616 path (a) wire-through vs path (b) delete-dead-write?

The Machinist sees no perf difference between the two paths (resolver is
~1–5 µs). The question is **architectural intent**: does
`Envelope.model` represent "the model this envelope was dispatched with"
(in which case wire it through — path (a) — single source of truth)?
Or "the model the caller suggested before resolution" (in which case
delete the redundant write — path (b))? **Q: What does `Envelope.model`
mean at the contract level?** The current code is ambiguous —
`executor.py:196` writes `""` (sentinel); `pipeline.py:456` writes
resolved model. They cannot both be right. Sage to call it.

---

## Sources

¹ [Comparison of Python TOML parser libraries — DEV Community](https://dev.to/pypyr/comparison-of-python-toml-parser-libraries-595e) — tomli benchmarks: 5000 parses of `data.toml` in 0.838 s ≈ 167 µs/parse for typical TOML.

² [Settings Management — Pydantic Validation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — pydantic-settings docs; nested validation cost dominates env scan + TOML read.

³ [tomllib — Parse TOML files](https://docs.python.org/3/library/tomllib.html) — stdlib tomllib (Python 3.11+); pure Python implementation.

⁴ [Pydantic BaseSettings vs. Dynaconf — Leapcell](https://leapcell.io/blog/pydantic-basesettings-vs-dynaconf-a-modern-guide-to-application-configuration) — quoted: "startup time improvements from 120ms to 35ms (70% faster)" for typical microservice configs.

⁵ [Why your multiprocessing Pool is stuck — Python Speed](https://pythonspeed.com/articles/python-multiprocessing/) — module-level globals are inherited by fork; cached state in parent contaminates children.

⁶ [pydantic-settings GitHub — toml.py](https://github.com/pydantic/pydantic-settings/blob/main/pydantic_settings/sources/providers/toml.py) — source confirmed in installed venv at `.venv/lib/python3.12/site-packages/pydantic_settings/sources/providers/toml.py`.

⁷ [pydantic-settings GitHub — base.py](https://github.com/pydantic/pydantic-settings/blob/main/pydantic_settings/sources/base.py) — `ConfigFileSourceMixin._read_files` line 216: missing file silently returns `{}`.

---

**End of scout report.** No source-code edits. No test writes. Mechanical
analysis only.
