# Prospective Code Review — BON-331 Knight RED Suite

- **Ticket:** BON-331 (bonfire-public v0.1, Wave 2.1 — models transfer)
- **Phase:** prospective-knight (pre-Warrior dispatch)
- **Reviewed SHA:** `db1145b` on `antawari/bon-331-knight`
- **Worktree:** `/home/ishtar/Projects/bonfire-public/.claude/worktrees/bon-331-knight`
- **Reviewer:** superpowers:code-reviewer (Opus 4.7, dual-lens engineering-discipline)
- **Timestamp:** 2026-04-17T23:05:43Z

## Verdict Banner

**APPROVE WITH SUGGESTIONS — MERGE (proceed to Warrior dispatch).**

The 242-test RED suite is sound, contract-faithful to the private V1 models, and properly RED for the right reason. Minor amendments recommended — all as SMEAC additions for the Warrior, not changes to the test files themselves.

## RED Invariant Evidence

```
============================= 242 errors in 3.42s =============================
Failed: bonfire.models.envelope not importable: No module named 'bonfire.models.envelope'
Failed: bonfire.models.events not importable: No module named 'bonfire.models.events'
Failed: bonfire.models.config not importable: No module named 'bonfire.models.config'
Failed: bonfire.models.plan not importable: No module named 'bonfire.models.plan'
```

Every one of the 242 tests fails at the `_require_module` autouse fixture with a
`pytest.fail()` call — never at an assertion in the test body. Collection
succeeds because each file wraps the target import in `try/except ImportError`
and binds all names to `None`. This is RED-by-design: failure mode is
unambiguously "implementation missing," never "environment drift" or
"contract wrong in the test."

## Lens-by-Lens Assessment

### 1. Test quality (RED for the right reason)
Every test will flip GREEN only when a real implementation of the named
symbol exists and behaves as asserted. No test can false-pass on an
environment artifact or an accidental symbol collision, because each file
imports through a `try/except` shim and the autouse fixture short-circuits
any test body execution while `_IMPORT_ERROR is not None`. **PASS.**

### 2. Per-file import shim soundness
The pattern is identical across all four files: module-level `try/except
ImportError as _exc`, all target symbols bound to `None` on failure,
`_IMPORT_ERROR` module-level variable, function-scope autouse fixture
`_require_module` that calls `pytest.fail(...)`. The fixture is re-evaluated
per test (function scope is default), so every test gets the failure. The
`# type: ignore[assignment,misc]` comments on the `None` bindings prevent
mypy noise. No collection-time traps: `pytest.fail` is inside a fixture,
not at module top level. **PASS.**

### 3. Contract fidelity to private V1
Cross-checked against `/home/ishtar/Projects/bonfire/src/bonfire/models/`:
- **Envelope:** 13 fields match; frozen `model_config`; `cost_usd >= 0`
  validator; `with_status`/`with_result`/`with_error`/`with_metadata`/`chain`
  semantics match; `__repr__` format matches; META_* constants match.
- **Events:** 28 concrete events, 9 category prefixes — matches the
  `EVENT_REGISTRY` in private V1 exactly. Knight's adaptation of the
  private docstring's stale "27" to the actual count of 28 is correct
  (adaptation #3 per the prompt).
- **Config:** `workflow` field properly dropped; top-level shape
  `{config_version, bonfire, memory, git, agents}` matches the adapted
  v0.1 contract; legacy migration `budget_usd -> max_budget_usd` matches.
- **Plan:** `StageSpec` 11 fields match; `WorkflowPlan` DAG invariants
  all covered (empty/duplicate/dangling/self-bounce/cycle); `AliasChoices`
  for `agent` and `model` on StageSpec; `task` alias on WorkflowPlan.name.
  **PASS.**

### 4. Over-specification risk
The repr assertions lock in the private V1 exact format (`status.name`
uppercase; `cost=$0.1234` with four-decimal formatting). For a
transfer-target ticket this is correct — the whole point is a faithful
copy of behavior, so reproducing the exact observable strings is a
feature, not over-specification. Event tests avoid locking internal
attribute order, and plan tests accept either Unicode arrow or `->`
for cycle paths. **PASS with note.**

### 5. Pydantic v2 idiom correctness
Tests exercise `model_fields.keys()` for field-set assertions (correct
v2 API), `model_validate(...)` for dict construction with mode="before"
validators, `AliasChoices` via both canonical and alias kwargs, and
`TypeAdapter` dump/validate JSON round-trips on a discriminated union.
`BonfireEventUnion.__args__[0].__args__` introspection is verified by a
local Python smoke test. **PASS.**

### 6. Warrior-implementability
A conservative Warrior can make all 242 pass by copying the four private
V1 model files and applying the three documented adaptations
(drop `workflow`, scrub `BON-`/`beta#` refs in docstrings, keep event
count at 28). Two implementation details the Warrior must remember —
`populate_by_name=True` paired with `AliasChoices` (F-002) and pruning
the `_DEFAULTS` dict alongside the field removal (F-005) — should be
called out in the Warrior SMEAC so there is no archaeology burden.
**PASS with SMEAC amendments.**

### 7. Brittleness
One "cost=" substring match that is safe today but theoretically brittle
to future task-string contents (F-004) — accepted as-is. All category
assertions use sets, not ordered lists. JSON round-trip tests assert
field equality, not byte equality. **PASS.**

### 8. Hygiene
One mutable module-level dict `SESSION` (F-007) — used only via
non-mutating spread, safe in practice. Imports are all used. No
unused fixtures, no leaky state between tests (every construct uses
monkeypatch.chdir to `tmp_path` for config tests). **PASS.**

## Findings

| ID | Severity | Lens | File:line | Summary |
|----|----------|------|-----------|---------|
| F-001 | MINOR | Over-specification | test_envelope.py:505 | `PENDING` (uppercase `.name`) locks in private V1 exact repr — acceptable for a transfer-target ticket |
| F-002 | MINOR | Pydantic v2 idiom | test_plan.py:159 | `agent=` alias requires `populate_by_name=True` + `AliasChoices` — cite in SMEAC |
| F-003 | MINOR | Warrior-implementability | test_plan.py:430 | Arrow OR `->` fallback is correctly permissive |
| F-004 | MINOR | Brittleness | test_envelope.py:530 | `"cost="` substring check is safe given task=`"x"` |
| F-005 | MINOR | Warrior-implementability | test_config.py:333 | Warrior must remove `workflow` from `_DEFAULTS` dict too — cite in SMEAC |
| F-006 | MINOR | Contract fidelity | test_config.py:176 | `config_version >= 1` is conservatively permissive — good hygiene |
| F-007 | NIT | Hygiene | test_events.py:81 | Module-level mutable `SESSION` dict — safe in practice |

Zero CRITICAL. Zero MAJOR.

## Final Recommendation

**MERGE (proceed to Warrior).**

The RED suite is sound, RED for the right reason, and faithful to the private
V1 contract with all three adaptations correctly applied. No test file needs
amendment. Proceed to Warrior dispatch with the following SMEAC amendments:

1. **StageSpec / WorkflowPlan:** The Warrior MUST set `model_config =
   ConfigDict(frozen=True, populate_by_name=True)` on both models so that
   `AliasChoices("agent", "agent_name")` accepts either kwarg form. Missing
   `populate_by_name=True` breaks `test_agent_name_accepted` and
   `test_task_alias_accepted` asymmetrically.

2. **BonfireSettings `_DEFAULTS`:** The Warrior MUST remove `"workflow":
   ProjectWorkflowConfig()` from the `_DEFAULTS` module-level dict in
   addition to removing the `workflow` field from the model. Test
   `test_describe_does_not_have_workflow_section` asserts the describe
   output has no workflow key; without the dict edit, describe would
   iterate a non-existent attribute and crash before the assertion runs.

3. **Imports:** The Warrior MUST NOT import `ProjectWorkflowConfig` at all
   — `bonfire.project.config` does not exist in public v0.1 and any such
   import will fail at collection.

No other changes required. The Knight's pattern (per-file import shim with
autouse `pytest.fail` fixture) is the correct transfer-target RED idiom
and should be preserved going forward on similar Wave 2 work.
