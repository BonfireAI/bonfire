---
divider_style: allow
divider_style_token: "# ---"
forbidden_divider_style: "# ==="
applies_to: "src/bonfire/**/*.py and tests/**/*.py"
version: "0.1.0"
---

# Bonfire Style Guide (v0.1)

This document is the binding style guide for Python files under `src/bonfire/`
and `tests/`. It is companion to (not a replacement for) `pyproject.toml`'s
ruff configuration. Where ruff is silent — formatting concerns ruff does not
opine on, like section-divider comments and module-docstring shape — this
file is the canon. Where ruff and this guide overlap, ruff wins on
mechanical matters; this guide wins on rationale.

External contributors: read this BEFORE you open a PR. Reviewers will cite
specific section anchors (e.g. `## §1 Section dividers`) when requesting
changes, so the section ordering here is itself the contract.

---

## Section dividers

(Anchor: §1 Section dividers — referenced by reviewers as `## §1 Section dividers`.)

This is the normative section divider decision for the v0.1 codebase.

**Decision.** Allow `# ---` (multi-dash) section dividers inside Python source
and test files. Forbid `# ===` (multi-equals) and any other multi-character
divider style.

The decision in machine-parseable inline form (also encoded in this file's
YAML frontmatter as `divider_style: allow`):

allow: ---
forbid: ===

### Why a single style

Two divider styles grew organically across the v0.1 transfer (`# ---`
appears in roughly 80% of files; `# ===` appears in roughly 20%). Both are
visually scannable; the cost of tolerating both is invisible to readers but
real to tooling — every grep for "section dividers" must double its
patterns, every ratchet test that wants to enforce structure must check two
forms. The cluster-350 cleanup picks one and locks it.

### Why `# ---` won

- Higher in-tree adoption at decision time (~80% of files already used it).
- Visually lighter — the dash matches markdown's horizontal-rule glyph,
  reinforcing the divider's role as a soft separator rather than a heavy
  section break.
- Composes cleanly with the docstring-comment convention some modules use,
  e.g. `# --- helpers ---` reads as "minor section: helpers", which is what
  the divider is for.

### What the divider is for

A section divider marks a logical group of definitions inside a module that
is too small to warrant its own file. Use it for:

- Grouping related private helpers below the public symbols.
- Separating "Constants" from "Classes" from "Functions" in modules that
  legitimately mix all three (e.g. small registry modules).
- Visually framing the `if TYPE_CHECKING:` block at the top of a module.

Do NOT use a divider:

- Between every two functions (whitespace already does that — ruff's
  `E302`/`E305` enforce it).
- As a substitute for a docstring (every public symbol needs a docstring;
  a divider above the symbol does not count).
- Inside a function body (refactor into smaller functions instead).

### Canonical form

The canonical divider is exactly:

```python
# ---------------------------------------------------------------------------
# Section title
# ---------------------------------------------------------------------------
```

The dash run is 75 characters (one column shy of the `pyproject.toml` 100-col
line limit, leaving room for the `# ` prefix). The middle line is a single
descriptive title, capitalized, no trailing punctuation.

### Anti-patterns

```python
# ===========================================================================
# Section title
# ===========================================================================
```

The `# ===` form is FORBIDDEN. A pre-commit hook (planned, not yet wired)
will reject it on `v0.1` and `main` branches.

```python
###############
# Title
###############
```

The `#`-block form is FORBIDDEN. Reads as a banner, not a section divider.

```python
# --- title ---
def helper(): ...
```

The inline single-line form is FORBIDDEN inside `src/bonfire/`. It is
TOLERATED in scratch modules under `tests/scratch/` (which the test suite
does not import) but reviewers will request the canonical 3-line form for
any merged PR.

### Migration path

Existing `# ===` dividers in `src/bonfire/` are tracked as a follow-up
ticket. The cluster-350 contract does NOT require a sweeping rewrite —
files migrate opportunistically as PRs touch them. New files MUST use
`# ---`.

### Future evolution

When `v0.2` introduces packaged subsystems with their own internal sections,
this decision may be revisited (e.g. "two divider styles, `# ---` for module
sections and `# ===` for package-level groupings"). Any change MUST land in
this document with a version bump in the frontmatter, and a downstream smoke
test in `tests/smoke/` MUST be updated in the same PR.

---

## §2 Optional annotations vs `# type: ignore`

The v0.1 type-checker stance: prefer explicit `Optional[T]` (or `T | None`)
annotations over `# type: ignore[assignment]` escape hatches.

**Why.** A `# type: ignore` is a silent contract — it says "trust me, the
type checker is wrong here". An `Optional[T]` annotation says "the caller
must handle `None`". The latter is enforceable; the former is not.

### Before (anti-pattern)

```python
canonical = AgentRole.lookup(role_str)
if not canonical:
    canonical = GAMIFIED_TO_GENERIC.get(role_str)  # type: ignore[assignment]
```

The `# type: ignore[assignment]` here masks the fact that `.get()` returns
`Optional[AgentRole]` — when the alias is unknown, `canonical` becomes
`None` silently, and the next line (which assumes it's an `AgentRole`)
raises at runtime.

### After (preferred)

```python
canonical: Optional[AgentRole] = AgentRole.lookup(role_str)
if canonical is None:
    canonical = GAMIFIED_TO_GENERIC.get(role_str)
# canonical is now Optional[AgentRole] — handle None explicitly downstream.
if canonical is None:
    return DEFAULT_FALLBACK  # explicit, type-checked path
```

The downstream consumer is now forced (by the type system) to check for
`None` before dereferencing.

### Scope

This rule binds:

- All Sage memos under `docs/audit/sage-decisions/` — code blocks (python
  fences) are linted by the cluster-350 doc-invariant smoke test.
- All Knight memos under `docs/audit/knight-memos/` — same lint.
- All `src/bonfire/` python files — ruff and mypy will pin this once
  the v0.2 strict-mode upgrade lands.

The rule does NOT bind prose mentions of `# type: ignore` (this very
section is one — discussion of the anti-pattern is fine).

---

## §3 Module docstrings

Every module gets a one-line docstring. Multi-line docstrings are encouraged
where the module is non-trivial. The first line is a sentence in title-case
ending with a period.

```python
"""Per-role model tier vocabulary and resolver — `<ticket-paraphrase>`.

Three-tier capability axis (reasoning/fast/balanced) decoupled from the
commercial tier (free/pro/enterprise). The resolver is a pure synchronous
function — no I/O, no cache, no async.
"""
```

The `<ticket-paraphrase>` placeholder is a ticket reference; in concrete files this
becomes the actual ticket the module was born from. The placeholder form is
what appears in templates and documentation.

---

## §4 Cross-references

This style guide cites:

- `pyproject.toml` for ruff configuration (line length, target Python version).
- `docs/adr/ADR-001-naming-vocabulary.md` for module-name conventions.
- `docs/audit/sage-decisions/_template-sage-memo.md` for the canonical Sage
  memo shape (the `# type: ignore` ban here is enforced by the template's
  `§F Anti-patterns to avoid` section).
- `docs/contributor-guide/wizard-pre-stage.md` for pre-merge gate procedure.

When this file is updated, the linking files SHOULD be re-verified in the
same PR.

---

**END Bonfire style guide.**
