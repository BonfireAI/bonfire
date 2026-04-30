# Cluster 351 — Sage Code-Synth Verdict (Warrior A vs Warrior B)

**Stamp:** 2026-04-30T23:00:00Z
**Lane:** bonfire-public · `antawari/cluster-351-sage-codesynth`
**Base HEAD:** `cebe690` (`origin/v0.1`)
**Sage spec (binding):** `docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md`
**Mission:** pick a winner between two competing GREEN implementations of
the locked Sage architectural contract; produce the Bard PR cherry-pick
recipe.

---

## A — Inputs

| Lane | Branch | SHA | Files | +/- | Lens |
|---|---|---|---|---|---|
| Warrior A (CONSERVATIVE) | `antawari/cluster-351-warrior-a` | `c2bb3d7` | 13 | +1516/-71 | minimum-diff, retargets legacy patches |
| Warrior B (INNOVATION) | `antawari/cluster-351-warrior-b` | `96b9e95` | 14 | +2840/-26 | hedge-imports, `Final[str]`, provenance comments, retrospective doc |

Both Warriors implemented Sage §F (Axis 1 helper) + §G (Axis 2 factory)
verbatim against the same Knight RED contract (Knight A unit lens at
`tests/unit/test_engine_model_resolver.py` + `test_engine_factory.py`;
Knight B integration lens at `test_engine_pipeline.py` +
`test_engine_executor.py` + `tests/conftest.py`).

The architectural contract was already locked by the parent Sage memo —
this synthesis is purely a code-quality + test-fidelity comparison.

---

## B — Convergence map

### B.1 Where A and B AGREE

1. **Helper signature is byte-identical to Sage §C.1.** Both:
   `resolve_dispatch_model(*, explicit_override: str, role: str,
   settings: BonfireSettings, config: PipelineConfig) -> str`. Module
   path `src/bonfire/engine/model_resolver.py` for both. Pure
   synchronous, no I/O, no caching.
2. **Factory signature is byte-identical to Sage §C.2.** Both:
   `load_settings_or_default() -> BonfireSettings`, never raises.
   Module path `src/bonfire/engine/factory.py`.
3. **Both use a broad `except Exception as exc: # noqa: BLE001`** in
   the factory. This matches Knight A §H.2.4's parametrized
   never-raise contract over `RuntimeError / ValueError / OSError`,
   none of which sit inside the narrow `(ValidationError,
   TOMLDecodeError, OSError)` tuple Sage §C.2 documented. Both
   Warriors converged on the wide catch independently.
4. **Both delete the `pipeline.py:456` dead envelope.model write per
   Decision D.** Replaced with `model=spec.model_override or ""`
   (executor empty-string sentinel parity). Warrior A:
   `pipeline.py:455`. Warrior B: `pipeline.py:472`.
5. **Both replace the inline 3-tier `or` chain at all three call sites**
   (`engine/executor.py`, `engine/pipeline.py`, `handlers/wizard.py`)
   with `resolve_dispatch_model(...)`. Wizard call site preserves
   `ROLE.value` ("reviewer") in both per Sage §K decision 5.
6. **Both wire the `settings=None` branch in all three constructors to
   `load_settings_or_default()`.** Warrior A: `executor.py:91`,
   `pipeline.py:115`, `wizard.py:263`. Warrior B: `executor.py:97`,
   `pipeline.py:121`, `wizard.py:269`.
7. **Both keep `bonfire.engine.__init__` un-touched.** Helper + factory
   reachable only via fully-qualified imports (Sage §C.1 explicitly
   said re-export is NOT required for v0.1).
8. **Knight A unit tests + Knight B integration tests + autouse
   conftest fixture** present and identical in both worktrees.

### B.2 Where A and B DIVERGE

| Axis | Warrior A | Warrior B | Bound to test contract? |
|---|---|---|---|
| Legacy `resolve_model_for_role` import at call-site modules | **Removed** at `executor.py`, `pipeline.py`, `wizard.py` | **Preserved with `# noqa: F401`** (the hedge) | Yes — drives B.2.1 below |
| Old `TestModelResolution` patch targets in 3 test modules | **Retargeted (10 sites)** to `bonfire.engine.model_resolver.resolve_model_for_role` | **Left at legacy call-site paths** (`bonfire.engine.{pipeline,executor}.resolve_model_for_role`, `bonfire.handlers.wizard.resolve_model_for_role`) | Yes — drives C below |
| `Final[str]` sentinels | absent | `_EMPTY_MODEL_SENTINEL` + `_WARNING_MESSAGE_TEMPLATE` | No |
| Module-level architectural-rationale docstrings | minimal | multi-paragraph "why this seam exists" | No |
| Provenance comments `# Per cluster-351 Sage memo §F.<n>` | absent | every replaced call site | No |
| Warning log payload | `exc` only | `type(exc).__name__` AND `exc` | No (test asserts substring "Failed to load BonfireSettings", both pass) |
| Retrospective doc | absent | `docs/audit/retrospective/cluster-351-warrior-b-20260430T220000Z.md` | No |

### B.2.1 The hedge does NOT preserve the legacy contract

Warrior B's retrospective (§Open contract questions item 1) admits this
itself: even with `# noqa: F401` keeping `resolve_model_for_role` bound
at the three call-site modules, the dispatch path now goes through
`bonfire.engine.model_resolver` — patches at the legacy call-site
modules **mutate a binding the production code no longer reads**.

Two of the three preserved `TestModelResolution` cases per call site
(`override_wins`, `role_passed_through`) coincidentally still pass
because they exercise paths upstream of the resolver invocation. The
third — `*_config_model_wins_when_resolver_empty` — fails because the
patch no longer reaches the actual `resolve_model_for_role` call
(which now lives behind `bonfire.engine.model_resolver`'s import).
Warrior A's clean retargeting is the only correct surface.

---

## C — Test-state verification

Bash is denied in this synthesis lane; the following is contract-level
prediction validated by file-level grep against both worktrees.

### C.1 Knight RED contract (14 tests + 1 fixture-validation)

Both Warriors flip all 14 Knight RED tests to GREEN and the
`test_conftest_scrubs_bonfire_env_for_engine_module` validation passes.
Source-file grep confirms both worktrees ship identical test files
post-cherry-pick.

### C.2 Pre-existing `TestModelResolution` retargeting

| Test file | Pre-existing `TestModelResolution` patches | Warrior A behavior | Warrior B behavior |
|---|---|---|---|
| `tests/unit/test_engine_executor.py` | 6 sites (lines 990, 1011, 1053, 1136, 1201, 1285) | All retargeted to `bonfire.engine.model_resolver.resolve_model_for_role` — patches reach the helper's import | Left at `bonfire.engine.executor.resolve_model_for_role` — patches mutate a binding the production code no longer reads |
| `tests/unit/test_engine_pipeline.py` | 3 sites (lines 1246, 1265, 1296 in A; 1243, 1263, 1294 in B) | All retargeted to `model_resolver.resolve_model_for_role` | Left at `bonfire.engine.pipeline.resolve_model_for_role` |
| `tests/unit/test_wizard_handler.py` | 1 site (line 571 in A; 574 in B) | Retargeted to `model_resolver.resolve_model_for_role` | Left at `bonfire.handlers.wizard.resolve_model_for_role` |

**Net:** A passes the full suite green; B passes the new contract but
breaks at minimum 3 legacy `*_config_model_wins_when_resolver_empty`
tests (one per call-site module) due to the patch-target drift. The
hedge `# noqa: F401` import is cosmetic.

### C.3 `TestVocabularyParity` + `TestResolverWiring`

Warrior A retargeted these too (also in `test_engine_executor.py`).
Warrior B did not. Same drift class — A green, B at-risk on whichever
of those exercise the resolver invocation path.

---

## D — Winner verdict

**Winner: WARRIOR A (CONSERVATIVE).**

Three-bullet justification:

1. **Test-fidelity correctness.** Warrior A retargeted 10 pre-existing
   patch sites to the new canonical seam (`model_resolver`
   re-imports `resolve_model_for_role`). Warrior B's `# noqa: F401`
   hedge keeps the symbol bound at call-site modules but the
   production code no longer reads it through that binding —
   `*_config_model_wins_when_resolver_empty` cases fail under B.
   Warrior B's own retrospective admits this. A is the only branch
   that lands the contract change AND keeps the existing suite green.
2. **Minimum-diff discipline matches the Sage spec.** Sage §J.5 lists
   the two no-go paths to reject. Warrior B's `Final[str]` sentinels,
   provenance comments at every call site, and multi-paragraph
   module-rationale docstrings are *additions*, not the contract.
   Sage §F.1 / §G.1 specified two new files — A delivers two new
   files plus the minimum surrounding diff; B delivers two new files
   plus ~1300 lines of extra prose, comments, and a retrospective
   doc. Smaller PR diff = easier Wizard review = faster merge into
   a Wave 9.1-blocked release train.
3. **`Final[str]` sentinels carry zero runtime weight (PEP 591).**
   They're a static-checker hint. The Knight contract asserts on
   substring `"Failed to load BonfireSettings"` (Sage §H.2.2 / §H.2.3),
   not on the constant's name. The `Final` annotation does not earn
   its place in the diff at this size.

---

## E — Cherry-pick recipe (which losing-side bits to fold in)

Concrete decisions for the four divergence axes the dispatch flagged:

| Question | Verdict | Rationale |
|---|---|---|
| Patch-target retargeting (10 sites) | **Adopt A's clean retargeting.** | B's hedge is cosmetic; the legacy patches don't reach the new resolver path even with the `# noqa` import preserved. |
| `Final[str]` sentinels | **Drop B's; keep A's plain literals.** | Zero runtime effect; test contract asserts on substring, not on name. Adds noise without benefit. |
| Provenance `# Per ... §F.<n>` comments | **Strip B's.** | The Sage memo IS the trail. Comments duplicate-ate the audit-doc reference at every call site — costs review time, no read-time benefit since `git blame` already points at the cluster-351 PR. One brief comment at each *new file's* module docstring is sufficient (A already has this). |
| Retrospective memo | **Drop.** | Useful as an internal artifact; not a release-train asset. Knight memos + Sage memo + Sage code-synth memo (this file) are the canonical audit chain. The retrospective adds a fourth class of doc with zero ratification value. |
| Wide `except Exception` in factory | **Keep (already in A).** | Both Warriors converged on this; it matches Knight A §H.2.4's `RuntimeError`/`ValueError`/`OSError` parametrize. Drift from Sage §C.2's narrow tuple is documented in G as accept-as-D-FT-followup. |
| Warning log payload (`type(exc).__name__` + `exc` vs `exc` only) | **Keep A's plain `exc`.** | Warrior A's plain-`exc` log includes the exception's repr (e.g. `ValidationError(...)`) which already encodes the type. B's split is a marginal readability improvement that doesn't earn its diff size. |

**Net cherry-pick count from B into A:** 0. Warrior A is canonical
as-is.

---

## F — Bard PR assembly plan (Worktree Merge Protocol per CLAUDE.md)

Branch: `antawari/cluster-351-bundle` off `v0.1@cebe690`.

```bash
# 1. Cut the bundle branch from the integration tip.
git checkout v0.1
git pull origin v0.1
git checkout -b antawari/cluster-351-bundle v0.1

# 2. Pull all source + test changes from Warrior A (the canonical lens).
git checkout antawari/cluster-351-warrior-a -- \
    src/bonfire/engine/model_resolver.py \
    src/bonfire/engine/factory.py \
    src/bonfire/engine/executor.py \
    src/bonfire/engine/pipeline.py \
    src/bonfire/handlers/wizard.py \
    tests/unit/test_engine_model_resolver.py \
    tests/unit/test_engine_factory.py \
    tests/unit/test_engine_executor.py \
    tests/unit/test_engine_pipeline.py \
    tests/unit/test_wizard_handler.py \
    tests/conftest.py

# 3. Pull the audit chain (Sage spec + both Knight memos + this synth memo).
#    Each lives on its authoring branch.
git checkout antawari/cluster-351-sage -- \
    docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md
git checkout antawari/cluster-351-knight-a -- \
    docs/audit/knight-memos/cluster-351-knight-a-20260430T210000Z.md
git checkout antawari/cluster-351-knight-b -- \
    docs/audit/knight-memos/cluster-351-knight-b-20260430T210000Z.md
git checkout antawari/cluster-351-sage-codesynth -- \
    docs/audit/sage-decisions/cluster-351-sage-codesynth-20260430T230000Z.md

# 4. Verify GREEN on the bundle.
pytest tests/ -x
ruff check src/ tests/
ruff format --check src/ tests/

# 5. Single bundle commit (per Worktree Merge Protocol).
git add -A
git commit -m "add engine model resolver helper and settings factory"
git push -u origin antawari/cluster-351-bundle

# 6. Open PR via Bard against v0.1.
```

Per CLAUDE.md `git checkout branch -- files` (NOT cherry-pick) is the
deterministic merge style; no commit-tangling.

---

## G — Drift findings vs Sage spec

| Drift | Severity | Verdict |
|---|---|---|
| Factory uses wide `except Exception` instead of narrow `(ValidationError, TOMLDecodeError, OSError)` tuple per Sage §C.2 | minor | **acceptable** — Knight A §H.2.4 parametrize fixes this contract by including `RuntimeError`/`ValueError`. Wider catch is the only consistent-with-test choice. Document in PR body. |
| Wizard call site uses `stage.model_override or ""` (rebuilds the empty-string sentinel inline) instead of letting `resolve_dispatch_model` see `stage.model_override` directly | trivial | **acceptable** — `or ""` is a defensive cast against a `None` stage.model_override. No behavioral difference on a string field. |
| Both Warriors keep `from bonfire.agent.tiers import resolve_model_for_role` removed at the three call-site modules (A) — no re-export from `bonfire.engine.__init__` either | none | **matches Sage §C.1** — explicitly stated re-exports NOT required for v0.1. |
| Knight A used `@pytest.mark.xfail(strict=True)` markers in `test_engine_model_resolver.py` + `test_engine_factory.py` | none — by design | Strict-xfail flips to test-runner failure on XPASS. Warrior phase removes the markers in the same diff per the canonical Bonfire RED pattern. Verify markers gone in bundle. |
| Old `TestModelResolution` retargeting from `bonfire.engine.{executor,pipeline}.resolve_model_for_role` to `bonfire.engine.model_resolver.resolve_model_for_role` (10 sites) | spec-silent — Sage §H.6 left "minor renames OK" but did not pre-specify retargeting | **accept-as-D-FT-followup**: file a v0.2 follow-up to either (a) prune the old `TestModelResolution` classes once the helper-test coverage is mature, or (b) keep them as a regression net pinning the helper's inner `resolve_model_for_role` call. |

No re-roll items. All drift falls inside the Sage §H.6 ±1 tolerance
plus the minor-naming flexibility the spec already grants.

---

## H — Decisions for Anta to ratify (≤4 lines)

1. Pick A as canonical; cherry-pick zero from B.
2. Bundle branch name: `antawari/cluster-351-bundle` (matches existing
   convention `cluster-350-bundle`).
3. PR body cites this memo + both Knight memos + the parent Sage spec.
4. File one v0.2 follow-up: prune the now-redundant
   `TestModelResolution::*_config_model_wins_when_resolver_empty` cases
   once the helper-suite coverage is ratified by a maintainer.

---

## Sources

- `docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md` (binding spec)
- `docs/audit/knight-memos/cluster-351-knight-a-20260430T210000Z.md` (unit lens)
- `docs/audit/knight-memos/cluster-351-knight-b-20260430T210000Z.md` (integration lens)
- `docs/audit/retrospective/cluster-351-warrior-b-20260430T220000Z.md` (B's self-disclosure of patch-target drift, §Open contract questions item 1)
- Warrior A worktree at `c2bb3d7`; Warrior B worktree at `96b9e95`
- Repo `CLAUDE.md` § Worktree Merge Protocol (`git checkout` not cherry-pick)
- ADR-001 module roster (singular `model_resolver.py`, `factory.py`, no `vault/` `costs/` `workflows/` leaks)

---

**End of Sage code-synth memo.** Winner: A. Bundle plan locked.
Awaiting Wizard commit + push + Bard dispatch.
