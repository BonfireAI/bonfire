# Wizard Pre-Stage Procedure

**Audience:** maintainers running the Wizard pre-merge review on a Warrior's
PR before the pre-merge gate fires.
**Status:** v0.1 binding. Updates require a PR against `v0.1` and a Sage
memo update if the procedure changes load-bearing tokens.

This document is the canonical home of the **pre-stage editable-install**
step in the Wizard playbook. The full Wizard playbook lives at
`docs/wizard-playbook.md`; this contributor-guide doc explains the
"why and when" in depth, while the playbook lists the operational steps.

---

## §1 What the pre-stage is

Before the **pre-merge gate** runs against a Warrior's PR, the Wizard MUST
perform a **pre-stage editable install** of the Warrior's worktree into the
Wizard's review venv. The single command is:

```bash
pip install -e <warrior-worktree>
```

`<warrior-worktree>` is a placeholder for the absolute path to the Warrior's
worktree on the reviewer's machine. On a single-developer setup it is
typically:

```
/home/<user>/Projects/bonfire-public/.claude/worktrees/<branch-name>/
```

On a multi-machine setup (where the Wizard reviews on a laptop and the
Warrior worked on a workstation), `<warrior-worktree>` is the path AFTER
the worktree has been fetched / mirrored to the Wizard's machine — it is
NOT the workstation path. The placeholder form `<warrior-worktree>` is
the canonical name; do not use shell-style `${WARRIOR_WORKTREE}` or any
all-caps variant.

The pre-stage must run BEFORE the pre-merge gate, not during, not after.
"Before the pre-merge gate" is the temporal anchor — the lesson is in
`feedback_editable_install_metadata.md` (operator-local) and is reproduced
here so external contributors understand the constraint without that
lesson memo.

---

## §2 Why the pre-stage is necessary

Bonfire ships as a `hatchling` src-layout package (`pyproject.toml` declares
`[tool.hatch.build.targets.wheel] packages = ["src/bonfire"]`). The
canonical install for development is:

```bash
pip install -e ".[dev]"
```

That `-e` (editable) flag points the Wizard's site-packages at the
`src/bonfire/` directory of WHICHEVER tree the install was run against. If
the Wizard runs the pre-merge gate WITHOUT the pre-stage, three classes of
silent regression are possible:

### 2.1 `importlib.metadata` returns stale version

The Warrior's PR may bump `pyproject.toml`'s version (e.g. for a
release-prep ticket). `importlib.metadata.version("bonfire-ai")` returns
the version of the INSTALLED distribution, not the version that the
file-on-disk currently declares. Without the pre-stage, the Wizard's gate
sees the previous install's version — every test that asserts the bumped
version FAILS with no signal that the cause is the install, not the code.

### 2.2 `importlib.resources` returns stale data files

The Warrior's PR may add a new data file (e.g. a Jinja template, a YAML
schema). `importlib.resources` reads the INSTALLED distribution's data —
without the pre-stage, the Wizard's gate sees the previous install's data
files. New file? Test that loads it raises `FileNotFoundError`.

### 2.3 `entry_points` returns stale CLI registration

The Warrior's PR may add a new Typer subcommand. The `[project.scripts]`
table in `pyproject.toml` is read at install time. Without the pre-stage,
running `bonfire <new-command>` invokes the OLD entry-points table and
reports "no such command" — even though the source file exists.

In all three cases, the pre-stage `pip install -e <warrior-worktree>`
refreshes the installed distribution's metadata, data files, and entry
points to match the Warrior's tree. The pre-merge gate then runs against
a faithful image of the PR.

---

## §3 When the pre-stage runs

The strict timeline:

```
1. Warrior pushes PR to feature branch.
2. Wizard fetches the PR's worktree (clone / git fetch / hard-link).
3. Wizard creates / activates a clean review venv.
4. Wizard runs:    pip install -e <warrior-worktree>           <-- pre-stage
5. Wizard runs:    pytest tests/ -x                              <-- pre-merge gate
6. Wizard runs:    ruff check src/ tests/                        <-- pre-merge gate
7. Wizard runs:    ruff format --check src/ tests/               <-- pre-merge gate
8. (gate green)    Wizard reads the diff via gh pr diff           <-- review proper
9. (gate red)      Wizard files findings via gh pr review
10. Approve / request-changes via gh pr review
11. Wizard squash-merges to v0.1 (or main, post v0.1.0).
```

The pre-stage is step 4. It runs ONCE per PR, regardless of how many gate
iterations follow. The pre-stage is NOT idempotent in a meaningful way —
re-running it on the same worktree is harmless but wasteful.

If the Warrior force-pushes (rebase + amend), the Wizard MUST re-run the
pre-stage before re-running the gate. The metadata refresh is path-keyed,
not commit-keyed.

---

## §4 Multi-machine considerations

When the Wizard reviews on a different machine than the Warrior:

1. The Warrior's worktree path on workstation does NOT carry over. The
   Wizard's `<warrior-worktree>` is whatever path the worktree lands at
   on the reviewer's machine after `git worktree add` or `git clone`.
2. The Warrior's `.venv` does NOT carry over either. Each machine maintains
   its own review venv. Trying to share a venv across machines via NFS or
   rsync is OUT OF SCOPE for v0.1; the failure modes are not worth the
   coordination cost.
3. Symlink paths and bind-mounts are TOLERATED — `pip install -e` resolves
   to the canonical path under the hood, so a symlinked
   `<warrior-worktree>` works as long as the destination is a real
   git worktree.

---

## §5 Failure modes and recovery

### 5.1 Pre-stage skipped

Symptom: pre-merge gate fails on a test that asserts the new version /
new data file / new CLI command.

Recovery: re-run `pip install -e <warrior-worktree>`. Re-run the gate.
The fix is sub-second.

### 5.2 Pre-stage ran against wrong worktree

Symptom: Wizard shadowing — the Wizard reviewed PR A's tree but the venv
is installed against PR B's tree. Gate passes (because B is healthy) but
the Wizard's findings reference symbols that exist in B but not in A.

Recovery: re-run `pip install -e <warrior-worktree>` against the CORRECT
worktree. Wizard re-reads the diff and re-files findings.

### 5.3 `pip install -e` fails (build-system error)

Symptom: `error: Microsoft Visual C++ 14.0 or greater is required` (Windows)
or `error: clang: error: linker command failed` (macOS, missing build chain).

Recovery: this means the Warrior's PR introduced a native dependency. File
this as a Wizard finding (the PR cannot ship if it breaks the editable
install on a supported OS). Bonfire v0.1 has NO native dependencies; all
dependencies are pure-Python. Any new native dep is a release-gate
violation.

---

## §6 Why this lives in the contributor guide

External contributors reviewing each other's PRs (post v0.1.0 public flip)
will not have the operator-local `feedback_*` memos that document the
internal lesson. The pre-stage requirement is portable knowledge — it
applies to every editable-install Python project, not just Bonfire. We
publish the rationale here so that external Wizards can adopt the same
discipline without internal context.

The full Wizard playbook (`docs/wizard-playbook.md`) cites this document
for the rationale and lists the operational sequence in §3 above as a
quick reference. Maintainers update this doc when the procedure changes;
the playbook follows.

---

## §7 Cross-references

- `docs/wizard-playbook.md` — operational steps (this doc's parent).
- `docs/style.md` — divider style and `# type: ignore` ban.
- `docs/release-gates.md` — release-gate ladder (the pre-merge gate is the
  Integration tier).

---

**END Wizard pre-stage procedure.**
