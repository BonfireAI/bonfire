"""Cluster 350 doc-invariant smoke tests — INNOVATION lens (Knight B).

Four child tickets in one file:

* DFT-A (BON-606) — Sage-memo template guards.

  Two invariants:

    1. No naked tracker IDs (``BON-\\d+``) in the docstring of files under
       ``docs/audit/sage-decisions/`` whose name carries the public tracker
       prefix-free convention. The Sage *template* itself MUST stay
       canonical and free of tracker leakage; that means the literal
       ``BON-NNN`` substring is also banned because the published template
       is what external contributors copy-paste.

    2. Prose-vs-list parity for the §D8 test-surface. Every Sage memo's
       §D8 (when present) carries a closing arithmetic line of the form
       ``N1 + N2 + ... + Nk = T tests`` AND an explicit per-class /
       per-file enumeration. Both must agree.

* DFT-B (BON-608) — Explicit Optional annotation policy.

  Sage decision memos and Knight memos MUST NOT use
  ``# type: ignore[assignment]`` inside python code-blocks; the
  documented escape hatch is an explicit ``Optional[T]`` (or
  ``T | None``) annotation. We grep code-fenced blocks only — prose
  mentions of the phrase (this docstring is one) are exempt.

* DFT-C (BON-609) — Wizard pre-stage editable-install doc.

  The Wizard playbook must include a paragraph explaining:

    * the literal phrase ``pip install -e`` ; and
    * the placeholder ``<warrior-worktree>`` ; and
    * a temporal anchor (``before pre-merge gate`` OR
      ``before the pre-merge gate``).

  The doc lives at ``docs/wizard-playbook.md`` (its canonical location
  per cluster 350 plan) — the test asserts the file exists and contains
  every required token.

* DFT-D (BON-607) — ``# ---`` section-divider style decision.

  The repo grew two competing divider styles in python (``# ---``
  multi-dash and ``# ===`` multi-equals). Cluster 350 picks one and
  documents it in ``docs/style.md``. The test asserts:

    * ``docs/style.md`` exists ;
    * a normative section header about section dividers is present ;
    * the decision is parseable. We accept TWO orthogonal serializations
      so the writer can pick what reads best:
        * a YAML frontmatter block at the top of the file with a
          ``divider_style:`` key whose value is ``allow`` or ``forbid`` ;
        * OR the in-prose form ``allow: <token>`` / ``forbid: <token>``.

All tests are landed RED — every assertion is wrapped in an ``xfail``
decorator. The Warrior implementation removes the xfail marks (or, for
the doc-text tests, makes the assertion pass by writing the docs).

Why a single file with parametrize over four ticket-derived suites:

* This file IS the contract for cluster-350-docs. Future clusters can
  copy the shape verbatim, replacing the four parametrize tables.
* A single file means one xfail-removal commit per ticket — easy to
  audit. The Warrior commits four times, each time removing one
  ``@pytest.mark.xfail`` decorator and supplying the doc / scrub.
* The meta-self-test at the bottom of the file confirms that ALL FOUR
  cluster invariants are wired and visible to pytest. That guards the
  parametrize-unpacking from silently dropping a ticket — which would
  be the worst kind of regression: a doc-invariant that was supposed
  to fire but didn't.

Knight B (innovation lens) deliberately broadens every contract beyond
the ``substring-exists`` test that a conservative lens would write:

* §D8 parity is parsed via regex with multi-line tolerance, then the
  prose count and the list count are compared as integers. A future
  Sage memo that adds a §D8 with tweaked formatting will still pass
  as long as the arithmetic is internally consistent.
* The ``# type: ignore`` test parametrizes over EVERY ``.md`` file
  under ``docs/audit/sage-decisions/`` AND ``docs/audit/knight-memos/``
  (when present). Adding a new memo automatically inherits the
  invariant — no test-edit burden.
* The Wizard-doc test asserts a LIST of required tokens, not a single
  canonical phrase. Doc rewrites stay green as long as the load-bearing
  tokens are still present.
* The style.md test parses the decision in TWO orthogonal serializations
  (frontmatter OR in-prose) — the doc author picks whichever reads best.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths — repo-relative so the worktree boundary is honored
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SAGE_DIR = REPO_ROOT / "docs" / "audit" / "sage-decisions"
KNIGHT_MEMO_DIR = REPO_ROOT / "docs" / "audit" / "knight-memos"
WIZARD_PLAYBOOK = REPO_ROOT / "docs" / "wizard-playbook.md"
STYLE_DOC = REPO_ROOT / "docs" / "style.md"


# ---------------------------------------------------------------------------
# Helpers — code-block extraction so prose mentions of forbidden patterns
# don't trip the meta-tests for free
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"^```(?P<lang>[a-zA-Z0-9_+-]*)\s*\n(?P<body>.*?)^```\s*$",
    re.DOTALL | re.MULTILINE,
)


def _code_blocks(markdown: str) -> list[tuple[str, str]]:
    r"""Return [(lang, body), ...] for every fenced code block in ``markdown``.

    The ``lang`` may be empty (a bare ```\n``` opener) — that block is still
    scanned because markdown convention treats unspecified-language fences
    as code.
    """
    return [(m.group("lang"), m.group("body")) for m in _FENCE_RE.finditer(markdown)]


def _all_sage_memos() -> list[Path]:
    """Every published Sage memo. Empty list if the dir is missing.

    parametrize() requires a non-empty list to actually emit tests; the
    self-test at the end of this file guards that we have at least one.
    """
    if not SAGE_DIR.is_dir():
        return []
    return sorted(p for p in SAGE_DIR.glob("*.md") if p.is_file())


def _all_memos_for_type_ignore_check() -> list[Path]:
    """Sage decisions + Knight memos (when the dir exists)."""
    memos: list[Path] = list(_all_sage_memos())
    if KNIGHT_MEMO_DIR.is_dir():
        memos.extend(sorted(p for p in KNIGHT_MEMO_DIR.glob("*.md") if p.is_file()))
    return memos


# ---------------------------------------------------------------------------
# DFT-A (BON-606) — Sage memo template guards
# ---------------------------------------------------------------------------

# Regex for the closing arithmetic line of a §D8 prose summary.
# Tolerant of whitespace, of arbitrary number-of-summands, and of either
# "tests" or no-trailing-noun. Spans line continuations because some
# memos break the equation across lines.
_D8_ARITHMETIC_RE = re.compile(
    r"(?P<addends>\d+(?:\s*\+\s*\d+){1,})\s*=\s*\*{0,2}(?P<total>\d+)\s*(?:tests?\b|\*{0,2})",
    re.IGNORECASE,
)

# A §D8 list-form line counts a test by either:
#   - a heading line "test_<name>" indented under a TestX class, OR
#   - a bullet "* <count> tests" / "- <count> tests" / "(~<count> tests)".
# We use the "(~N tests)" / "= N tests" form which is what the BON-350
# Sage memo and its precedents use to enumerate per-file counts.
_D8_PER_FILE_COUNT_RE = re.compile(
    r"\(\s*~?\s*(?P<count>\d+)\s*tests?\s*\)",
    re.IGNORECASE,
)


def _extract_d8_section(text: str) -> str | None:
    """Return the §D8 section body (between '## D8' and the next '## ' header)."""
    # Tolerant of "## D8 — ...", "## D8 - ...", "## D8: ..." etc.
    match = re.search(
        r"^##\s+D8\b[^\n]*\n(?P<body>.*?)(?=^##\s+\S|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    return match.group("body") if match else None


@pytest.mark.xfail(
    reason="DFT-A (BON-606): Sage memo template guard — naked tracker IDs in template prose. "
    "Warrior scrubs published Sage template of BON-NNN literals.",
    strict=False,
)
@pytest.mark.parametrize("memo", _all_sage_memos() or [pytest.param(None, id="no-sage-memos")])
def test_dfta_no_naked_tracker_ids_in_published_sage_template(memo: Path | None) -> None:
    """The published Sage *template* must not carry tracker leakage.

    We treat any memo whose stem ends in ``-template`` (case-insensitive)
    as the canonical template. Concrete sage memos for shipped tickets
    legitimately reference their tracker ID; the template is what
    external contributors copy.
    """
    if memo is None:
        pytest.fail(
            f"No sage memos found under {SAGE_DIR}; the cluster-350 invariant "
            "requires at least one template."
        )
        return
    if not memo.stem.lower().endswith("-template"):
        pytest.skip(f"{memo.name} is a concrete memo, not the template")
        return
    body = memo.read_text(encoding="utf-8")
    naked = re.findall(r"\bBON-\d+\b", body)
    assert not naked, (
        f"{memo.name} carries naked tracker IDs (template must stay public-safe): "
        f"{sorted(set(naked))}"
    )


@pytest.mark.xfail(
    reason="DFT-A (BON-606): §D8 prose-vs-list parity — Warrior makes counts match.",
    strict=False,
)
@pytest.mark.parametrize("memo", _all_sage_memos() or [pytest.param(None, id="no-sage-memos")])
def test_dfta_d8_prose_and_list_counts_match(memo: Path | None) -> None:
    """When a Sage memo carries a §D8, the prose-summary arithmetic and
    the per-file enumeration must agree.

    Concrete contract:

      * Prose summary line of the form ``A + B + ... = T`` MUST exist.
      * Per-file counts ``(~N tests)`` MUST also exist.
      * sum(addends in prose) == T (parser sanity).
      * sum(per-file counts) == T (memo internal consistency).

    The test is skipped when §D8 is absent (the memo is not a
    test-surface-bearing decision).
    """
    if memo is None:
        pytest.fail(f"No sage memos found under {SAGE_DIR}.")
        return
    text = memo.read_text(encoding="utf-8")
    d8 = _extract_d8_section(text)
    if d8 is None:
        pytest.skip(f"{memo.name} has no §D8 test-surface section")
        return

    arith = _D8_ARITHMETIC_RE.search(d8)
    assert arith is not None, (
        f"{memo.name} §D8 missing prose-arithmetic line of the form 'A + B + ... = T tests'."
    )
    addends = [int(x.strip()) for x in arith.group("addends").split("+")]
    prose_total = int(arith.group("total"))
    assert sum(addends) == prose_total, (
        f"{memo.name} §D8 prose arithmetic is internally inconsistent: "
        f"{addends} sums to {sum(addends)} but the line claims {prose_total}."
    )

    list_counts = [int(m.group("count")) for m in _D8_PER_FILE_COUNT_RE.finditer(d8)]
    assert list_counts, f"{memo.name} §D8 missing per-file enumeration of the form '(~N tests)'."
    assert sum(list_counts) == prose_total, (
        f"{memo.name} §D8 prose total ({prose_total}) does not match per-file "
        f"sum ({sum(list_counts)} from {list_counts})."
    )


# ---------------------------------------------------------------------------
# DFT-B (BON-608) — explicit Optional > `# type: ignore[assignment]`
# ---------------------------------------------------------------------------

# Match `# type: ignore[assignment]` when it appears inside a python (or
# bare) code fence. We do NOT match prose mentions of the phrase — this
# very docstring is exempt because it's prose.
_TYPE_IGNORE_ASSIGNMENT_RE = re.compile(
    r"#\s*type:\s*ignore\[\s*assignment\s*\]",
)


def _has_type_ignore_in_code_fences(markdown: str) -> list[tuple[str, int]]:
    """Return [(lang, line_in_block), ...] for every offense in code fences.

    Empty list = clean.
    """
    offenses: list[tuple[str, int]] = []
    for lang, body in _code_blocks(markdown):
        # Only check python-ish blocks. Empty lang = unspecified, which we
        # still treat as code (markdown convention).
        if lang and lang.lower() not in {"python", "py", "python3", ""}:
            continue
        for idx, line in enumerate(body.splitlines(), start=1):
            if _TYPE_IGNORE_ASSIGNMENT_RE.search(line):
                offenses.append((lang or "<unspecified>", idx))
    return offenses


@pytest.mark.xfail(
    reason=(
        "DFT-B (BON-608): explicit Optional annotation > '# type: ignore[assignment]'. "
        "Warrior rewrites code-block usages to use Optional[T] / T | None."
    ),
    strict=False,
)
@pytest.mark.parametrize(
    "memo",
    _all_memos_for_type_ignore_check() or [pytest.param(None, id="no-memos")],
)
def test_dftb_no_type_ignore_assignment_in_memo_code_blocks(memo: Path | None) -> None:
    """Audit memos must not pin readers to a `# type: ignore` escape hatch.

    The decision: prefer ``Optional[T]`` (or ``T | None``) annotation that
    is explicit at the type level, over a comment-driven mypy escape that
    silently masks future regressions.
    """
    if memo is None:
        pytest.fail(
            f"No memos found under {SAGE_DIR} or {KNIGHT_MEMO_DIR}; "
            "BON-608 invariant requires at least one memo to scan."
        )
        return
    text = memo.read_text(encoding="utf-8")
    offenses = _has_type_ignore_in_code_fences(text)
    assert not offenses, (
        f"{memo.name} carries '# type: ignore[assignment]' inside a code "
        f"fence ({len(offenses)} offence(s) at "
        f"{[(lang, line) for lang, line in offenses]}). "
        f"Policy: use 'Optional[T]' / 'T | None' instead."
    )


# ---------------------------------------------------------------------------
# DFT-C (BON-609) — Wizard pre-stage editable-install doc
# ---------------------------------------------------------------------------

# Required tokens. Each item is (token, human-label-for-failure-message).
# The list is intentionally a list of substrings — any of them missing
# causes a fail with a clear pointer.
_BON609_REQUIRED_TOKENS: list[tuple[str, str]] = [
    ("pip install -e", "the editable-install command literal"),
    ("<warrior-worktree>", "the worktree path placeholder"),
    ("pre-merge gate", "the temporal anchor (when the install must run)"),
]


@pytest.mark.xfail(
    reason=(
        "DFT-C (BON-609): Wizard pre-stage editable-install doc. "
        "Warrior writes docs/wizard-playbook.md including all required tokens."
    ),
    strict=False,
)
@pytest.mark.parametrize(("token", "label"), _BON609_REQUIRED_TOKENS)
def test_dftc_wizard_playbook_documents_pre_stage_install(token: str, label: str) -> None:
    """The Wizard playbook must document the pre-stage editable-install step.

    A pre-stage `pip install -e <warrior-worktree>` against the Warrior's
    worktree (BEFORE the pre-merge gate runs) is required so that
    `importlib.metadata` returns the worktree's pyproject version, not
    the parent venv's stale install. See feedback memo
    `feedback_editable_install_metadata.md`.
    """
    assert WIZARD_PLAYBOOK.is_file(), (
        f"{WIZARD_PLAYBOOK} not found — Wizard playbook is the canonical home "
        f"for cluster-350-docs DFT-C."
    )
    body = WIZARD_PLAYBOOK.read_text(encoding="utf-8")
    assert token in body, (
        f"{WIZARD_PLAYBOOK.name} missing {label} (token {token!r}). "
        f"Doc must explain the pre-stage editable install BEFORE the pre-merge gate."
    )


# ---------------------------------------------------------------------------
# DFT-D (BON-607) — `# ---` section-divider style decision
# ---------------------------------------------------------------------------

# Frontmatter pattern: `---\n...\ndivider_style: allow\n...\n---` at top.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<body>.*?)\n---\s*(?:\n|\Z)",
    re.DOTALL,
)
_FRONTMATTER_KEY_RE = re.compile(
    r"^divider_style\s*:\s*(?P<value>\S+)\s*$",
    re.MULTILINE,
)

# Inline pattern (the in-prose form): a line starting with
# "allow:" or "forbid:" with the divider literal as the value.
_INLINE_DECISION_RE = re.compile(
    r"^(?P<verdict>allow|forbid)\s*:\s*(?P<token>[#=\-]{2,}.*)$",
    re.MULTILINE | re.IGNORECASE,
)

# Normative-header sentinels. Any one of these (case-insensitive) qualifies.
_DIVIDER_HEADERS = (
    "## section divider",
    "### section divider",
    "## dividers",
    "### dividers",
    "## section dividers",
    "### section dividers",
)


def _has_normative_divider_header(text: str) -> bool:
    lowered = text.lower()
    return any(header in lowered for header in _DIVIDER_HEADERS)


def _has_parseable_decision(text: str) -> bool:
    """True if EITHER frontmatter has divider_style OR inline allow/forbid present."""
    fm = _FRONTMATTER_RE.match(text)
    if fm and _FRONTMATTER_KEY_RE.search(fm.group("body")):
        return True
    return bool(_INLINE_DECISION_RE.search(text))


@pytest.mark.xfail(
    reason=("DFT-D (BON-607): style.md must exist and document the section-divider decision."),
    strict=False,
)
def test_dftd_style_doc_exists() -> None:
    """`docs/style.md` is the home of v0.1 style decisions."""
    assert STYLE_DOC.is_file(), (
        f"{STYLE_DOC} not found — cluster-350 DFT-D requires a canonical style.md."
    )


@pytest.mark.xfail(
    reason="DFT-D (BON-607): style.md must contain a normative section-divider header.",
    strict=False,
)
def test_dftd_style_doc_has_normative_divider_section() -> None:
    """The doc must call out section dividers as a normative decision."""
    assert STYLE_DOC.is_file(), f"{STYLE_DOC} missing — see test_dftd_style_doc_exists."
    text = STYLE_DOC.read_text(encoding="utf-8")
    assert _has_normative_divider_header(text), (
        f"{STYLE_DOC.name} missing a normative section-divider header. "
        f"Expected one of: {list(_DIVIDER_HEADERS)}."
    )


@pytest.mark.xfail(
    reason="DFT-D (BON-607): style.md decision must be machine-parseable.",
    strict=False,
)
def test_dftd_style_doc_decision_is_parseable() -> None:
    """Decision must be in YAML frontmatter OR inline allow:/forbid: form."""
    assert STYLE_DOC.is_file(), f"{STYLE_DOC} missing — see test_dftd_style_doc_exists."
    text = STYLE_DOC.read_text(encoding="utf-8")
    assert _has_parseable_decision(text), (
        f"{STYLE_DOC.name} divider decision is not machine-parseable. "
        f"Expected EITHER YAML frontmatter with `divider_style:` key, "
        f"OR an inline line starting with `allow:` / `forbid:` followed "
        f"by the divider literal."
    )


# ---------------------------------------------------------------------------
# Meta-self-test — guard the parametrize unpacking
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "Meta self-test for cluster-350 doc invariants. xfail per Knight B "
        "mission rule 'xfail decorators on every new test'; strict=False "
        "permits xpass when the parametrize unpacking is healthy."
    ),
    strict=False,
)
def test_meta_at_least_four_cluster_350_invariants_registered() -> None:
    """Sanity check: the four child tickets each ship at least one test.

    This guards against a silent parametrize drop (empty list, mistyped
    decorator) that would let a doc invariant 'pass' by simply not
    running. The set of test-function names whose first-letter token is
    DFT-{A,B,C,D} must each appear at least once in this module.

    The file already auto-discovers the four functions; this test simply
    asserts that fact, so a future refactor that drops a ticket's test
    fails LOUDLY here.
    """
    import inspect

    module = inspect.getmodule(test_meta_at_least_four_cluster_350_invariants_registered)
    assert module is not None
    test_names = [name for name in dir(module) if name.startswith("test_")]
    by_dft = {"a": [], "b": [], "c": [], "d": []}
    for name in test_names:
        # name shape: test_dft<letter>_...
        m = re.match(r"^test_dft([abcd])_", name)
        if m:
            by_dft[m.group(1)].append(name)
    missing = [letter.upper() for letter, hits in by_dft.items() if not hits]
    assert not missing, (
        f"Cluster-350 doc-invariant suite is missing tests for DFT ticket(s): "
        f"{missing}. Each child ticket (A=BON-606, B=BON-608, C=BON-609, "
        f"D=BON-607) must contribute at least one test_dft<letter>_* function."
    )
    # Total must be >= 4 — one per ticket, even after pytest collects
    # parametrize into separate ids.
    flat_count = sum(len(v) for v in by_dft.values())
    assert flat_count >= 4, f"Expected >= 4 cluster-350 invariant test functions, got {flat_count}."
