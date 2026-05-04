# Cluster 350 doc-invariants — Knight B (Innovation Lens) memo

**Stamp:** 2026-04-30T19:33:17Z
**Branch:** `antawari/cluster-350-docs-knight-b` (worktree off `origin/v0.1@81c9d21`)
**Lens:** Innovation — broader contracts, parametrized targets, parsable
serializations, meta-self-test guard.
**Counterpart:** Knight A is the conservative substring-existence lens.
Sage will synthesize a single canonical RED test file from the two.
**Files touched (one):** `tests/smoke/test_350_dft_doc_invariants_innovation.py`.
**Lines:** ~330. Single file, four child tickets, eight test functions plus
one meta-self-test.

---

## Summary of choices

The four cluster-350 child tickets each guard one piece of doc / memo
hygiene. The conservative knight (A) writes a substring-existence test
per ticket — easy to grok, easy to satisfy, easy to bypass. The
innovation lens broadens every contract so that the test asserts the
INVARIANT, not a specific phrasing, and so that future memos
automatically inherit the guard without test-edit burden.

| Ticket  | Conservative shape          | Innovation shape                                                                    |
| ------- | --------------------------- | ----------------------------------------------------------------------------------- |
| BON-606 | "literal §D8 line exists"   | regex parse of `A + B + ... = T` AND per-file `(~N tests)` enumeration; sums match  |
| BON-608 | "specific memo is clean"    | parametrized over EVERY `.md` under `sage-decisions/` + `knight-memos/`             |
| BON-609 | "canonical phrase present"  | parametrized list of REQUIRED tokens; doc author may rephrase the surrounding prose |
| BON-607 | "style.md mentions divider" | exists + normative header + EITHER YAML frontmatter OR inline `allow:`/`forbid:`    |

Plus one **meta-self-test** that asserts ≥ 4 `test_dft<letter>_*`
functions are registered — guards parametrize-unpacking from silently
dropping a ticket.

---

## Per-ticket innovation rationale

### DFT-A (BON-606) — Sage memo §D8 parity, regex-based

**Why regex over substring.** The §D8 prose summary in the BON-350 Sage
memo reads:

> Total NEW tests: 12 + 14 + 21 + 4 = **51 tests**

The conservative test would assert `"12 + 14 + 21 + 4 = **51 tests**"`
literally. That breaks the moment a future Sage memo (a) uses a
different number of test files, (b) drops the bold, (c) writes
`= 51 tests` without the trailing markdown emphasis. The innovation lens
parses with a tolerant regex (`\d+(?:\s*\+\s*\d+){1,}\s*=\s*\*{0,2}\d+`)
that survives all three drift directions.

**Why parametrize over EVERY sage memo, not just bon-350.** A future Sage
memo for BON-XXX will have its own §D8. Discovering memos via
`SAGE_DIR.glob("*.md")` means the invariant fires for every memo without
test-edit. Memos with no §D8 are skipped — opting out by absence is
explicit and visible in `pytest -v` output.

**Why arithmetic-consistency is the load-bearing assertion.** The real
hazard is a memo author updating one test file's count, the prose
summary, but forgetting the per-file enumeration (or vice versa). The
test catches the divergence even if BOTH numbers are valid in
isolation.

**Edge case I did NOT handle (contract question for Sage).** Multi-line
§D8 prose where the `=` and the total are on different lines. The
current regex spans whitespace but not arbitrary line continuations
inside the equation. If a memo writes:

```
12 + 14 + 21 + 4 =
51 tests
```

it would NOT match. Decision: out of scope; if the §D8 author writes
across lines they should keep the equation on one line. Knight A's
substring test would also miss this — equivalent restriction.

### DFT-B (BON-608) — code-fenced `# type: ignore[assignment]` ban

**Why fenced-code-block scoping matters.** A naive `grep` for
`# type: ignore[assignment]` would trip on prose mentions (this very
memo, the very docstring of the test file). Code-fence extraction is
the only correct shape: we ban the comment INSIDE python code blocks
where it would be a real type-checker escape hatch.

**Why parametrize over both `sage-decisions/` AND `knight-memos/`.**
Both directories ship code samples. The BON-350 memo's published
resolver code-block uses `# type: ignore[assignment]` (line 191) — that
is the single concrete offense in the current tree. Future Knight
memos that include code samples will inherit the same ban.

**Why `strict=False` on the xfail.** Most existing memos are clean
(they have no offending code blocks at all). Those tests legitimately
pass at RED-time — `strict=False` permits the xpass without flipping
the suite red. The single offending memo (BON-350) reports a real
xfail at RED-time, then becomes a real pass post-Warrior-fix.

**Edge case I did NOT handle.** The unspecified-language fence
(```` ``` ```` with no `python` tag). I treat it as code-and-scan-it.
A memo that demonstrates the BAD pattern in a `text` or `bash` block
would be ignored. Decision: that's correct — the comment is only a
type-checker escape inside python.

### DFT-C (BON-609) — Wizard pre-stage editable-install doc

**Why a list of required tokens, not a single canonical phrase.** Doc
prose evolves. The conservative test would pin one exact sentence; the
first time a maintainer rephrases ("re-install editable" instead of
"editable install") the test breaks for no reason. A token list
captures the LOAD-BEARING content (the command verbatim, the
placeholder, the temporal anchor) and lets the surrounding prose
breathe.

**Why three tokens, not five.** I deliberately picked the smallest
set that still constrains the doc to communicate the right thing:

1. `pip install -e` — the command (otherwise the doc could miss it).
2. `<warrior-worktree>` — the placeholder name (otherwise the doc
   could leave operators guessing what path to install).
3. `pre-merge gate` — the temporal anchor (otherwise the doc could
   miss the "before, not during" timing that the lesson encodes).

**Edge case.** The placeholder might be written `${warrior-worktree}`
or `WARRIOR_WORKTREE` instead of `<warrior-worktree>`. The token list
locks the angle-bracket form. **Contract question for Sage:** is
`<warrior-worktree>` the canonical placeholder, or is one of the
shell-style alternatives also acceptable? Memo's recommendation: lock
angle-brackets — matches markdown convention and matches the lesson
memo `feedback_editable_install_metadata.md`.

### DFT-D (BON-607) — `# ---` divider style decision

**Why two orthogonal serializations.** A maintainer writing a style
guide may prefer either:

* **YAML frontmatter** (`divider_style: allow`) — machine-friendly,
  parseable by every YAML library on the planet.
* **Inline prose** (`allow: # ---`) — human-friendly, scannable
  alongside the rationale paragraph.

Forcing one or the other is a writer-ergonomics call I refuse to
make for the Warrior. Both forms parse, both forms commit the
decision to a specific token, both forms survive the test. The Sage
synthesizer picks the canonical form for the synthesized RED tests.

**Why three separate test functions for DFT-D.** The check has three
orthogonal failure modes: file missing, header missing, decision
not parseable. Splitting into three tests means the failure message
points to the exact gap. Knight A's lens may collapse them; the
innovation lens splits.

**Edge case.** A maintainer writes the decision in a code-fenced block
instead of as inline prose. The current parser accepts EITHER
frontmatter or unfenced inline `allow:`/`forbid:`; a code-fenced
inline form would be missed. **Contract question for Sage:** is a
fenced inline decision acceptable? Memo's recommendation: no —
machine-parseable means top-level, not inside a fence.

---

## Meta-self-test rationale

The meta-test `test_meta_at_least_four_cluster_350_invariants_registered`
exists because parametrize is the most common silent-failure pattern in
pytest. A typo in the parametrize argument list, a `pytest.param(None)`
that escapes, an empty list — any of these makes the "test" zero-rows
and therefore vacuously green. The meta-test scans the module by
introspection and asserts that each child ticket (DFT-A through DFT-D)
contributes at least one function whose name begins with
`test_dft<letter>_`. If a future refactor drops a function or renames
the prefix, the meta-test fails LOUDLY — exactly when the invariant
disappears.

The meta-test is `xfail(strict=False)` per Knight B mission rule
"xfail decorators on every new test"; it currently xpasses (the
parametrize is healthy), which is the desired state.

---

## Why innovation lens choices are load-bearing for memo-template hygiene

Three of these choices are, in my judgement, the load-bearing ones for
preserving Sage / Knight memo hygiene over time:

1. **Glob-discovery (DFT-A and DFT-B).** Future memos automatically
   inherit the guards. The maintainer never has to remember to add
   their new memo to a test fixture. This is the single biggest
   hygiene multiplier.

2. **Token-list contracts (DFT-C).** Doc prose ages; load-bearing
   tokens don't. The token-list shape is the right primitive for any
   doc-content invariant — every cluster-350-derivative ticket should
   reach for this shape first.

3. **Parsable serializations (DFT-D).** Future style decisions need
   to remain machine-grep-able for CI. Forcing the decision into one
   of two parseable forms means a downstream ratchet test (e.g. "no
   `# ---` in src/ if the decision is `forbid`") can read the canon
   directly from the doc.

The §D8 arithmetic regex (DFT-A) is the SECOND-most load-bearing —
not because the regex is exotic, but because the entire reason §D8
exists is to keep the test-count numbers honest, and a non-arithmetic
substring test silently allows divergence.

---

## Contract questions for Sage

Listed in priority order; each is non-blocking — the synthesized test
file CAN ship with my recommendation.

1. **DFT-A scope.** Does BON-606 want the §D8 invariant to fire on
   EVERY sage memo (memo's choice), or only on memos whose stem
   starts with `bon-` (the conservative reading)? Memo recommendation:
   every memo; future Sage memos may not start with `bon-`.

2. **DFT-A "no naked tracker IDs" trigger condition.** Memo limits
   the BON-NNN scrub to files whose stem ends in `-template`, on the
   logic that concrete memos legitimately reference their tracker.
   Sage may instead want EVERY memo scrubbed (treat
   `docs/audit/sage-decisions/` as the public surface). Memo
   recommendation: template-only. Concrete memos are internal-by-name.

3. **DFT-B scope.** Does BON-608 also want to ban
   `# type: ignore[arg-type]`, `# type: ignore[return]`, etc., or
   only `[assignment]`? The ticket title is "explicit Optional
   annotation > `# type: ignore[assignment]` policy" — memo locks
   `[assignment]` only. Sage may broaden.

4. **DFT-C placeholder form.** `<warrior-worktree>` (locked by memo)
   vs `${WARRIOR_WORKTREE}` vs `WARRIOR_WORKTREE_PATH`. Pick one and
   lock it.

5. **DFT-D decision form.** Memo accepts BOTH frontmatter and inline.
   Sage MUST pick one for the canonical form to keep the test
   deterministic in synthesis. Memo recommendation: inline
   `allow: # ---` — easier to read in a doc-eyeballed review.

6. **Wizard playbook canonical path.** Memo locks
   `docs/wizard-playbook.md`. The Sage memo for cluster-350 may have
   a different canonical home (e.g. `docs/playbooks/wizard.md`). If
   so, the test paths update accordingly — single-line change.

7. **Meta-self-test xfail.** Mission says "xfail every new test."
   Strict reading would require the meta-test to fail at RED-time.
   Memo's resolution: `xfail(strict=False)` permits xpass for the
   meta-test specifically — its purpose is structural, and structural
   tests should not falsely fail. Sage may override by removing the
   xfail entirely.

---

## RED state confirmation

```
$ pytest tests/smoke/test_350_dft_doc_invariants_innovation.py
================= 66 skipped, 13 xfailed, 36 xpassed in 0.27s ==================
```

Full suite with new file:

```
$ pytest tests/ -q
3799 passed, 66 skipped, 40 xfailed, 53 xpassed, 8 warnings in 26.94s
```

Baseline of `3799 passed` holds; no failures introduced. Lint clean
(`ruff check` All checks passed; `ruff format --check` 1 file already
formatted).

---

**END Knight B (innovation) memo.**
