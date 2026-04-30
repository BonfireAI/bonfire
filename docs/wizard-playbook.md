# Wizard Playbook

Operational playbook for the Wizard role in the Bonfire pipeline.
The Wizard is the prompt-architect lens that runs against a PR diff
AFTER PR creation and BEFORE merge.

## Pre-merge gate

The pre-merge gate is the verification stage that blocks a merge until
the Wizard signs off. Two checks anchor the gate:

1. The two-lens review (Wizard + `code-reviewer`) lands `approve`.
2. The pre-stage editable install has run against the Warrior's
   worktree.

This page documents the second check.

## Pre-stage editable install

When a Warrior agent ships a feature branch from a worktree, the
pyproject metadata in that worktree may differ from the parent venv's
installed metadata (a stale `bonfire-ai` install pinned to an older
version). `importlib.metadata` returns the INSTALLED metadata, not
file metadata, so any test that asserts on the package version sees
the venv's view rather than the worktree's view.

The fix: re-install editable from the Warrior's worktree before the
pre-merge gate runs.

```bash
pip install -e <warrior-worktree>
```

Where `<warrior-worktree>` is the absolute path to the Warrior's
worktree (for example, `.claude/worktrees/cluster-NNN-warrior-a`).

The install MUST run before pre-merge gate verification. Running it
during verification or after the merge skips the gate's contract; the
test that motivated this lesson (the editable-install metadata
hazard) only fires when the worktree's pyproject and the venv's
installed metadata agree.

## Why this matters

The lesson is encoded in the operator's `feedback_editable_install_metadata.md`
note: `importlib.metadata` returns INSTALLED metadata, not file metadata.
A Warrior who bumps the pyproject version in a worktree but skips the
editable re-install will see the test pass locally (because pytest
imports from src/ via PYTHONPATH) but fail in CI (where the wheel
build sees the new version). The pre-stage install closes that gap.

## When to skip

Never skip during pre-merge gate execution. The only valid skip is
when the Warrior's worktree has not changed `pyproject.toml` AND the
parent venv install is already current. When in doubt, install.
