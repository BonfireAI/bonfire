# Knight A (Conservative Lens) — 350-Cluster Doc Invariants

**Stamp:** 2026-04-30T19:36:46Z
**Branch:** `antawari/cluster-350-docs-knight-a` (off `origin/v0.1` @ `81c9d21`)
**Single test file:** `tests/smoke/test_350_dft_doc_invariants.py` (5 RED tests)
**Cluster:** 4 follow-up tickets from the 350 doc-polish audit
(internal IDs paraphrased per repo convention — see `CONTRIBUTING.md`).

The Warrior fixes each contract by creating the target file with the
content shape described below. Every assertion is anchored on file
existence + literal substring; nothing requires AST or template
parsing.

---

## Contract 1 — Sage memo template scrubs ticket refs in code blocks

- **Test:** `test_sage_template_sample_code_blocks_have_no_naked_ticket_refs`
- **Target path Warrior creates:**
  `docs/audit/sage-decisions/_template-sage-memo.md`
- **Content shape:**
  - A reusable Sage-memo skeleton (D1–D10 sections mirroring the
    real `bon-XXX-sage-*.md` artifacts already in this directory).
  - Sample-code blocks (fenced with triple backticks) MUST NOT
    contain `BON-\d+` literals. Use placeholder strings like
    `ticket-NNN` or `<ticket>`. Prose outside fenced blocks may
    still cite real tickets — only fenced sample-code is scrubbed.

## Contract 2 — Sage memo template §D8 prose-vs-list parity

- **Test:** `test_sage_template_d8_prose_count_matches_list_count`
- **Target path Warrior creates:** same as Contract 1.
- **Content shape inside §D8:**
  - Heading `## D8 — Test surface` (or `## D8 ...` — regex matches
    `^##\s*D8`).
  - A prose total of the form `NN net-new tests` or `NN tests total`.
  - Fenced blocks listing explicit `test_*` identifiers; the count of
    DISTINCT identifiers under §D8 must equal the prose total.
  - If §D8 is absent in the template, the test skips (parity is
    conditional on the section's presence).

## Contract 3 — `# ---` divider verdict codified

- **Test:** `test_style_doc_documents_section_divider_convention`
- **Target path Warrior creates:** `docs/style.md`
- **Content shape:**
  - Must contain the literal string `# ---` (the comment-divider in
    Python source).
  - Must contain at least one verdict word from
    `{"allow", "permitted", "forbid", "banned", "discouraged"}`.
  - Conservative pick: ALLOW. Existing source already uses both
    `# ---` and `# ───` (e.g. `tests/unit/test_no_bon_ref_in_src_sweep.py`,
    `src/bonfire/analysis/models.py`). Forbidding would force a
    sweep we don't have appetite for at v0.1.

## Contract 4 — Wizard pre-stage editable-install step documented

- **Test:** `test_wizard_pre_stage_doc_documents_editable_install`
- **Target path Warrior creates:**
  `docs/contributor-guide/wizard-pre-stage.md`
- **Content shape:**
  - Must contain the literal phrase `pip install -e`.
  - Must contain the case-insensitive string `worktree`.
  - Recommended body: a paragraph explaining that the reviewer
    (Wizard, in the gamified vocabulary) MUST run
    `pip install -e <warrior-worktree>` before reviewing a PR built
    on a worktree branch, so editable-install metadata reflects the
    branch under review.

## Contract 5 — Templates avoid `# type: ignore[assignment]`

- **Test:** `test_sage_templates_avoid_type_ignore_assignment`
- **Target path Warrior creates:** same as Contract 1.
- **Content shape:**
  - The canonical template MUST exist (anchors the contract).
  - No file under `docs/audit/sage-decisions/` whose stem starts
    with `_template` may contain the literal string
    `# type: ignore[assignment]`. The convention demonstrated in
    sample blocks should be the explicit `Optional[T]` annotation
    on the first line, then `.get()` reassign — no suppression.

---

## Verification snapshot (pre-Warrior)

```text
$ PYTHONPATH=src .venv/bin/pytest tests/smoke/test_350_dft_doc_invariants.py -v
test_sage_template_sample_code_blocks_have_no_naked_ticket_refs XFAIL
test_sage_template_d8_prose_count_matches_list_count            XFAIL
test_style_doc_documents_section_divider_convention             XFAIL
test_wizard_pre_stage_doc_documents_editable_install            XFAIL
test_sage_templates_avoid_type_ignore_assignment                XFAIL
=> 5 xfailed (RED, as expected)
```

Full suite (worktree): `3799 passed, 32 xfailed, 17 xpassed` —
baseline 3799 passed preserved; xfailed grew by exactly 5
(27 → 32) from this file's contracts.

Ruff on the new test file: clean (`ruff check` + `ruff format --check`
both pass on `tests/smoke/test_350_dft_doc_invariants.py`).

---

## Contract questions for Sage

1. **Template path.** Conservative lens picked
   `docs/audit/sage-decisions/_template-sage-memo.md` (underscore
   prefix sorts isolated from real `bon-NNN-*` artifacts and signals
   "not a decision, a skeleton"). If Sage prefers
   `docs/audit/templates/sage-memo.md` (separate directory), update
   `_TEMPLATE_PATH` and `_iter_template_memos` glob in the test file.
2. **§D8 prose-count regex.** Currently matches `NN net-new tests`
   OR `NN tests total` (case-insensitive). The historical
   `bon-350-sage` memo uses the phrase `**51 net-new tests total**`.
   If Sage wants a stricter or looser regex, update
   `_PROSE_COUNT`.
3. **Verdict verbs.** Contract 3 accepts any of
   `{allow, permitted, forbid, banned, discouraged}`. If Sage wants
   the canonical wording locked (e.g. only "ALLOWED" with caps),
   tighten the assertion.
4. **`worktree` literal.** Contract 4 requires substring `worktree`
   anywhere (case-insensitive). If Sage wants the more specific
   phrase `pip install -e <warrior-worktree>` as the literal
   citation, replace the two assertions with one substring check on
   the full canonical phrase.
