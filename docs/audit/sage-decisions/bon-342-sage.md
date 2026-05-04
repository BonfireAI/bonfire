# BON-342 W5.3 handlers/ — Sage Synthesis Decision Log

**Date:** 2026-04-20
**v0.1 tip:** 9ac260c
**Inputs:** Knight A (bon-342-knight-a) + Knight B (bon-342-knight-b)

## Decision Summary

| # | Decision | Verdict | Rationale |
|---|---|---|---|
| D1 | Architect generic role | **ADOPT `analyst`** (AgentRole.ANALYST = "analyst"; ROLE_DISPLAY["analyst"] = DisplayNames("Analysis Agent", "Architect")) | Anchors to the existing canonical `bonfire.analysis/` subsystem; "analyst" is profession-like (Layer-1 neutral) where "scanner" is verb-like; "architect" (Knight B) breaks Layer-1 neutrality because it IS the gamified display. |
| D2 | `ROLE: AgentRole` module constant + `HANDLER_ROLE_MAP` dict | **ADOPT** | Positive seam. Single source of truth for stem→role binding; enables grep-discoverability of the code-layer soul; makes drift impossible to hide; supports dispatch-layer role routing. |
| D3 | Gamified-literal source guard | **ADOPT_WITH_EXEMPTION** (`"Wizard Code Review"` H1 exempted) | Keeps display translation at the boundary, but the review-body H1 heading is load-bearing user-facing text rendered by GitHub's UI — forcing it through `ROLE_DISPLAY[ROLE].gamified` at render-time in a string template adds complexity without gain. |
| D4 | v1 Meta constants (`META_BARD_*`, `META_REVIEW_VERDICT_SOURCE`, `META_REVIEW_PARSE_FAILURE_REASON`) + events (`WizardReviewCompleted`, `VerdictParseFailed`) | **DEFER** via `xfail` | Porting these widens W5.3 from handler-layer work into data-layer (envelope, events) work. Separate follow-up ticket. Knight A's xfail is the cleaner shape; Knight B's shimmed imports are fine at collection time but break intent. |
| D5 | `DispatchOptions.setting_sources` + `PipelineConfig.dispatch_timeout_seconds` | **DEFER** via `xfail` | `protocols.py` is load-bearing and just audited closed (BON-332). Widening the protocol surface needs its own ticket. |
| D6 | Strategist negative assertions | **KEEP** | Cheap defensive lock that v0.1 handlers/ ships exactly four handlers; future v1-sync PRs can't accidentally add strategist without opening a ticket. |

## Per-decision analysis

### D1 — Architect generic role: ADOPT `analyst`

**Evidence weighed:**

- **Knight A proposal (`scanner`):** Layer-1 verb-neutral; matches `researcher/tester/implementer/etc.` pattern superficially BUT all the existing Layer-1 names are profession-like nouns (researcher, tester, implementer, verifier, publisher, reviewer, closer, synthesizer). `scanner` is a tool/verb — if adopted it would be the only Layer-1 name that isn't a job title.
- **Knight B proposal (`architect`):** Preserves the ticket-text literal BUT the naming module defines Layer 3 (gamified) for "Architect" and Layer 1 as profession-neutral. Using `architect` at Layer 1 collapses the three-layer distinction that the handler-port discipline is meant to enforce.
- **Wizard third option (`analyst`):** Anchored by `/home/ishtar/Projects/bonfire-public/src/bonfire/analysis/` — a canonical subsystem directory already in v0.1. A handler that scans a project and produces a ranked importance map IS functionally an analyst (analyzing structure, not merely discovering files). Profession-like. Preserves Layer-1 neutrality.

**Verdict:** `analyst`.

**Concrete lock:**

- `AgentRole.ANALYST = "analyst"` added to `src/bonfire/agent/roles.py`.
- `ROLE_DISPLAY["analyst"] = DisplayNames("Analysis Agent", "Architect")` added to `src/bonfire/naming.py`.
- `src/bonfire/handlers/architect.py` exposes `ROLE: AgentRole = AgentRole.ANALYST`.
- `StageSpec(role="analyst")` for the architect stage.
- `HANDLER_ROLE_MAP["architect"] = AgentRole.ANALYST`.

**Cited lines:**

- Knight A `test_handlers_package.py` L76-84, L135-150 (open-decision markers).
- Knight B `test_architect_handler.py` L132-144, L145-165 (aggressive ARCHITECT proposal).
- Knight B `test_handlers_role_binding.py` L44, L94-107 (architect entry conditional).
- Knight B `test_handlers_package.py` L95-111, L194-206 (architect mapping + roundtrip).

### D2 — `ROLE: AgentRole` + `HANDLER_ROLE_MAP`: ADOPT

**Evidence:** Knight B's `test_handlers_role_binding.py` introduces the single LOAD-BEARING cross-cutting invariant — every handler module exposes a `ROLE` that is an `AgentRole` enum member, and `HANDLER_ROLE_MAP` binds stem→role at package level. This:

1. Makes the code-layer soul grep-discoverable.
2. Locks drift in two places simultaneously (module ROLE + package map).
3. Supports future dispatch-layer role-routing without hardcoded dicts.

Knight A does not install this discipline; Knight A tests pass with silent drift.

**Verdict:** Adopt. All four handler modules (`bard.py`, `wizard.py`, `herald.py`, `architect.py`) expose `ROLE: AgentRole`. `handlers/__init__.py` publishes `HANDLER_ROLE_MAP: dict[str, AgentRole]`. Both lock cross-referenced in `test_handlers_role_binding.py`.

### D3 — Gamified-literal source guard: ADOPT_WITH_EXEMPTION

**Evidence:**

- Knight B `test_bard_handler.py` `TestGenericVocabularyDiscipline.test_handler_source_does_not_hardcode_gamified_display` (L215-247).
- Knight B `test_wizard_handler.py` same test (L268-296) with the `"Wizard Code Review"` exemption on L288.
- Knight B `test_herald_handler.py` same test (L120-141).
- Knight B `test_architect_handler.py` `TestNegativeDriftGuards.test_handler_source_does_not_hardcode_gamified_display` (L333-360).

**Verdict:** Keep the guard; keep the `"Wizard Code Review"` exemption.

The H1 heading in the Wizard review-body template is user-visible markdown that GitHub's UI renders. Routing it through `ROLE_DISPLAY[ROLE].gamified` at template-substitution time trades a one-line string literal for a format-string lookup — negligible DX win, non-zero cognitive cost. Architect's guard uses `"Architect"` (title case) as the sentinel since that IS the proposed gamified display.

### D4 — v1 Meta constants + events: DEFER

**Affected symbols:**

- `META_BARD_BASE_SHA`, `META_BARD_BRANCH`, `META_BARD_COMMIT_SHA`, `META_BARD_STAGED_FILES`, `META_BARD_STAGING_FAILURE_REASON` (envelope module)
- `META_REVIEW_VERDICT_SOURCE`, `META_REVIEW_PARSE_FAILURE_REASON` (envelope module)
- `WizardReviewCompleted`, `VerdictParseFailed` (events module)

**Evidence:**

- Knight A cleanly `xfail`s every dependent assertion with `_BARD_META_XFAIL`, `_EXTRA_META_XFAIL`, `_WIZARD_EVENTS_XFAIL`.
- Knight B shims the imports with placeholder values / placeholder classes — tests collect but assertions against `isinstance(e, WizardReviewCompleted)` silently return False against the shim class.

**Verdict:** DEFER. Use `xfail(reason="depends on META_BARD_* — deferred to BON-W5x-meta-ports")` shape (Knight A's approach). Don't ship shims — they compile green on a false premise. Warrior implements handlers that populate these keys with the shimmed names so the tests flip GREEN automatically when the real constants land.

**Follow-up ticket:** `BON-W5.3-meta-ports` — Port `META_BARD_*`, `META_REVIEW_VERDICT_SOURCE`, `META_REVIEW_PARSE_FAILURE_REASON`, `WizardReviewCompleted`, `VerdictParseFailed` from v1 to bonfire-public.

### D5 — DispatchOptions/PipelineConfig scope: DEFER

**Affected symbols:**

- `DispatchOptions.setting_sources` (used by Wizard handler to disable filesystem settings in review agents).
- `PipelineConfig.dispatch_timeout_seconds` (used by Wizard handler to set the execute_with_retry timeout).

**Evidence:** `protocols.py` was the subject of BON-332 (audited closed). Widening `DispatchOptions` requires its own design gate.

**Verdict:** DEFER via `xfail`.

**Follow-up ticket:** `BON-W5.3-protocol-widen` — Add `setting_sources` to `DispatchOptions`, `dispatch_timeout_seconds` to `PipelineConfig`.

### D6 — Strategist negative assertions: KEEP

**Evidence:** Knight B `test_handlers_package.py` `TestStrategistOutOfScope.test_strategist_module_not_imported_by_package_init` (L231-239), `TestPackageExports.test_all_does_not_export_strategist` (L127-129), `TestPackageDocstring.test_docstring_does_not_mention_strategist` (L172-176).

**Verdict:** KEEP. Cheap. Enforces scope boundary.

## Test suite synthesis

| Suite | Knight A raw | Knight B raw | Canonical | Dedupe |
|---|---|---|---|---|
| test_bard_handler.py | 61 test definitions | 59 tests | 59 tests | ~50% shared body, 1 additional (generic-vocab class) |
| test_wizard_handler.py | 65 tests | 45 tests | 52 tests | |
| test_herald_handler.py | 16 tests | 22 tests | 22 tests | |
| test_architect_handler.py | 20 tests | 15 tests | 18 tests | |
| test_handlers_package.py | 11 tests | 17 tests | 17 tests | |
| test_handlers_role_binding.py | — | 5 (parametrized → 19 cases) | 5 parametrized | |
| **Total (approx test nodes)** | | | ~173 | |

Dedupe strategy:
- When both Knights tested the same invariant with slightly different shapes, picked the clearer form.
- Knight B's class-based grouping adopted over Knight A's flat function layout — reads better at scale.
- Knight A's granular slug-builder tests kept intact (Knight B had same but some names differed).
- Knight B's GenericVocabularyDiscipline classes adopted WHOLE — they are the point of this wave.
- Knight B's role-binding cross-cutting suite adopted WHOLE — the load-bearing net.

## Warrior contract (symbols to implement)

### `src/bonfire/agent/roles.py` (widen)

Add enum member:

```python
class AgentRole(StrEnum):
    # ... existing members ...
    ANALYST = "analyst"
```

Update the docstring-mapping table in `AgentRole.__doc__` to add `analyst -> Analysis Agent / Architect`.

### `src/bonfire/naming.py` (widen)

Add ROLE_DISPLAY entry:

```python
ROLE_DISPLAY: dict[str, DisplayNames] = {
    # ... existing entries ...
    "analyst": DisplayNames("Analysis Agent", "Architect"),
}
```

### `src/bonfire/models/envelope.py` (widen — add Bard + Review meta keys)

```python
META_BARD_BASE_SHA: str = "bard_base_sha"
META_BARD_BRANCH: str = "bard_branch"
META_BARD_COMMIT_SHA: str = "bard_commit_sha"
META_BARD_STAGED_FILES: str = "bard_staged_files"
META_BARD_STAGING_FAILURE_REASON: str = "bard_staging_failure_reason"
META_REVIEW_VERDICT_SOURCE: str = "review_verdict_source"
META_REVIEW_PARSE_FAILURE_REASON: str = "review_parse_failure_reason"
```

(The xfail markers in synthesized test suite use `_BARD_META_XFAIL` / `_EXTRA_META_XFAIL` that flip off automatically once these land. If the Warrior adds them in the same port, tests flip GREEN.)

### `src/bonfire/handlers/__init__.py`

```python
"""bonfire.handlers — pipeline stage handlers.

File-level names stay gamified (historical + grep). The generic role each
handler implements lives in HANDLER_ROLE_MAP and as a module-level ROLE
constant inside each handler module.

| stem       | class               | generic role | gamified display |
|------------|---------------------|--------------|------------------|
| bard       | BardHandler         | publisher    | Bard             |
| wizard     | WizardHandler       | reviewer     | Wizard           |
| herald     | HeraldHandler       | closer       | Herald           |
| architect  | ArchitectHandler    | analyst      | Architect        |

Strategist is out of scope for W5.3.
"""

from bonfire.agent.roles import AgentRole
from bonfire.handlers.architect import ArchitectHandler
from bonfire.handlers.bard import BardHandler
from bonfire.handlers.herald import HeraldHandler
from bonfire.handlers.wizard import WizardHandler

HANDLER_ROLE_MAP: dict[str, AgentRole] = {
    "bard": AgentRole.PUBLISHER,
    "wizard": AgentRole.REVIEWER,
    "herald": AgentRole.CLOSER,
    "architect": AgentRole.ANALYST,
}

__all__ = [
    "ArchitectHandler",
    "BardHandler",
    "HANDLER_ROLE_MAP",
    "HeraldHandler",
    "WizardHandler",
]
```

### `src/bonfire/handlers/bard.py`

- `ROLE: AgentRole = AgentRole.PUBLISHER` (module constant).
- Class `BardHandler` — docstring cites "publisher".
- `__init__(self, *, git_workflow, github_client, config=None)`.
- `async def handle(self, stage, envelope, prior_results) -> Envelope`.
- Helpers: `_slugify_task(task, envelope_id)`, slug cap 40, suffix 12 chars.
- No `"Bard"` string literal in code body (docstrings/comments exempted).
- No EventBus, no DispatchOptions, no execute_with_retry imports.

### `src/bonfire/handlers/wizard.py`

- `ROLE: AgentRole = AgentRole.REVIEWER` (module constant).
- Class `WizardHandler` — docstring cites "reviewer".
- `__init__(self, *, github_client, backend, config, event_bus=None)`.
- `async def handle(self, stage, envelope, prior_results) -> Envelope`.
- Helpers: `_parse_verdict(text)` returning `tuple[str, str | None]`; `_parse_severity(text)` returning string.
- `_VERDICT_TAG_RE`, `_SEVERITY_TAG_RE` compiled at module scope, IGNORECASE.
- `"Wizard Code Review"` is the ONLY exempt "Wizard" literal (review-body H1 heading).

### `src/bonfire/handlers/herald.py`

- `ROLE: AgentRole = AgentRole.CLOSER` (module constant).
- Class `HeraldHandler` — docstring cites "closer".
- `__init__(self, *, github_client)`.
- `async def handle(self, stage, envelope, prior_results) -> Envelope`.
- Reads PR number from `prior_results` (META_PR_NUMBER, META_REVIEW_VERDICT, or parses GitHub PR URL from a "bard" key).
- Merges on `approve` verdict; no merge otherwise.

### `src/bonfire/handlers/architect.py`

- `ROLE: AgentRole = AgentRole.ANALYST` (module constant).
- Class `ArchitectHandler` — docstring cites "analyst" AND "architect" (the tests accept either; "architect" wording is natural since the class is named ArchitectHandler).
- `__init__(self, *, vault, project_root, project_name="", git_hash="", exclude_patterns=None)`.
- `async def handle(self, stage, envelope, prior_results) -> Envelope`.
- Depends on `bonfire.vault.scanner.ProjectScanner`, `bonfire.vault.chunker`, `bonfire.vault.memory.InMemoryVaultBackend` (still xfail-gated — these are ported in the `BON-W5.3-vault-port` follow-up if not landed yet; if Warrior lands them in this wave, tests flip GREEN).

## Follow-up tickets proposed

1. **BON-W5.3-meta-ports** — Port `META_BARD_*` (×5), `META_REVIEW_VERDICT_SOURCE`, `META_REVIEW_PARSE_FAILURE_REASON` to `bonfire.models.envelope`; port `WizardReviewCompleted`, `VerdictParseFailed` to `bonfire.models.events`. Target: flip the Bard META + Wizard extra-meta + Wizard events xfails.
2. **BON-W5.3-protocol-widen** — Add `setting_sources: list[str] = []` to `DispatchOptions`; add `dispatch_timeout_seconds: float | None = None` to `PipelineConfig`. Target: flip the `_SETTING_SOURCES_XFAIL` and `_TIMEOUT_XFAIL` markers.
3. **BON-W5.3-vault-port** — Port `bonfire.vault.memory.InMemoryVaultBackend`, `bonfire.vault.scanner.ProjectScanner`, `bonfire.vault.chunker.{chunk_markdown, chunk_source_file, content_hash}` from v1 to bonfire-public. Target: flip `_VAULT_XFAIL`, `_CHUNKER_XFAIL`, `_SCANNER_XFAIL` in the architect suite. (If Warrior ports these in this wave, the ArchitectHandler tests flip GREEN immediately.)
4. **BON-W5.3-strategist-sync** — Future ticket to port StrategistHandler (OUT OF SCOPE for W5.3). Must add strategist entry to HANDLER_ROLE_MAP, relax the "exactly four entries" test, and add docstring coverage.

## §D7 — Sage-correction pass (2026-04-21)

**Gap detected.** The initial synthesis at `8f526ca` marked the architect live-path tests with `@_HANDLER_XFAIL` alone. Once the Warrior shipped `src/bonfire/handlers/architect.py`, `_HANDLER_PRESENT` flipped `True`, the condition on `_HANDLER_XFAIL` went `False`, and those markers no-op'd. The tests then ran through `ArchitectHandler.handle()`, which lazy-imports `bonfire.vault.scanner.ProjectScanner` and `bonfire.vault.chunker.chunk_*` inside the call body, and blew up on `ModuleNotFoundError` because no vault port has landed yet (BON-W5.3-vault-port deferred per §D4-adjacent Warrior-contract note on L240). Parallel gap on Wizard: `test_max_budget_is_none` asserted `captured_options.max_budget_usd is None`, but v0.1 `DispatchOptions.max_budget_usd: float = 0.0` — non-nullable per §D5. That test had no xfail marker at all and failed outright on the `is None` assertion.

Net effect on Warrior-src PYTHONPATH run: 8 tests failing on the wrong axis (infrastructure absent, not handler contract violated). Wave discipline required re-gating, not porting.

**Marker strategy chosen.**

- **Architect (7 tests) — shape (i) Stack existing flags.** Each test decoration now names the full set of deps the call body exercises, drawn from the Warrior-contract dep table (L240 + dispatching-Wizard mission). Any-True-condition wins in pytest, so `_HANDLER_PRESENT=True AND _SCANNER_PRESENT=False` still triggers xfail via `_SCANNER_XFAIL`. Per-test dep matrix:
  - L445 `test_returns_completed_envelope_with_json_summary` — HANDLER + SCANNER + CHUNKER + VAULT.
  - L462 `test_stores_manifest_entry` — HANDLER + SCANNER + VAULT.
  - L480 `test_stores_signature_entries` — HANDLER + SCANNER + VAULT.
  - L496 `test_stores_code_chunks` — HANDLER + CHUNKER + VAULT.
  - L512 `test_skips_already_existing_hashes` — HANDLER + SCANNER (local vault stub).
  - L577 `test_vault_store_failure_returns_failed_envelope` — HANDLER + SCANNER (local vault stub).
  - L606 `test_vault_exists_failure_wraps_in_failed_envelope` — HANDLER + SCANNER (local vault stub).
  Rationale for shape (i) over shape (ii) composite flag: the stacked decorations read at the call site as a declaration of which ports each test needs, so the next Warrior porting vault can diff the decoration on/off as each port lands (SCANNER lands → test 5/6/7 auto-flip; CHUNKER lands → test 4 auto-flip; VAULT lands last → tests 1/2/3 auto-flip). A single composite flag would require re-editing the flag block each port round.

- **Wizard (`test_max_budget_is_none`, L450) — shape (ii) unconditional xfail.** Condition "is `max_budget_usd` annotation nullable" is a reflective-type-check (unwrap `Optional`/`UnionType`) — clumsy at flag-block level. The protocol-widen ticket is the explicit fix gate, and an unconditional `xfail(strict=False)` auto-reports `XPASS` the day BON-W5.3-protocol-widen lands — that XPASS is the exact signal to delete the marker. Matches the spirit of §D5 (DEFER via xfail, do NOT widen here).

**Lines touched.**

- `tests/unit/test_architect_handler.py` — 9 decorator insertions (stacked xfails above each of the 7 listed tests; no assertion/fixture/body changes).
- `tests/unit/test_wizard_handler.py` — 1 decorator insertion on L450 test function (unconditional `pytest.mark.xfail`).
- `docs/audit/sage-decisions/bon-342-sage.md` — this §D7 block appended.

**No contract changes, no src/ edits, no Warrior-worktree touches, no flag-block restructuring** — all existing flags (`_HANDLER_XFAIL`, `_VAULT_XFAIL`, `_CHUNKER_XFAIL`, `_SCANNER_XFAIL`) unchanged.

