# Bonfire Style Guide (v0.1)

Normative style decisions for the public tree. One file, one decision per
section, machine-grep-able where possible.

## Section dividers

allow: ---

Bonfire allows the multi-dash python comment divider (the `# ---` form)
as a section separator inside `.py` files. The competing multi-equals
form (`# ===`) is not endorsed by this guide; new code uses `# ---`.

Rationale: the dash form reads as a horizontal rule in editor preview,
matches the markdown convention this repo already uses for prose
section breaks, and avoids confusion with the `=` character that
Python uses for assignment.

The decision is published inline (not as YAML frontmatter) so reviewers
can scan the verdict alongside its rationale.

## Optional annotation policy

When a value may legitimately be `None`, declare the type explicitly:

```python
from typing import Optional

cost_total: Optional[float] = None
```

Or, equivalently, the PEP 604 union form:

```python
cost_total: float | None = None
```

Do not reach for a comment-driven type-checker escape such as
`# type: ignore[assignment]`. The explicit annotation is part of the
contract; the comment silently masks future regressions and pins
downstream readers to a workaround.

## Imports

Sorted by `ruff`'s `I001` rule. Run `ruff check --fix` before commit;
the agent commit protocol (see `CLAUDE.md`) makes this mandatory.

## Line length

100 characters, per `pyproject.toml`. Ruff enforces via `E501`.
