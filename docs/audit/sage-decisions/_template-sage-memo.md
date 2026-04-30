# `<ticket-paraphrase>` — Scout-Sage Warrior Contract (D1–D10)

**Stamp:** `<UTC-stamp>` (ISO-8601, e.g. `2026-04-30T20:05:00Z`)
**Ticket:** `<ticket-paraphrase>` — `<one-line title>`
**Size:** `<S | M | L>` · adjusted to `<final-size>` after audit (rationale below) · **Priority:** `<Low | Medium | High>`
**Role:** Scout-Sage (combined; this memo is the contract handed to Knights and Warriors).
**Canonical branch:** `<author>/<ticket>-canonical` off `v0.1@<sha>` (post-`<predecessor>` merge).
**Scope:** One paragraph. State the package-surface delta, the test-floor, and the exact dispatch / engine / protocol boundary the change must NOT cross.
**Authority:** This memo is the single source of truth for scope, naming, package surface, signatures, default mappings, test names, and numeric preflight for `<ticket-paraphrase>` dispatch.

---

> **Template hygiene rule.** This template lives at the top of every published
> Sage memo's directory. It MUST stay free of internal-tracker leakage —
> external contributors copy this verbatim. Use the placeholder `<ticket-paraphrase>`
> (or `<ticket-Y>` / `<ticket-X>` for sibling references). Do NOT inline
> tracker prefixes in the template prose. Concrete memos (named after the
> ticket they document) are the only legitimate place for tracker IDs.
>
> **Real-shape reference.** A live memo following this template's section
> ordering is `bon-348-sage-20260426T013845Z.md` (CLI composition root)
> and `bon-350-sage-20260427T182947Z.md` (per-role model tier). Read either
> for a worked example of every section below.

---

## §A Inputs

The Scout reports, the relevant ADRs, the current `v0.1` HEAD, and the
upstream tickets. List each with a one-line provenance pointer:

- Scout report: `docs/audit/scouts/<ticket>-<lens>-<stamp>.md`
- Predecessor Sage memo (if porting on top of one): `docs/audit/sage-decisions/<predecessor>-sage-<stamp>.md`
- Binding ADRs: `docs/adr/ADR-001-naming-vocabulary.md` (always), plus any ticket-specific ADR
- v1 origin (if a transfer): `<v1-path>`

## §B Summary (one-line decision)

A single bolded paragraph that a returning maintainer can read in 30 seconds
and know exactly what ships. State (in order):

1. The exact package-surface delta (new files, modified files, no-touch boundary).
2. The four canonical numbers from §D8 (per-file test counts) and the §D10 preflight.
3. The ticket boundary — what the next ticket in the sequence picks up.

## §C Context: what the codebase already has

Prose-cite the existing modules, classes, and call sites the change leans
on. Each citation gets a `path:line` pointer so a fresh reader can verify.
This is the single most-skipped section in early Sage memos and the single
most useful section for Knights writing RED tests.

## §D1 — Scope

### IN-SCOPE (Warriors implement ALL of these)

Numbered list. Every item is a verifiable artifact (a file created, a class
modified, a test landed). NO prose-only items.

### OUT-OF-SCOPE — strict non-goals

Numbered list with rationale. Every non-goal includes a one-sentence reason.
"Why the next ticket owns this" is the correct shape; "we did not have time"
is NOT.

## §D2 — Package surface (LOCKED)

Concrete file-by-file LOCKED definitions. Each new or modified file gets:

- The exact path (repo-relative).
- The full source for files under ~50 LOC; otherwise the exact public symbols
  (signatures, return types, docstring summaries) and the LOC budget.
- Any ADR-001 module-name renames marked inline (e.g. `cost/` not `costs/`).

Example (a frozen mapping, with explicit `Optional[T]` instead of `# type: ignore`):

```python
"""Demo module — `<ticket-paraphrase>` — replace this docstring."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Optional

from bonfire.agent.roles import AgentRole

# Note the explicit `Optional[AgentRole]` annotation. The anti-pattern
# documented in section F (the type-ignore-assignment escape hatch)
# would silently mask a future regression where `.get()` returns `None`
# for an alias the resolver has not seen yet.
_ALIAS_TO_ROLE: Mapping[str, AgentRole] = MappingProxyType({
    "scout": AgentRole.RESEARCHER,
})


def lookup(name: str) -> Optional[AgentRole]:
    """Return the canonical role for ``name``, or ``None`` if unknown."""
    return _ALIAS_TO_ROLE.get(name.strip().lower())
```

## §D3 — Naming and ADR-001 alignment

Cite the public-tree module name for every cross-module import. ADR-001
overrides v1 spelling on every collision (`cost/` not `costs/`, `knowledge/`
not `vault/`, `workflow/` not `workflows/`, etc.). When a v1 origin is
ported, write a one-line table mapping `v1 → public` for every renamed
import.

## §D4 — Defaults and frozen tables

If the change ships a default mapping or lookup table, freeze it with
`MappingProxyType` and pin the order. Document why each row is what it is —
defaults that drift silently are the worst maintenance class.

## §D5 — Configuration surface

The exact TOML / Pydantic schema delta. State the `BonfireSettings.model_fields`
ratchet (if any) and the exact env-var nesting form. Cite which ratchet test
locks the field set.

## §D6 — Backwards-compat and migration

If the change is a transfer (v1 → public) or a v0.1 internal rename, list:

1. The exact symbols that are removed.
2. The exact symbols that are added.
3. Any deprecation shim (with sunset date).
4. The release-gate impact (if any).

## §D7 — Forbidden imports

State which modules MUST NOT import which other modules. Cite the
prompt-compiler `_FORBIDDEN` test for the v0.1 enforcement mechanism. New
forbidden edges go HERE; otherwise this section is "no change".

## §D8 — Test surface (LOCKED)

This is the single most-load-bearing section. Land the exact test-class /
test-function tree per file, per file count, and a closing arithmetic line.

### Test file 1: `tests/unit/<filename>.py` (~`<N1>` tests)

```text
class TestXxx:
    test_yyy
    test_zzz
```

### Test file 2: `tests/unit/<other>.py` (~`<N2>` tests)

```text
class TestAaa:
    test_bbb
```

(Repeat for every file.)

### Total NEW tests: `<N1>` + `<N2>` + ... + `<Nk>` = **`<T>` tests**

The arithmetic above is BOTH a Sage-author sanity check AND a machine-parseable
invariant. The `cluster-350` doc-invariant smoke test (innovation lens) parses
this line via regex, sums the addends, and asserts the prose total matches
the per-file `(~N tests)` enumeration. If you change one number, change the
other in the same edit.

## §D9 — Coupling and forbidden-edge tests

Tests that assert the change does NOT cross a stage boundary. AST-introspection
tests live here. Example: "no test in `test_resolver.py` imports
`bonfire.dispatch.*`."

## §D10 — Wizard preflight

The exact numeric ratchet. Format:

> Wizard preflight `passed_after − passed_before == +<T> ± 5`. Zero regressions
> on `failed` / `xfailed` / `xpassed`.

The `± 5` slack absorbs the unrelated test-count drift that occasionally lands
on `v0.1`. The Wizard rejects the PR if drift exceeds the band.

## §E Future tickets (D-FT)

Every non-goal that is "deferred" (not "rejected") gets a D-FT entry. The
entry is a one-paragraph stub:

- Proposed ticket title.
- Why it is not in this ticket.
- Acceptance criteria (one paragraph).
- Suggested predecessor.

These stubs become real tickets in the maintainer's tracker after Sage signs
off. External contributors see the rationale; internal maintainers see the
filing trail.

## §F Anti-patterns to avoid

A short list of patterns that have caused regressions in past Sage memos:

- **Using `# type: ignore[assignment]`** to silence a `.get()` return that
  could be `None`. Always use an explicit `Optional[T]` annotation. The
  doc-invariant smoke test (innovation lens) bans `# type: ignore[assignment]`
  inside python code blocks under `docs/audit/`.
- **Inline tracker IDs in the template.** Concrete memos may cite their own
  tracker; the template MUST stay clean.
- **Prose summary that contradicts §D8 enumeration.** The arithmetic line
  MUST match the per-file `(~N tests)` total. The smoke test parses both
  and compares.
- **Non-frozen default tables.** A plain dict can be mutated by a downstream
  caller. Always wrap with `MappingProxyType`.
- **Implicit `# ---` divider drift.** Use the canonical divider chosen in
  `docs/style.md`. Do not invent new ones in flight.

## §G Future evolution

This template is itself versioned. When a section grows or splits, bump the
template version line at the top of this file and add a one-line CHANGELOG
note here. Past template versions remain readable in git history; the
present file is the canonical shape Knights and Warriors should expect.

A future iteration may split §D2 into "package surface" and "import surface"
when v0.2 introduces a public/internal `__all__` boundary. That split SHOULD
preserve the §A-through-§G section anchors so smoke tests that grep for
section headers do not need updates.

---

**END Sage memo template.**
