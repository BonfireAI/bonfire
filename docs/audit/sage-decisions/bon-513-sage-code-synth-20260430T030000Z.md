# BON-513 — Code-Synth Decision Log (Sage)

**Stamp:** 2026-04-30T03:00:00Z
**Ticket:** BON-513 — Pipeline: Warrior→Sage auto-bounce stage for under-specified xfail markers
**Pattern:** BON-348 / BON-341 code-synth precedent (winner-take-most + cherry-picked loser improvements + deferred-deviation D-FTs)

**Source artifacts:**
- Sage memo (contract-lock slice): `docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md` (§D-CL.1–§D-CL.8)
- Sibling slices §A+§B (ratification) and §D1–§D10 (module shape, classifier, pipeline)

**Warrior A (CONSERVATIVE):** branch `antawari/bon-513-warrior-a` @ `85ec717` — diff stat: ~1396 lines, 7 files. Mirror Wizard/Bard/Herald shape; minimal-diff; `_CorrectionDispatchOptions` shim wrapping Pydantic `DispatchOptions`.
**Warrior B (INNOVATION):** branch `antawari/bon-513-warrior-b` @ `aa3c062` — diff stat: ~1448 lines, 7 files. Type-driven contracts: `SageCorrectionDispatchOptions` frozen dataclass + `_CorrectionCycleOutcome` frozen dataclass + dict-dispatch verdict routing + `Literal` `parse_source` field + StrEnum + `frozenset[str]` everywhere.

**Both at HEAD:** 114/114 contract tests passing, 3790 full suite, no regressions. Both branched from `antawari/bon-513-contract-lock` @ `e75ee11`.

**Author:** Sage (code-synth, dual-Warrior reconciliation)

---

## §D-CS.1 — Verdict

**Winner: Warrior B (INNOVATION).**

Closest peer is BON-519's `MergePreflightHandler` — that handler already ships StrEnum verdicts, frozen dataclasses, and structured-outcome value types. Warrior B mirrors that shape verbatim; Warrior A introduces a `_CorrectionDispatchOptions` shim (`__slots__`-based class wrapping a Pydantic model so two attribute spellings — `tools` AND `allowed_tools` — both satisfy mock introspection) that the codebase's existing handler precedent does not have. Per `feedback_conservative_wins_execution.md` conservative wins on equal footing — but Warrior B's shape is the in-repo precedent for this class of handler, so "conservative" here is a misnomer; B is the codebase-fit choice.

---

## §D-CS.2 — Side-by-side comparison

| Dimension | Warrior A | Warrior B |
|---|---|---|
| **Handler shape** | Long flat `handle()` body with verdict-string `if/elif` chain spanning ~70 lines (`sage_correction_bounce.py:368–462`); private helpers are module-level `_build_*` functions. | `handle()` delegates to `_route_verdict()` (`sage_correction_bounce.py:605–691`); private helpers are instance methods on the handler. Cleaner inheritance/test path. |
| **Classifier shape** | StrEnum `ClassifierVerdict` + frozen `BounceClassification` + `DeferRecord` (with `parse_source: str` plain string field). 5-step decision tree with branching on `parse_source == "absent"` per memo content. | StrEnum `ClassifierVerdict` + frozen `BounceClassification` + `DeferRecord` with `parse_source: Literal["front_matter", "prose", "absent"]` (compile-time validated). 7-step decision tree, identical algorithm; carries `parse_source` THROUGH the result so callers can distinguish empty-memo vs malformed-memo without re-parsing. |
| **Gate shape** | `if/elif` chain, 7 branches, ~60 lines (`gates.py:116–190`). Reads BOTH metadata keys for ambiguous-detection (defensive). | Dict-table dispatch via module-level `_PASSING_WARNING_VERDICTS: frozenset[str]` lookup, 4 branches, ~50 lines (`gates.py:113–163`). Reads BOTH metadata keys for ambiguous-detection (same defensiveness, half the code). |
| **Dispatch options** | `_CorrectionDispatchOptions` shim — a `__slots__` class that holds `tools: frozenset[str]` AND `allowed_tools: frozenset[str]` (same value, two spellings) plus an `inner: DispatchOptions` Pydantic instance (`sage_correction_bounce.py:734–756`). The shim exists ONLY so `hasattr(arg, "allowed_tools")` AND `hasattr(arg, "tools")` both return True for mock introspection. | `SageCorrectionDispatchOptions` — `@dataclass(frozen=True)` with `allowed_tools: frozenset[str] = field(default_factory=lambda: _SAGE_CORRECTION_ALLOWED_TOOLS)`, `role`, `permission_mode`, `correction_mode`, `missing_deps` (`sage_correction_bounce.py:322–344`). One canonical shape; tests assert against that one shape. |
| **Verdict routing** | String comparison + `frozenset` membership (`_GREEN_VERDICTS`, `_ESCALATE_VERDICTS`); ~6 if-branches + 1 fail-safe FAILED. | Sentinel string constants + `_KNOWN_VERDICTS: frozenset[str]` membership check FIRST (fail-safe FAILED for unknowns BEFORE routing); then 4-branch routing. Wrong states unrepresentable: an unknown verdict goes to FAILED before the dispatch decision is even considered. |
| **Cycle-outcome surface** | Inlined: every cycle code-path inlines a full `envelope.model_copy(update={...})` block (4 separate ones), each with its own `metadata` dict construction. | `_CorrectionCycleOutcome` frozen dataclass holds `(status, correction_verdict, cycles, escalated, error_type, error_message, correction_branch)`; `_run_correction_cycle()` returns it; `_build_envelope_from_cycle_outcome()` translates once. Easy to test in isolation. |
| **Decision-log parser** | Hybrid front-matter + prose. Returns `ParsedDecisionLog(deps, parse_source, records)` with `records: tuple[DeferRecord, ...]`. Carries the per-bullet records too (provenance metadata). | Hybrid front-matter + prose. Returns `ParsedDecisionLog(deps, parse_source)` only. Lighter surface; all production callers only need the deps set. |
| **§D-CL.7 mitigations** | #5 file-write atomicity (handler delegates to `Edit` tool; ✓), #6 dict-ordering (frozenset returns; ✓), #9 subprocess injection (no `shell=True`; ✓ — but no `start_new_session` consideration), #11 path-guard (no path serialization; ✓). | #1 async cancellation propagation (explicit `except asyncio.CancelledError: raise` in `handle()` AND `_run_correction_cycle()` AND `_call_backend_execute()`; mitigates `feedback_async_cancellation.md`-class drift), #5 ✓, #6 ✓, #7 cherry-pick idempotency (`_safe_cherry_pick_abort()` helper; reset-on-failure; ✓), #9 ✓ (tuple args + no `shell=True`), #11 ✓, #12 type-driven contracts via `Literal` `parse_source` (Sage §D-CL.7 #6 enforced at type level). |
| **Deferred deviations** | (1) `HANDLER_ROLE_MAP` not extended (4-entry lock), (2) `bonfire.engine.__all__` not widened (14-symbol lock), (3) `workflow/standard.py` untouched (8-stage lock). | (1) HANDLER_ROLE_MAP not extended, (2) `bonfire.engine.__all__` not widened, (3) `workflow/standard.py` docstring-only update (one paragraph noting the stage exists; no functional change to the 8-stage pipeline; honors the lock). |

---

## §D-CS.3 — Why winner wins

1. **Type-driven contracts make wrong states unrepresentable.** Warrior B's `Literal["front_matter", "prose", "absent"]` field on `ParsedDecisionLog` (`classifier.py:1202`, `1215`) is checked by mypy/Pyright at edit-time; Warrior A's `parse_source: str = "absent"` (`classifier.py:1078`) accepts any string and silently drifts on a future typo.

2. **Codebase precedent fit.** `MergePreflightHandler` (the BON-519 closest peer at `src/bonfire/handlers/merge_preflight.py`) ships `PreflightVerdict(StrEnum)` + `@dataclass(frozen=True) FailingTest` + `Literal` types in exactly the shape Warrior B mirrors. Warrior B's `SageCorrectionDispatchOptions` (`sage_correction_bounce.py:322–344`) and `_CorrectionCycleOutcome` (`sage_correction_bounce.py:347–366`) are the same idiom one stage over. Warrior A's `_CorrectionDispatchOptions` shim is novel — no existing handler ships a "two-attribute-spelling" wrapper. Per `feedback_review_before_building.md` codebase-fit beats minimal-diff for keystone handlers.

3. **Async cancellation propagation (§D-CL.7 #1).** Warrior B explicitly re-raises `asyncio.CancelledError` at THREE call sites (`sage_correction_bounce.py:521`, `733`, `754`) so the parent pipeline's cancellation reaches the supervising task. Warrior A has a single broad `except Exception` at the top of `handle()` (`sage_correction_bounce.py:454`) that silently swallows `CancelledError` (Python 3.11+ `CancelledError` is a `BaseException` so it would actually escape, BUT the inner cycle dispatch at line 626 catches `Exception` — same drift). The §D-CL.7 contract requires explicit cancellation handling; B does it, A does not.

4. **Cherry-pick idempotency (§D-CL.7 #7).** Warrior B ships `_safe_cherry_pick_abort()` helper (`sage_correction_bounce.py:890–908`) that calls `git_workflow.cherry_pick_abort()` BEFORE returning FAILED on a cherry-pick exception (mitigates the corrupt-MERGING-state drift the §D-CL.7 #7 contract names). Warrior A skips the abort path entirely (`sage_correction_bounce.py:646–663` — sets metadata + returns FAILED, but no abort call).

5. **Verdict routing exhaustiveness via dict-dispatch.** Warrior B's `_route_verdict()` checks `verdict not in _KNOWN_VERDICTS` FIRST (`sage_correction_bounce.py:620`) — unknowns FAIL before any routing; the four branches that follow handle the 4 known verdicts symmetrically. Warrior A interleaves the unknown-verdict fail-safe at the end of the routing chain (`sage_correction_bounce.py:436–452`) — the routing logic and the safety check are tangled. B's structure makes the §D-CL.6 #4 contract (verdict routing exhaustiveness) eyeball-verifiable.

6. **No two-spelling shim.** Warrior B's `SageCorrectionDispatchOptions.allowed_tools: frozenset[str]` is the single canonical name. Tests that check `hasattr(arg, "allowed_tools")` pass; tests that check `arg.allowed_tools == frozenset({"Read", "Edit"})` pass. Warrior A introduces a 3-attribute shim (`tools`, `allowed_tools`, `inner`) at `sage_correction_bounce.py:734–756` whose stated purpose is mock-introspection compatibility. That's a smell — the contract should pin ONE name; mock-shape contortions belong in test fixtures, not production. Future maintenance reads B's class as "the dispatch options" and A's class as "mystery wrapper, why are there two spellings?"

7. **Structured `_CorrectionCycleOutcome`.** Warrior B's frozen dataclass (`sage_correction_bounce.py:347–366`) carries `(status, correction_verdict, cycles, escalated, error_type, error_message, correction_branch)` as one value; the cycle method returns one; the envelope builder translates once at `_build_envelope_from_cycle_outcome()`. Warrior A inlines four separate `envelope.model_copy(update={...})` calls inside `_run_correction_cycle()` (lines 649, 674, 692, 710), each ~20 lines, each with its own metadata dict construction. B is testable in isolation (mock the cycle, assert on the outcome dataclass); A is testable only end-to-end through the envelope shape.

8. **Compile-time vs runtime dep extraction.** Warrior B's `_extract_cited_deps()` is a module-level pure function with a precompiled `_XFAIL_REASON_DEP_RE` (`classifier.py:1270`); the regex is named, documented (`# Cited-dep extractor for xfail reasons. Pattern: "deferred to BON-X"`), and called from one place. Warrior A inlines `import re as _re` INSIDE `_extract_commit_sha()` at `sage_correction_bounce.py:862` — runtime import inside a function is a code smell on a hot-ish path; the regex is constructed every call.

---

## §D-CS.4 — What loser does better (cherry-pick into winner at PR time)

1. **Warrior A's `_GREEN_VERDICTS` set spelling alignment.** A treats `"green"` AND `"not_needed_warrior_green"` as equivalent green-skip signals (`sage_correction_bounce.py:317–319`); B handles them as distinct branches. The unification A applies makes the routing simpler — Bard could cherry-pick A's `_GREEN_VERDICTS: frozenset[str] = frozenset({"green", "not_needed_warrior_green"})` constant and wire B's `_route_verdict` to use it. Net delta: ~3 lines fewer in B's `_route_verdict`.

2. **Warrior A's `_extract_commit_sha` regex fallback.** A's helper (`sage_correction_bounce.py:845–867`) tries `dispatch_result.metadata['correction_commit_sha']` FIRST, then falls back to a `sha=<hex>` regex against the result text. B's helper (`sage_correction_bounce.py:858–872`) only checks the dict path. A's fallback is genuinely useful when the backend returns a free-text result without metadata. Cherry-pick A's two-tier approach into B at ship time.

3. **Warrior A's `DeferRecord.records: tuple[DeferRecord, ...]` field on ParsedDecisionLog.** A's parser carries per-bullet provenance records (line numbers, parse source) on `ParsedDecisionLog` (`classifier.py:1098`). B's parser only carries `deps + parse_source`. The provenance records are not used today but are useful for future error messages ("Sage memo line 27: dep BON-X not in failing-test xfail reasons"). Cherry-pick A's `records` field into B's `ParsedDecisionLog` at ship time — additive change, no behavior delta.

---

## §D-CS.5 — Deferred deviations (file as D-FTs in Linear before merge)

Per `feedback_tickets_before_action.md` and Sage memo §D-CL.8, file these BEFORE the PR merges:

| ID candidate | Title | Rationale |
|---|---|---|
| **BON-513-FT-13** | Extend `HANDLER_ROLE_MAP` to include sage_correction_bounce + lift the 4-entry test lock | `tests/unit/test_handlers_package.py::test_handler_role_map_has_four_entries` locks at 4 entries; `MergePreflightHandler` precedent is to bypass the gamified-display map. Decision deferred: today the verifier and synthesizer-correction handlers both bypass; future ticket either widens the lock to N or formalises a separate "deterministic handlers" registry. Both Warriors mirrored MergePreflight precedent. |
| **BON-513-FT-14** | Widen `bonfire.engine.__all__` from 14 to 15 (or N) symbols to surface SageCorrectionResolvedGate | `tests/unit/test_engine_init.py::test_all_list_contains_exactly_14_symbols` locks at 14; both Warriors leave the gate reachable via `hasattr(bonfire.engine, "SageCorrectionResolvedGate")` and via direct submodule import (`from bonfire.engine.gates import SageCorrectionResolvedGate`) but NOT via `from bonfire.engine import *`. Promote to `__all__` after lock-widening ticket. |
| **BON-513-FT-15** | Wire `sage_correction_bounce` into `workflow.standard.standard_build` (composition root) | `tests/unit/test_workflow.py::TestStandardBuild` locks the 8-stage pipeline shape; Sage memo §D-CL.4 line 312 EXPLICITLY defers composition-root wiring as a D-FT when the composition root has not landed. It has not. Warrior B adds a docstring note pointing at this gap; Warrior A leaves the file untouched. The wiring (insert `sage_correction_bounce` between `warrior` and `bard`; rewire `bard.depends_on` to include the new stage; update the test fixtures) is its own ticket — will collide with BON-519's parallel composition-root work otherwise. |

All three are **documented deferrals**, not bugs. Ship-as-is matches the Sage-memo-prescribed path.

---

## §D-CS.6 — Bard ship instructions

**Branch to ship from:** `antawari/bon-513-warrior-b` @ `aa3c062`

**Files included in PR (7 modified/created):**

```
src/bonfire/engine/__init__.py           (modified -- import only, NOT in __all__)
src/bonfire/engine/gates.py              (modified -- add SageCorrectionResolvedGate)
src/bonfire/handlers/__init__.py         (modified -- export SageCorrectionBounceHandler)
src/bonfire/handlers/sage_correction_bounce.py   (new)
src/bonfire/models/envelope.py           (modified -- 6 new META_* constants)
src/bonfire/verify/__init__.py           (new -- package re-exports)
src/bonfire/verify/classifier.py         (new)
src/bonfire/workflow/standard.py         (modified -- docstring note only; 8-stage lock honored)
```

**At PR-time cherry-pick from Warrior A (per §D-CS.4):**
1. `_GREEN_VERDICTS: frozenset[str] = frozenset({"green", "not_needed_warrior_green"})` constant — unify the two green-skip signals so B's `_route_verdict` routes them identically.
2. Two-tier `_extract_commit_sha` helper — add the `sha=<hex>` regex fallback against `dispatch_result.result` for backends that return free-text.
3. `ParsedDecisionLog.records: tuple[DeferRecord, ...]` field — additive, no behavior delta, future-proofs error messages with line-number provenance.

These three are explicit cherry-picks Bard inlines into the PR diff during ship; they are NOT in B's tip but should be in the merged PR.

**Commit-message hint:**

```
BON-513: SageCorrectionBounce stage -- auto-bounce under-marked xfail to Sage

Adds SageCorrectionBounceHandler + bonfire.verify.classifier package.
Type-driven contracts: ClassifierVerdict StrEnum, frozen BounceClassification
+ ParsedDecisionLog with Literal parse_source, frozen
SageCorrectionDispatchOptions (allowed_tools: frozenset[str]).
Mirrors MergePreflightHandler shape; explicit asyncio.CancelledError
propagation; cherry-pick idempotency via _safe_cherry_pick_abort.

3 deferred deviations filed as D-FTs (BON-513-FT-13/14/15):
HANDLER_ROLE_MAP, bonfire.engine.__all__, standard_build composition
root all locked by pre-existing tests; this commit honors all locks.

114/114 contract tests + 3790 full suite green; no regressions.
```

**Wizard SMEAC anchor:** Wizard reviews the PR diff (NOT branch files) AFTER PR creation, BEFORE merge — verify the 10 §D-CL.6 categories from the contract-lock memo, with particular attention to category #5 (tool-restriction discipline: `allowed_tools=frozenset({"Read", "Edit"})` literal) and category #6 (cleanup discipline: `_safe_cherry_pick_abort` exists).

---

**End of code-synth memo.**
