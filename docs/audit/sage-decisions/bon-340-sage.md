# BON-340 Sage Decision — Wave 5.1 `prompt/` transfer

**Date:** 2026-04-19
**Ticket:** BON-340 — Transfer `src/bonfire/prompt/` to v0.1 with IdentityBlock rename
**Base:** `v0.1 @ c59866e`
**Worktree:** `antawari/bon-340-sage`

**Sources:**
- Knight-A (innovative): `.claude/worktrees/bon-340-knight-a/tests/unit/test_prompt_compiler.py` — 124 tests, commit `524a5bd`
- Knight-B (conservative): `.claude/worktrees/bon-340-knight-b/tests/unit/test_prompt_compiler.py` — 117 tests, commit `b386841`
- Private V1 reference (read-only): `/home/ishtar/Projects/bonfire/src/bonfire/prompt/` (750 LOC), `/home/ishtar/Projects/bonfire/tests/unit/test_prompt_compiler.py` (768 lines)
- Precedent: `tests/unit/test_engine_init.py` (lazy-import shim pattern)
- Public event surface (already shipped): `src/bonfire/models/events.py:275-294` (`AxiomLoaded`)

---

## Decoupling contract

> This ticket delivers the **transfer** of V1's `prompt/` subpackage to v0.1 with one rename: the frontmatter model (V1 `AxiomMeta`) becomes `IdentityBlock`, the on-disk filename (V1 `axiom.md`) becomes `identity_block.md`, and the compiler method (V1 `load_axiom` / `load_axiom_validated`) becomes `load_identity_block` / `load_identity_block_validated`. The ticket **does NOT** rename the already-published `AxiomLoaded` event or its `event_type="axiom.loaded"` string — those are part of v0.1's existing shipped surface (`src/bonfire/models/events.py:275-294`) and renaming them mid-v0.1 would break consumers. The `cognitive_pattern` key and its seven allowed literals are preserved byte-for-byte from V1. The ticket scope is `tests/unit/test_prompt_compiler.py` (this file) + the five files Warrior will create. Warrior does NOT modify `bonfire.models.events` in this ticket. Event rename (if ever desired) is a separate, post-v0.1 concern.

---

## 1. Canonical Decisions

### D1 — Import convention: lazy-import shim pattern (Knight-B wins; Knight-A aligned)

**Decision:** Every test lazily imports `bonfire.prompt` or `bonfire.prompt.truncation` from **inside its own body** via `_prompt()` / `_truncation()` helper functions. This produces granular per-test RED rather than a single whole-file collection error.

**Rationale:** Matches the v0.1 public-test idiom in `tests/unit/test_engine_init.py`. Knight-A used a try/except try-import at module top-level with an autouse fixture that fails every test — this also produces granular RED, but the shim pattern is the established convention already in the public tree. Knight-B adopted the shim pattern directly; Knight-A is nominally aligned but with a different plumbing. **Lock: shim.**

**Source:** Sage D1 of BON-334 (`bon-334-sage-2026-04-18T19-14-42Z.md`) established this pattern repo-wide.

---

### D2 — Method names: `load_identity_block` / `load_identity_block_validated` (Knight-A wins)

**Decision:** Compiler methods are renamed from V1's `load_axiom` / `load_axiom_validated` to `load_identity_block` / `load_identity_block_validated`. The corresponding Pydantic model is `IdentityBlock` (formerly `AxiomMeta`). The module filename is `identity_block.py` (formerly `axiom_meta.py`).

**Rationale:** The three-layer naming vocabulary (`identity_block` / `mission` / `reach`) is the authoritative public-facing surface established by Anta's Naming Sage verdict in Session 052 during the public-vocab audit (see `MEMORY.md:project_bonfire_session052` — "naming vocab, audit, 30 tickets (BON-326–355)"). Knight-A renamed both the Pydantic model AND the methods; Knight-B renamed only the model but kept `load_axiom*` method names. **Lock: Knight-A's rename on the method signatures.** Public surface consistency matters more than minimising diff from V1.

**Source:** Knight-A test surface + S052 naming audit.

---

### D3 — `AxiomLoaded` event: **kept** (hybrid transitional state)

**Decision:** The `AxiomLoaded` event class and its `event_type = "axiom.loaded"` string remain unchanged. This test file does NOT re-test `AxiomLoaded` — that class already ships in `src/bonfire/models/events.py:275-294` and is covered by `tests/unit/test_events.py` (existing in v0.1). Knight-B's `TestAxiomLoadedEvent` block is intentionally omitted from the canonical suite.

**Rationale:** `AxiomLoaded` is already a published event in v0.1. Renaming it mid-v0.1 breaks the consumer contract. The method-name rename (D2) is bounded to the `prompt/` subpackage; the event surface lives in `models/` and is not in BON-340's scope. Accepting a temporary lexical inconsistency (`load_identity_block` method emits an `AxiomLoaded` event) is the correct trade: keep the published surface stable, rename internals where cheap.

**Source:** `MEMORY.md:feedback_stone_law_model_separation` (don't rename shipped surfaces). Event file already contains `AxiomLoaded` in the public repo (verified via Grep). Warrior MUST NOT touch `bonfire.models.events` in this ticket.

---

### D4 — Block-name strings: `{role}_identity` (not `{role}_axiom`), flexible assertions

**Decision:** The internal block name strings used inside `compose_agent_prompt` are `{role}_identity`, `{role}_mission`, `{role}_reach`. However, the canonical tests do NOT assert the exact block-name suffix — they assert the **presence** of identity / mission / reach layer content (via content markers, not name strings).

**Rationale:** Knight-A explicitly asserted `f"{role}_axiom"` presence; Knight-B left the naming flexible. Warrior implementation can align with V1's V1-style `{role}_axiom` for the internal block name if they prefer minimising private-V1 diff, but the Sage-canonical naming is `{role}_identity`. The tests assert composition behaviour (content reachable in output), not internal naming, so this is decoupled from the Warrior's call.

**Source:** Hybrid call informed by S052 naming conventions (external-facing = identity) + pragmatism (internal = Warrior's choice).

---

### D5 — Extra-fields policy on `IdentityBlock`: `extra="forbid"` (Knight-B wins, stricter)

**Decision:** `IdentityBlock.model_config` pins `extra="forbid"`. Unknown frontmatter keys raise `ValidationError` at parse time.

**Rationale:** Private V1 (`/home/ishtar/Projects/bonfire/src/bonfire/prompt/axiom_meta.py`) uses `model_config = {"frozen": True}` but NOT `extra="forbid"` — V1 is slightly permissive. However, for a v0.1 published contract, schema drift should fail LOUD at validation time, not silently at dispatch time. Knight-A's "accept either" approach is too permissive — a published contract must be strict about unknown keys. **Lock: `extra="forbid"` + `frozen=True`.** This is a DELIBERATE stricter-than-V1 divergence, documented here for the Wizard.

**Source:** Sage call. Adopts conservative Knight-B posture plus the explicit `extra="forbid"` escalation.

---

### D6 — Bundled-default precedence: forgiving branch kept

**Decision:** The `load_template` two-tier discovery (`project_root → bundled defaults → FileNotFoundError`) is preserved. `load_identity_block` also uses two-tier discovery (returns `None` from bundled tier if missing). The canonical test `test_falls_back_to_bundled_defaults` has a forgiving try/except branch: if a bundled default exists it asserts the template loads; if `FileNotFoundError` is raised the test passes silently.

**Rationale:** v0.1 ships NO bundled default templates (deliberately minimal distribution surface — users supply their own in `agents/<role>/prompt.md`). But the discovery-fallback code path MUST be present in the implementation so a later wave can ship bundled defaults without re-architecting the loader. Knight-B kept the forgiving test; Knight-A omitted it. **Lock: Knight-B's forgiving test.**

**Warrior note:** Ship the `importlib.resources.files("bonfire.prompt.templates")` lookup code in `compiler.py` but ship ZERO files in `src/bonfire/prompt/templates/` (empty directory with just a `__init__.py` or empty marker). This keeps v0.1's surface minimal AND keeps the fallback seam alive.

**Source:** Knight-B's conservative posture aligns with "seam before body" (`MEMORY.md:feedback_seam_before_body`).

---

### D7 — Test-count synthesis: 144 canonical tests

**Decision:** 144 canonical tests (collected). Dedup math:
- Knight-A: 124 tests
- Knight-B: 117 tests
- Overlap (identical or near-identical assertions kept from whichever Knight): ~83 tests
- Knight-A-only adversarial edges kept: ~15 tests (Jinja sandbox, Unicode, priority collisions, U-shape ties, character-slice + U-shape interaction, etc.)
- Knight-B-only conservative coverage kept: ~11 tests (individual `missing_X_raises` splits, parametrized cognitive patterns, two-element result list, etc.)
- `AxiomLoaded` event tests (Knight-B's §16 — 10 tests): **dropped** per D3 — already covered in `tests/unit/test_events.py`
- Knight-A's `TestInnovativeEdge.test_identity_block_extra_fields_rejected_or_ignored` (1 test, too-permissive): **dropped** and replaced with a single strict `test_extra_fields_rejected` per D5
- `test_identity_block_module_has_no_forbidden_imports` (dependency-constraint): **kept** (Knight-A-only; Knight-B didn't have it). This locks the `identity_block.py` filename so Warrior cannot name it otherwise.

Target was 150–180; canonical landed at 144 after deliberate `AxiomLoaded` removal (10 tests offloaded to existing event coverage). This is LEAN by design — adversarial edges preserved, redundant surface-inventory duplication pruned.

---

### D8 — `TestDependencyConstraints.test_identity_block_module_has_no_forbidden_imports`

**Decision:** This test (Knight-A) is **kept** and **load-bearing**. It LOCKS the Warrior to the filename `src/bonfire/prompt/identity_block.py`. Without this test, Warrior could ship `axiom_meta.py` with `IdentityBlock` defined inside, and the rename would be only skin-deep.

**Source:** Knight-A.

---

## 2. Summary of Tension-Matrix Verdicts

| # | Tension | Winner | Notes |
|---|---------|--------|-------|
| 1 | Import convention | Both → lazy-shim (Knight-B idiom) | Locked |
| 2 | Method names | Knight-A rename | `load_identity_block*` |
| 2b | Event name | Neither rename | Keep `AxiomLoaded` / `axiom.loaded` |
| 3 | Block-name strings | Hybrid | Warrior's call, tests stay flexible |
| 4 | Extra-fields policy | Stricter-than-both | `extra="forbid"` |
| 5 | Bundled-default precedence | Knight-B forgiving | Seam present, no files |
| 6 | Test count | Sage | 144 canonical |
| 7 | Filename lockdown test | Knight-A | `identity_block.py` enforced |

---

## 3. Warrior Handoff — exact src-file list with API surface

All paths relative to the ticket's worktree root.

### `src/bonfire/prompt/__init__.py`

Exports (public surface):

```python
from bonfire.prompt.compiler import PromptBlock, PromptCompiler, PromptTemplate
from bonfire.prompt.identity_block import IdentityBlock
from bonfire.prompt.truncation import (
    effective_budget,
    estimate_tokens,
    order_by_position,
    truncate_blocks,
)

__all__ = [
    "IdentityBlock",
    "PromptBlock",
    "PromptCompiler",
    "PromptTemplate",
    "effective_budget",
    "estimate_tokens",
    "order_by_position",
    "truncate_blocks",
]
```

### `src/bonfire/prompt/identity_block.py` (renamed from V1's `axiom_meta.py`)

Must provide:

```python
class _OutputContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    format: str
    required_sections: list[str]

    def __getitem__(self, key: str) -> object:
        return getattr(self, key)


class IdentityBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    version: str
    truncation_priority: int = Field(gt=0)
    cognitive_pattern: Literal[
        "observe", "contract", "execute",
        "synthesize", "audit", "publish", "announce",
    ]
    tools: list[str] = Field(default_factory=list)
    output_contract: _OutputContract
```

Note: V1's `axiom_meta.py` does NOT set `extra="forbid"`. The Warrior MUST add it per D5.

### `src/bonfire/prompt/truncation.py`

Pure translation from V1 (same file, 162 lines). No contract drift. The `TYPE_CHECKING` import of `PromptBlock` from `compiler.py` is preserved (avoids circular). Exports: `estimate_tokens`, `effective_budget`, `truncate_blocks`, `order_by_position`.

### `src/bonfire/prompt/compiler.py`

Direct port of V1's 517-line `compiler.py` with the following renames:

| V1 symbol | v0.1 symbol |
|-----------|-------------|
| `from bonfire.prompt.axiom_meta import AxiomMeta` | `from bonfire.prompt.identity_block import IdentityBlock` |
| `def load_axiom(self, role)` | `def load_identity_block(self, role)` |
| `def load_axiom_validated(self, role) -> tuple[PromptTemplate, AxiomMeta]` | `def load_identity_block_validated(self, role) -> tuple[PromptTemplate, IdentityBlock]` |
| Resource filename: `f"{role}_axiom.md"` → `f"{role}_identity.md"` (for bundled defaults) | same rename |
| On-disk filename under project: `axiom.md` | `identity_block.md` |
| Block name: `f"{role}_axiom"` inside `compose_agent_prompt` | Warrior's choice (tests flexible per D4). Sage recommends `f"{role}_identity"` for consistency. |

All other methods (`load_template`, `render_template`, `compile`, `compose_agent_prompt`, `compose_task_prompt`, `guard_diff`, `get_role_tools`) port byte-for-byte except for the renames above. `get_role_tools` delegates to `load_identity_block_validated` with try/except ValueError → return `[]`.

### `src/bonfire/prompt/templates/` directory

Empty is OK for v0.1. Ship an `__init__.py` (empty, or just `"""Bundled default prompt templates (empty in v0.1)."""`). This keeps `importlib.resources.files("bonfire.prompt.templates")` importable so the fallback path does not raise `ModuleNotFoundError` at import time.

---

## 4. Known transitional state (document for Wizard)

1. **`AxiomLoaded` event keeps its V1-era name while its emitting method is renamed.** This is a deliberate decoupling: event surface stability (published to users) trumps lexical consistency with internal method names. The method `load_identity_block` would emit an `AxiomLoaded` event when called by callers who wire event emission (out of scope for this ticket — compiler module does not emit events directly; higher layers do).

2. **`IdentityBlock` pins `extra="forbid"`, a DIVERGENCE from V1's `axiom_meta.py`.** V1 is permissive; v0.1 is strict. This is intentional (D5). If the Wizard prefers V1 parity, revert the `extra="forbid"` in `identity_block.py` and drop `test_extra_fields_rejected`.

3. **Block name inside `compose_agent_prompt` is not asserted.** Tests assert content markers (`IDENTITY_MARKER`, `MISSION_MARKER`), not block-name strings. Warrior's call which string to use internally. Recommend `f"{role}_identity"` for alignment with method name.

4. **No bundled default templates ship in v0.1.** The `templates/` directory exists only so the `importlib.resources.files(...)` fallback path is importable. Post-v0.1 may ship bundled defaults; the seam is alive.

---

## 5. Unresolved ambiguity for Wizard pre-merge

- **Rare output-contract edge:** V1's `_OutputContract` subclass does NOT pin `extra="forbid"`. The canonical tests assert strict rejection only on the outer `IdentityBlock`, not on `_OutputContract`. Warrior MAY ship `_OutputContract` with `extra="forbid"` too (recommended for consistency) or without (matches V1). Tests do not constrain this decision.

- **Block-name naming inside `compose_agent_prompt`:** D4 leaves this flexible. If Wizard later wants the block name visible in downstream logs/events to match the new nomenclature, a follow-up ticket can lock `{role}_identity`.

- **`{role}_identity.md` vs `{role}_axiom.md` for bundled resource filename:** No tests cover this (v0.1 ships zero bundled templates). Warrior should pick `{role}_identity.md` for consistency with the rename, but no test fails either way.
