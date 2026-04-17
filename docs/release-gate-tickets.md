# Release-Gate Tickets — Linear drafts (BON-356 family)

> Drafted here because Linear OAuth expires mid-session. Anta or a future Wizard
> pass files them when auth is live. Keep this file until the tickets exist,
> then delete it and replace with a link to the Linear epic.

---

## BON-356 — EPIC: Release Gate v0.1 Infrastructure

**Goal.** Stand up the discipline that keeps `main` clean and validates the flip back to public at v0.1.0.

**Children.** BON-357, BON-358, BON-359, BON-360, BON-361, BON-362.

**Done when.** All children complete, `docs/release-gates.md` is the operative protocol, and Wave 2 ticket execution can begin with the gate in place.

---

## BON-357 — v0.1 branch + branch protection

**Acceptance:**
- `v0.1` integration branch live at origin — **done** in this session.
- GitHub branch protection on `v0.1`: require PR + 1 review, no direct pushes.
- Same rule on `main`.
- Rules configured via the GitHub web UI — OAuth scope on the local `gh` is insufficient.

**Owner.** Anta (UI click). Wizard verifies config via `gh api`.

---

## BON-358 — `docs/release-gates.md` + verdict schema

**Acceptance:**
- `docs/release-gates.md` covers tiers, reviewer cadence, E2E box, fixture, verdict, cost logging, API key handling, re-publish checklist, rollback, release train lifecycle.
- `tests/e2e/schemas/verdict.schema.json` is valid JSON Schema Draft-07.
- Both land in `antawari/bon-356-release-gate-scaffold` PR into `v0.1`.

**Status.** **Scaffolded** in this session's PR.

---

## BON-359 — Dockerfile + `e2e-box.sh` + `e2e-runner.sh`

**Acceptance:**
- `tests/e2e/Dockerfile` builds clean with `docker build`.
- `tests/e2e/scripts/e2e-box.sh` runs the container with host `.env` and mounts the output dir.
- `tests/e2e/scripts/e2e-runner.sh` drives Claude CLI → Bonfire → verdict emission.
- Finalize the exact `claude` CLI invocation once the fixture is ready (depends on BON-360).
- Integrate the fixture's `gate/check-verdict.sh`.
- First dry-run against a stubbed ticket emits a valid verdict JSON (PASS or FAIL — but schema-valid).

**Status.** Scaffold shipped. Runnable completion deferred to this ticket.

---

## BON-360 — Fixture target repo

**Repo.** `BonfireAI/bonfire-e2e-fixture` (private, created this session).

**Acceptance:**
- Small Python package (~10 files). Pytest suite (~15 tests).
- One deliberately broken test with a clear name and a TODO hint in the implementation file (not in the test).
- `gate/check-verdict.sh` — enforces all seven anti-cheat rules from `docs/release-gates.md`.
- `gate/expected-assertions.yaml` — declares which assertions matter for this fixture and the ticket text Claude receives.
- `README.md` explains the fixture's purpose and how the release gate consumes it.

**Ticket the fixture emits.** One deterministic, well-scoped task that Bonfire's pipeline can actually complete. Small, surgical, verifiable.

---

## BON-361 — Per-wave gate checklist template

**Acceptance:**
- `docs/templates/wave-close-gate.md` — PR template for wave-close PRs.
- Fields: wave number, tier declaration (infra / integration / E2E / release), reviewer sign-offs, E2E verdict (if applicable), open follow-ups.
- Linked from `docs/release-gates.md`.

---

## BON-362 — Audit existing open branches / PRs for fit

**Acceptance:**
- Review all open remote branches on `BonfireAI/bonfire`.
- Each branch: keep / rebase onto `v0.1` / close.
- PR #1 (BON-330 CONTRIBUTING) already merged to `main` — audit whether any of its content should move to `v0.1` or stays at `main`.
- Any stale refs pruned.
- Report posted as a comment on BON-356.

---

## Notes

- `BonfireAI/bonfire` flipped to **private** at the start of this session.
- `BonfireAI/bonfire-e2e-fixture` created **private** in this session.
- `antawari/bon-330-contributing` branch already auto-pruned remotely (PR #1 merged).
