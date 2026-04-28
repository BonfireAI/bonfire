# BON-351 — Code-synth decision log

**Stamp:** 2026-04-28T01:55:00Z
**Stage:** Code-synth (post dual-Warrior; pre Bard PR + Wizard review)
**Wizard:** Ishtar / Passelewe — performed in main session (no separate Sage agent dispatched)
**Inputs:**
- Sage memo at `bonfire-public/.claude/worktrees/bon-351-sage/sage-memo-bon351.md` (commit `df72ea4`, branch `antawari/bon-351-sage`)
- Knight A RED at `antawari/bon-351-knight-a` (`24c18c9`, 24 tests / 8 files)
- Knight B RED at `antawari/bon-351-knight-b` (`0088b9e`, 8 tests / 3 files)
- Contract-lock at `antawari/bon-351-contract-lock` (`0e02b34`, 32 RED tests merged)
- Warrior A at `antawari/bon-351-warrior-a` (`cf673fc`, +80/-7 across 8 files)
- Warrior B at `antawari/bon-351-warrior-b` (`8b27cfc`, +99/-4 across 8 files)

---

## Verdict

**Winner: Warrior A.**

Both Warriors achieve identical pytest state (3508 passed, 0 failed, 27 xfailed, 17 xpassed). Both modify the same 8 source files. Both make the same architectural decisions (no `DispatchOptions` widening per Sage D3, settings plumbing on three constructors per Sage D-CL.1, `defaultdict` group-by for `model_costs()` per Sage D8). The choice between them is style, scope-discipline, and surfaced insight.

Warrior A wins on:
- **Tighter diff** (+80/-7 vs B's +99/-4). Conservative wins on tight contracts per `feedback_conservative_wins_execution.md`.
- **Single-line resolver precedence chain** matches the existing house style of `executor.py` and `pipeline.py` (no other multi-line `or` chains in those files).
- **Sage memo discipline** — Warrior A made the line-190 fix and explicitly flagged it for Wizard adjudication. Warrior B made the same fix without flagging (treating it as inferred from D-CL.4 prose). A's loud-fail-flag is the better operational discipline.

Warrior B's contributions are folded back as D-FTs (below) — no code from Warrior B's branch is cherry-picked into the winning branch. The architectural concerns surfaced by B are the real take-home value of running B; they file as follow-up tickets, not as code edits to BON-351's PR.

---

## Convergence — what BOTH Warriors did the same

1. **Same 8 files modified** — exact match on the Sage D10 surface map plus the `executor.py:190` envelope.model fix (Sage memo did NOT list line 190; both Warriors independently discovered it was needed).
2. **Same `DispatchCompleted.model: str = ""` field addition** to `models/events.py`, default empty string, backward-compatible.
3. **Same `DispatchRecord.model: str = ""` field + new `ModelCost` Pydantic class** with 4 fields (`model: str`, `dispatch_count: int`, `total_cost_usd: float`, `total_duration_seconds: float`).
4. **Same `model_costs() -> list[ModelCost]` aggregator** in `cost/analyzer.py` — `defaultdict`-based group-by, descending sort by `total_cost_usd`.
5. **Same settings plumbing** on `StageExecutor`, `PipelineEngine`, `WizardHandler` constructors — `settings: BonfireSettings | None = None` default, falls back to `BonfireSettings()` when None.
6. **Same precedence chain** at all three call sites: `envelope.model OR resolve_model_for_role(role, settings) OR self._config.model` (executor + wizard) and `spec.model_override OR resolve_model_for_role(spec.role, settings) OR self._config.model` (pipeline).
7. **Same line-190 fix** in `executor.py` — change `model=stage.model_override or self._config.model` to `model=stage.model_override or ""`. Without this fix, the resolver chain at line 266 short-circuits and the `test_executor_passes_role_to_resolver` Knight test fails. **Independent convergence on this fix is the strongest signal the Sage memo D10 needs an amendment.**

---

## Divergence — where Warriors A and B differed

| Aspect | Warrior A (winner) | Warrior B | Decision rationale |
|---|---|---|---|
| Resolver chain formatting | Single-line `or` chain | Multi-line paren-formatted | A matches house style; B's choice is a readability improvement deferred to a future cleanup |
| `model_costs()` body | Imperative for-loop | List-comprehension | Equivalent; A is more explicit at the cost of one line |
| `__slots__` ordering | Append `_settings` at end | Insert alphabetically | A preserves git-blame minimization; B adopts the latent alphabetical convention |
| Ticket-tag prose in source | None (already scrubbed) | Flagged BON-353 sweep guard explicitly | Both honor BON-353; B noted the sweep test on first pass (defensive) |
| Architectural concerns surfaced | 1 (line 190 fix) | 4 (line 190 + 3 more — see below) | B's read of the codebase was wider; the 3 extra concerns file as D-FTs |

---

## D-FTs to file from this code-synth

### D-FT A — Sage memo D10 surface map should include `executor.py:190`
**Severity:** Substantive
**Origin:** Both Warriors independently fixed line 190; the Sage memo did not list it.
**Suggested fix:** amend the Sage memo template (and any future BON-351-class memos) to include "all sites that pre-construct `envelope.model` upstream of the resolver call site" in the surface map. Possibly part of a broader "Sage memo template improvement" line under BON-606's umbrella.
**Size:** XS (one paragraph in a future Sage template).

### D-FT B — `pipeline.py` envelope.model is dead-weight in pipeline-mode dispatch
**Severity:** Nit (architectural; non-functional)
**Origin:** Warrior B concern #2.
**Detail:** `pipeline.py:451` sets `envelope.model = spec.model_override or self._config.model` but `pipeline.py:498` constructs `DispatchOptions(model=spec.model_override or resolver(...) or config.model)` — i.e., the envelope.model assignment at line 451 is never read for option computation. Future change to wire envelope.model into the runner or backend would surprise. Suggest unifying both dispatch paths through a single helper.
**Size:** S (extract a shared helper, ~30 LOC).

### D-FT C — `BonfireSettings()` constructed per-instance of every dispatch site
**Severity:** Nit (efficiency; non-functional today)
**Origin:** Warrior B concern #3.
**Detail:** Each of `StageExecutor`, `PipelineEngine`, `WizardHandler` calls `BonfireSettings()` in its constructor when `settings=None`, re-reading `bonfire.toml` and re-parsing env vars each time. In a long pipeline with many dispatches this is wasteful but correct. Either pass settings from a single composition root, or memoize at module scope.
**Size:** S (pick one mitigation; threads through composition root).

### D-FT D — `ModelCost` not re-exported from `bonfire.cost.__init__.py`
**Severity:** Nit (forward-API consistency)
**Origin:** Warrior B ambiguity.
**Detail:** Existing `AgentCost`, `DispatchRecord`, `PipelineRecord`, `SessionCost` are re-exported from `bonfire.cost.__init__.py`. `ModelCost` is not, by my (Wizard) call to defer it as out-of-D10-scope. The absence is a forward-public-API inconsistency. Two-line edit.
**Size:** XS.

---

## Next stage: Bard

Bard creates the BON-351 PR from `antawari/bon-351-warrior-a` (winning Warrior branch) targeting `v0.1`. PR body cites: Sage memo, both Knight branches, code-synth verdict (this document), test count delta, the line-190 fix as a flagged deviation, and the four D-FTs above.

After Bard: dual-lens Wizard review (regular Wizard + `superpowers:code-reviewer` per `feedback_dual_reviewer.md` since BON-351 is the W7 keystone) → admin-merge → Scribe close + D-FT filings.
