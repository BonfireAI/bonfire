# Sage code-synth — Cluster 350 doc-invariant Warriors

- **UTC stamp:** 2026-04-30T20:51:02Z
- **Sage code-synth branch:** `antawari/cluster-350-sage-codesynth` (off `origin/v0.1 @ e87b2c8`)
- **Mission:** Pick a winner between two competing Warrior doc-file sets for
  cluster 350. Knight B's RED test file
  (`tests/smoke/test_350_dft_doc_invariants_innovation.py`) is the binding
  contract; this memo synthesizes which Warrior's doc set best satisfies it
  and what to cherry-pick from the loser.
- **Scope:** doc-only deliverable — no `bonfire.*` runtime imports, no
  `src/bonfire/` changes, no test-file edits. The Bard PR ships ≤ 6 doc
  files plus the Knight B test file.

---

## A — Inputs

### Warrior A (CONSERVATIVE) — branch `antawari/cluster-350-warrior-a` @ `5cebf41`

Files written (3): `docs/audit/sage-decisions/_template-sage-memo.md` (86 L),
`docs/style.md` (51 L), `docs/wizard-playbook.md` (57 L).

Trade-offs:

- **Test is contract.** Wrote to `docs/wizard-playbook.md` (Knight B test
  path) and intentionally did NOT create `docs/contributor-guide/wizard-pre-stage.md`
  (Sage C spec path).
- **Inline regex compat.** `allow: ---` (bare dashes) so the Knight B
  regex `^(allow|forbid)\s*:\s*([#=\-]{2,}.*)$` matches. Sage C's
  `allow: # ---` would not match (`# ` is `#` then space, fails `{2,}`).
- **Template stem mismatch.** Filename `_template-sage-memo` does NOT end
  in `-template`, so Knight B's DFT-A-test-1 selector
  (`memo.stem.lower().endswith("-template")`) SKIPS this file. The
  naked-tracker scrub never fires on the conservative Warrior's template.
- **Minimal content.** No §D8 in the template, exact-phrase matches over
  rich rationale.

### Warrior B (INNOVATION) — branch `antawari/cluster-350-warrior-b` @ `816cd47`

Files written (5): `docs/audit/sage-decisions/_template-sage-memo.md` (228 L),
`docs/audit/sage-decisions/sage-memo-template.md` (38 L, redirect),
`docs/style.md` (225 L),
`docs/contributor-guide/wizard-pre-stage.md` (199 L),
`docs/wizard-playbook.md` (64 L).

Trade-offs:

- **Two-file template.** Canonical body at `_template-sage-memo.md` plus a
  thin redirect at `sage-memo-template.md` whose stem ends in `-template`.
  DFT-A-test-1 fires on the redirect; the redirect is clean of `BON-\d+`.
- **Dual-serialization style.** YAML frontmatter (`divider_style: allow`)
  AND inline (`allow: ---`, `forbid: ===`). Both grammars satisfied.
- **Two-file playbook.** Thin `docs/wizard-playbook.md` (test path, all 3
  required tokens) + rich `docs/contributor-guide/wizard-pre-stage.md`
  (Sage C spec path, multi-machine considerations + 11-step timeline +
  failure-mode taxonomy).
- **`<ticket-Z>` placeholder convention** propagated through templates.
- **Anti-pattern fences** in §F enumerate bad patterns; §D2 fenced demo
  shows explicit `Optional[AgentRole]` over `# type: ignore[assignment]`.

### Knight memos and Knight B's RED test file

- Knight A: `docs/audit/knight-memos/cluster-350-docs-knight-a-20260430T193646Z.md`
  on `antawari/cluster-350-docs-knight-a` @ `ed7c8fc`.
- Knight B (Sage C anointed winner):
  `docs/audit/knight-memos/cluster-350-docs-knight-b-20260430T193317Z.md`
  on `antawari/cluster-350-docs-knight-b` @ `66b8bd8`.
- Binding test: `tests/smoke/test_350_dft_doc_invariants_innovation.py` on
  the Knight B branch — 14 `xfail(strict=False)` decorators; neither
  Warrior touched the file. Verification table in §C.

### Original Sage C memo

`docs/audit/sage-decisions/cluster-350-sage-20260430T200500Z.md` on
`antawari/cluster-350-sage`. Anointed Knight B as winner; locked the
playbook at `docs/contributor-guide/wizard-pre-stage.md` and the divider
decision at `allow: # ---`. Two of those locks contradict the actual
Knight B test bytecode — see §G.

---

## B — Convergence map

| Surface | Warrior A | Warrior B | Convergence |
|---|---|---|---|
| Sage memo template | 86 L plain skeleton | 228 L with §D2 fenced sample | **disagree on depth** |
| Template filename | one file | two files (redirect for stem-selector) | **disagree on DFT-A-test-1 coverage** |
| `docs/style.md` | 51 L inline-only | 225 L frontmatter + inline + anti-patterns | **agree on inline form** |
| Wizard playbook | flat path only | flat (test path) + contributor-guide (Sage C path) | **disagree on path drift** |
| Placeholder convention | `<ticket-paraphrase>` (invented) | `<ticket-Z>` (Sage-C-derived) | **disagree on naming** |
| Inline regex compat | `allow: ---` (3 dashes) | `allow: ---` AND `forbid: ===` AND YAML | **agree** that bare dashes are needed |

The two consequential disagreements:

1. **Template stem coverage.** A's single template SKIPS the
   naked-tracker scrub silently; B's two-file strategy fires the scrub on
   the redirect. Future memo drift detection is a B-only feature.
2. **Path drift handling.** A drops Sage C's contributor-guide path; B
   writes both. Cross-references stay live in B's set.

---

## C — Test-contract verification

Per-test verdict against
`tests/smoke/test_350_dft_doc_invariants_innovation.py`:

| Test | Knight B file:line | Warrior A | Warrior B |
|---|---|---|---|
| `test_dfta_no_naked_tracker_ids_in_published_sage_template` | `:155-179` | SKIP — stem doesn't end `-template` | PASS — redirect stem matches; clean |
| `test_dfta_d8_prose_and_list_counts_match` (parametrized) | `:182-219` | SKIP for new template (`## §D8` ≠ `^##\s+D8\b`) | SKIP for new template (same) |
| `test_dftb_no_type_ignore_assignment_in_memo_code_blocks` (parametrized) | `:241-274` | PASS — no offending literal in fences | PASS — fenced sample uses `Optional[T]`; §F prose mention exempt |
| `test_dftc_wizard_playbook_documents_pre_stage_install` (3 tokens) | `:292-318` | PASS for all 3 | PASS for all 3 |
| `test_dftd_style_doc_exists` | `:367-371` | PASS | PASS |
| `test_dftd_style_doc_has_normative_divider_section` | `:375-385` | PASS — `## Section dividers` | PASS — `## Section dividers` |
| `test_dftd_style_doc_decision_is_parseable` | `:389-401` | PASS — inline matches `[#=\-]{2,}` | PASS — both forms satisfy |
| `test_meta_at_least_four_cluster_350_invariants_registered` | `:411-444` | xpass | xpass |

Net: A = 6 PASS / 2 SKIP; B = 7 PASS / 1 SKIP.

The decisive test is **DFT-A test 1**. A's filename silently SKIPS the
invariant the cluster exists to enforce.

---

## D — Winner verdict: **Warrior B (INNOVATION)**

Three reasons, in priority order, per `feedback_dual_workflow_corrected`:

1. **B is the only Warrior whose DFT-A test 1 actually fires.** A's
   filename `_template-sage-memo.md` produces a silent SKIP — the cluster's
   reason for existing (scrub future templates of internal-tracker
   leakage) is not enforced on A's deliverable. B's redirect makes the
   invariant load-bearing. Glob-discovery is the moat for memo hygiene.
2. **B reconciles Sage-C-vs-Knight-B path drift without a follow-up.** A
   picks one path and drops the other; cross-references citing Sage C's
   spec land on a 404. B writes both files: thin `docs/wizard-playbook.md`
   (test path) and rich `docs/contributor-guide/wizard-pre-stage.md`
   (Sage C path). Cross-refs stay live.
3. **B's `style.md` ages better.** Dual-serialization (YAML + inline)
   means a future ratchet preferring frontmatter does not need the doc
   rewritten. A's inline-only form will require an edit the moment any
   tooling shifts to YAML parsing.

Soft signal AGAINST B: 5 doc files vs A's 3 increases review surface.
Mitigated because the redirect is 38 lines and load-bearing, and the
contributor-guide page is the canonical home Sage C mandates. None is
filler.

---

## E — Cherry-pick recipe (loser → winner)

Two A-side contributions to fold into B:

1. **A's terser §A-`Conventions` paragraph** in `_template-sage-memo.md`.
   A's "copy this file, rename it, fill in the sections" framing is
   crisp guidance for first-time copy-paste users; prepend it under B's
   title.
2. **A's plain-English placeholder `<ticket-paraphrase>`.** B uses
   `<ticket-Z>`. Anta's standing instruction (no naked Linear IDs;
   paraphrase wins) suggests `<ticket-paraphrase>` is the better
   long-term placeholder. Rename `<ticket-Z>` → `<ticket-paraphrase>`
   throughout B's templates.

Cherry-pick **count: 2**.

### Path drift between Sage C spec and Knight B test

Already resolved in B by writing **both files**. Bard PR keeps both:
playbook = test-asserted quick-reference, contributor-guide page =
rationale-and-procedure reference. They cross-link.

### Inline-decision regex compatibility

Sage C wrote `allow: # ---`; Knight B's regex `[#=\-]{2,}` requires 2+
consecutive chars from `{#, =, -}`, so `# ` (single `#` then space)
fails. Both Warriors correctly pivoted to `allow: ---`. Bard PR keeps
the bare-`---` form; B's style.md prose distinguishes in-code divider
grammar (`# ---`) from in-prose decision-token grammar (`---`).

---

## F — Bard PR assembly plan

Bard creates the integration branch off `v0.1` per CLAUDE.md Worktree
Merge Protocol:

```bash
git checkout v0.1 -b antawari/cluster-350-docs-bundle
```

Pick up doc files from Warrior B (winner):

```bash
git checkout antawari/cluster-350-warrior-b -- \
    docs/audit/sage-decisions/_template-sage-memo.md \
    docs/audit/sage-decisions/sage-memo-template.md \
    docs/style.md \
    docs/contributor-guide/wizard-pre-stage.md \
    docs/wizard-playbook.md

git checkout antawari/cluster-350-docs-knight-b -- \
    tests/smoke/test_350_dft_doc_invariants_innovation.py
```

Apply cherry-picks:

- Edit `docs/audit/sage-decisions/_template-sage-memo.md`: prepend A's
  three-sentence "copy, rename, fill" framing under the title.
- Edit both template files: replace `<ticket-Z>` with
  `<ticket-paraphrase>` throughout. `<UTC-stamp>` unaffected.

Commit (imperative, no tracker IDs):

```bash
git add docs/audit/sage-decisions/_template-sage-memo.md \
        docs/audit/sage-decisions/sage-memo-template.md \
        docs/style.md \
        docs/contributor-guide/wizard-pre-stage.md \
        docs/wizard-playbook.md \
        tests/smoke/test_350_dft_doc_invariants_innovation.py

git commit -m "Land cluster-350 doc-invariant guards and Sage-memo template"
```

### Verification

```bash
PYTHONPATH=src .venv/bin/pytest \
    tests/smoke/test_350_dft_doc_invariants_innovation.py -v
# Expect: 7 invariants xpass, 1 xpass (meta-self-test), DFT-A-test-2
# parametrized over all sage memos shows pre-Warrior xfail/xpass mix.

PYTHONPATH=src .venv/bin/pytest tests/ -q
# Full suite: baseline + 0 net-new tests (Knight B file already RED-counted);
# xpass count rises by ~7.
```

xfail decorators stay; `strict=False` permits xpass.

---

## G — Drift findings to surface

Three contract gaps between Sage C's locked spec and Knight B's test
bytecode. None block the Bard PR; each deserves a follow-up D-FT.

### Gap 1 — Wizard playbook canonical path

- **Sage C lock:** `docs/contributor-guide/wizard-pre-stage.md`.
- **Knight B test (line 17):** `WIZARD_PLAYBOOK = "docs/wizard-playbook.md"`.
- **Resolution:** Bard ships both.
- **Recommendation:** Sage C §G.1 acknowledged the synthesized RED file
  was never published on the Sage branch — the Knight file became
  contract by default. File a follow-up to either deprecate
  `docs/wizard-playbook.md` or deprecate the contributor-guide page;
  until then, both coexist by design. Future Sage memos that mandate a
  synthesized file MUST publish it BEFORE Warrior dispatch.

### Gap 2 — Inline-decision token format

- **Sage C lock:** `allow: # ---` (mirrors in-code divider).
- **Knight B regex (line 354):** `[#=\-]{2,}.*` — `# ` (single `#` then
  space) does NOT match.
- **Resolution:** B wrote `allow: ---` inline AND
  `divider_style: allow` in YAML, with rationale prose.
- **Recommendation:** File a D-FT to lock the grammar difference
  explicitly in `docs/style.md` (in-code divider grammar vs in-prose
  decision-token grammar). Alternative: widen the Knight regex in a
  future iteration to permit a leading `#\s+` prefix.

### Gap 3 — Template stem-selector convention

- **Knight B test (line 162):** `endswith("-template")`.
- **Sage C lock:** underscore-prefix `_template-sage-memo.md` (stem does
  NOT end in `-template`).
- **Resolution:** B wrote `sage-memo-template.md` redirect.
- **Recommendation:** File a D-FT to either rename the canonical body to
  `sage-memo-template.md` (and retire the redirect) or widen the
  selector to also match `_template-*` stems. The cleaner long-term
  rule is "template files end in `-template.md`".

---

## H — Decisions for Anta to ratify

1. **Winner = Warrior B.** Two-file template, dual-serialization style,
   dual-path playbook are load-bearing for invariants A silently skips.
2. **Cherry-pick `<ticket-paraphrase>` over `<ticket-Z>`.** Matches the
   "no naked Linear IDs; paraphrase wins" discipline.
3. **File three D-FT follow-ups** (one per §G drift finding). Cleanup
   only, none block the Bard PR.
4. **Bard merge target = `v0.1`.** Docs-only ship; release-gate ratchet
   unchanged.

---

**End cluster-350 Sage code-synth memo.**
