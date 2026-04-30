# Wizard Playbook (v0.1)

The operational checklist a maintainer runs when reviewing a Warrior's PR
before the **pre-merge gate** fires. Rationale and edge cases live in
[`docs/contributor-guide/wizard-pre-stage.md`](contributor-guide/wizard-pre-stage.md);
this file is the quick reference.

---

## §1 Pre-stage editable install

Before the pre-merge gate runs, install the Warrior's worktree into the
Wizard's review venv:

```bash
pip install -e <warrior-worktree>
```

`<warrior-worktree>` is the absolute path to the Warrior's worktree on the
reviewer's machine (single-developer setup) or after fetch/mirror
(multi-machine setup). See
[`docs/contributor-guide/wizard-pre-stage.md`](contributor-guide/wizard-pre-stage.md)
§2 for why this step is non-negotiable.

This step happens BEFORE the pre-merge gate, never during, never after.

## §2 Pre-merge gate

```bash
pytest tests/ -x
ruff check src/ tests/
ruff format --check src/ tests/
```

All three MUST pass on a clean run. If any fail, the Wizard files findings
via `gh pr review --request-changes` and the Warrior fixes; loop until
green.

## §3 Review proper

```bash
gh pr diff <pr-number>
```

The Wizard reads the diff (NOT the branch files — the diff is what reviewers
see), checks against the binding Sage memo, and either approves or requests
changes via `gh pr review`.

## §4 Merge

After approval and a green gate, squash-merge to the integration branch
(`v0.1` during pre-release; `main` post-v0.1.0).

---

## See also

- [`docs/contributor-guide/wizard-pre-stage.md`](contributor-guide/wizard-pre-stage.md)
  — full rationale for the pre-stage step.
- [`docs/style.md`](style.md) — code-style canon (divider style,
  `# type: ignore` ban).
- [`docs/release-gates.md`](release-gates.md) — release-gate tier ladder.
- [`docs/audit/sage-decisions/_template-sage-memo.md`](audit/sage-decisions/_template-sage-memo.md)
  — Sage memo template the Wizard cross-references during review.
