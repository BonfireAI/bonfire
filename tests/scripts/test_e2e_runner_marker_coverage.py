# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Every alternative in the box runner's two marker lists, proved against real pip text.

``tests/e2e/scripts/e2e-runner.sh``'s ``classify_pip_failure`` decides whether a
failed pip step is reported as ``box_network_unreachable`` (the box's link died,
the wheel was never reached) or ``artifact_install_failed`` (the wheel is
broken). It decides that with two ``|``-separated regex alternations: ten
``artifact_markers`` and seventeen ``transport_markers``.

``test_e2e_runner_install_resilience.py`` proves the *shapes* of the 2026-07-27
incident — DNS death, a read timeout on a socket that accepts and never
answers, a refused connection, four artifact shapes, and one mixed control rod.
Measured against the shipped lists, that left the *vocabulary* almost entirely
unproved: 6 of 17 transport alternatives and 4 of 10 artifact alternatives
appeared in any log the classifier is ever fed, and — counting only
alternatives whose deletion would change a result — **0 of 17** transport and
**2 of 10** artifact alternatives were load-bearing. A pattern nobody proved
matches anything is decoration, and a decorative transport marker is exactly
how a dead link gets reported as a false accusation against a released wheel.

CONTRACT (three parts, each with its own test):

1. Every alternative in each shipped list has a captured-shape log that
   exercises it, and each such log classifies the way its list demands.
2. The set of alternatives the shipped runner carries **equals** the set this
   suite covers. Adding a marker to the runner without a fixture turns
   ``test_every_shipped_alternative_has_a_fixture`` RED and names it.
3. Deleting any alternative from the shipped list flips a real log's verdict.
   That is the control rod: it proves these tests disagree with a broken
   classifier rather than merely agreeing with the current one.

PARSING ASSUMPTIONS for (2), stated so a future shape change fails loudly
instead of silently parsing to nothing:

* each list is assigned on ONE line inside ``classify_pip_failure``, as
  ``local <name>='<body>'`` with single quotes;
* exactly one such assignment exists per name — zero or two is an error, not a
  best-effort pick;
* ``<body>`` is a top-level ``|`` alternation with no grouping parentheses and
  no escaped pipes; a body containing ``(``, ``)`` or ``\\|`` is refused rather
  than mis-split;
* every alternative is non-blank and carries no padding.

AN EMPTY PARSE CANNOT PASS. The body pattern is ``[^']+`` — at least one
character — so ``local transport_markers=''`` yields no match and
``_split_marker_list`` raises ``MarkerListParseError``. A renamed or deleted
``classify_pip_failure`` yields an empty extraction and raises too.
``test_the_parser_refuses_a_list_it_cannot_read`` drives all five refusal
shapes directly, and ``test_the_shipped_lists_parse_to_real_alternations``
asserts non-zero counts plus known-shipped anchors *before* any coverage claim
is made, so "every marker is covered" is never vacuously true over an empty
set.

ROUTE TAKEN FOR THE CONTROL ROD: real mutation of the extracted shell. Each
mutation test re-extracts ``classify_pip_failure`` from the shipped runner,
deletes one alternative from one list, and runs the mutant under a real bash.
The weaker route — asserting only that an unmatched log falls through to
``artifact`` — is already covered by
``test_unrecognised_output_defaults_to_artifact`` in the sibling module and
proves nothing about any individual alternative. Three transport alternatives
cannot be mutation-proved alone because real pip never prints them without a
second marker in the same log; they are declared in ``SUBSUMED_TRANSPORT`` and
proved as a *pair*, so the declaration cannot rot into an excuse for an
ungraded marker.

The captured logs live in ``e2e_pip_log_corpus.py`` — data with no assertions,
split out because this file plus the corpus breaks the 500-line form budget.

This module is pure, offline and deterministic. It runs bash and reads files.
It never touches Docker, the network, an API key, or ``.e2e-runs/``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.scripts.e2e_pip_log_corpus import (
    ARTIFACT_FIXTURES,
    DEGRADED_TAIL,
    MIXED_DEGRADED_SHAPES,
    SOLE_TRANSPORT,
    SUBSUMED_TRANSPORT,
    TRANSPORT_FIXTURES,
)
from tests.scripts.test_e2e_runner_install_resilience import (
    PLAYBOOK,
    RUNNER,
    _extract_function,
)

#: Reason codes as the runner emits them. The optional second segment keeps
#: ``trap:sigterm`` whole while dropping the ``:$label`` / ``:installed=…``
#: suffixes that are filled in at run time.
REASON_CODE = re.compile(r'emit_failure_verdict "([a-z_]+(?::[a-z_]+)?)[:"]')


# --------------------------------------------------------------------------
# Reading the shipped lists, and mutating them.
# --------------------------------------------------------------------------


class MarkerListParseError(RuntimeError):
    """A shipped marker list could not be read as a top-level `|` alternation.

    Raised rather than returning an empty tuple: an empty list would make every
    coverage assertion vacuously true, which is the failure shape this module
    exists to remove.
    """


def _shipped_classifier() -> str:
    """Return the verbatim ``classify_pip_failure`` text from the shipped runner."""
    shell = _extract_function("classify_pip_failure")
    if not shell:
        raise MarkerListParseError("classify_pip_failure is no longer defined in the runner")
    return shell


def _split_marker_list(shell: str, name: str) -> tuple[str, ...]:
    """Split the ``local <name>='a|b|c'`` assignment in *shell* into alternatives."""
    found = re.findall(rf"^[ \t]*local {re.escape(name)}='([^']+)'[ \t]*$", shell, re.MULTILINE)
    if len(found) != 1:
        raise MarkerListParseError(
            f"expected exactly one `local {name}='...'` line, found {len(found)}"
        )
    body = found[0]
    if any(token in body for token in ("(", ")", "\\|")):
        raise MarkerListParseError(f"{name} has a shape this parser cannot split safely: {body!r}")
    alternatives = tuple(body.split("|"))
    blank = [index for index, alt in enumerate(alternatives) if not alt.strip()]
    if blank:
        raise MarkerListParseError(f"{name} has blank alternatives at positions {blank}")
    return alternatives


def _shipped_alternatives(name: str) -> tuple[str, ...]:
    return _split_marker_list(_shipped_classifier(), name)


def _without(shell: str, name: str, alternative: str) -> str:
    """Return *shell* with *alternative* deleted from marker list *name*."""
    alternatives = _split_marker_list(shell, name)
    if alternative not in alternatives:
        raise MarkerListParseError(f"{alternative!r} is not an alternative of {name}")
    kept = [alt for alt in alternatives if alt != alternative]
    if not kept:
        raise MarkerListParseError(f"{name} would be emptied, and an empty grep matches everything")
    old = f"local {name}='{'|'.join(alternatives)}'"
    return shell.replace(old, f"local {name}='{'|'.join(kept)}'", 1)


def _classify_with(shell: str, log_text: str, tmp_path: Path) -> str:
    """Run *shell*'s ``classify_pip_failure`` over *log_text* under a real bash."""
    log = tmp_path / "step.log"
    log.write_text(log_text, encoding="utf-8")
    script = tmp_path / "classify.sh"
    script.write_text(
        f'set -euo pipefail\n{shell}\nclassify_pip_failure "{log}"\n', encoding="utf-8"
    )
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, check=False, cwd=str(tmp_path)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


# --------------------------------------------------------------------------
# 1. Every alternative is exercised by a captured shape.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alternative", sorted(TRANSPORT_FIXTURES))
def test_every_transport_shape_is_read_as_the_box_and_not_the_wheel(
    alternative: str, tmp_path: Path
) -> None:
    """A degraded or dead link must never be reported as a broken artifact."""
    verdict = _classify_with(_shipped_classifier(), TRANSPORT_FIXTURES[alternative], tmp_path)
    assert verdict == "network", alternative


@pytest.mark.parametrize("alternative", sorted(ARTIFACT_FIXTURES))
def test_every_artifact_shape_beats_a_degraded_link(alternative: str, tmp_path: Path) -> None:
    """Each artifact marker must win over transport noise, not merely over silence.

    Asserting that an artifact-only log classifies ``artifact`` would prove
    nothing: the classifier's default branch already answers ``artifact`` for
    any log it does not recognise, so such a test passes even with the marker
    deleted. Every artifact alternative is therefore graded through a degrading
    link, where the default branch cannot supply the answer.
    """
    shipped = _shipped_classifier()
    mixed = DEGRADED_TAIL + ARTIFACT_FIXTURES[alternative]
    assert _classify_with(shipped, mixed, tmp_path) == "artifact", alternative
    # The counterfactual that makes the line above load-bearing.
    assert _classify_with(shipped, DEGRADED_TAIL, tmp_path) == "network"


@pytest.mark.parametrize("name", sorted(MIXED_DEGRADED_SHAPES))
def test_a_broken_wheel_on_a_merely_degraded_link_stays_an_artifact_failure(
    name: str, tmp_path: Path
) -> None:
    """The ordering rule, proved against slow-and-partial rather than only dead.

    The sibling module's one mixed control rod uses a fully *refused*
    connection. These four use the degraded shapes the incident class is
    actually made of — a truncated transfer, a stalled read, a captive portal —
    and one of them prints the artifact error *before* the transport noise, so
    the rule cannot be passing by reading position.
    """
    mixed, transport_half = MIXED_DEGRADED_SHAPES[name]
    shipped = _shipped_classifier()
    assert _classify_with(shipped, mixed, tmp_path) == "artifact", name
    assert _classify_with(shipped, transport_half, tmp_path) == "network", name


# --------------------------------------------------------------------------
# 2. The non-vacuity assertion: covered set == shipped set.
# --------------------------------------------------------------------------


def test_the_shipped_lists_parse_to_real_alternations() -> None:
    """Guard the guard: prove the parse returned the real lists before using it.

    Every claim in this file is quantified over the parsed alternatives, so a
    parse that silently returned nothing would make them all vacuously true.
    Counts must be non-zero, and each list must contain an alternative that is
    unmistakably from the shipped runner rather than from a stub.
    """
    artifact = _shipped_alternatives("artifact_markers")
    transport = _shipped_alternatives("transport_markers")
    assert len(artifact) > 0, "artifact_markers parsed to nothing"
    assert len(transport) > 0, "transport_markers parsed to nothing"
    assert "Invalid wheel filename" in artifact, artifact
    assert "ReadTimeoutError" in transport, transport
    for name, alternatives in (("artifact", artifact), ("transport", transport)):
        assert len(set(alternatives)) == len(alternatives), f"{name} list repeats an alternative"
        for alt in alternatives:
            assert alt.strip() == alt, f"{name}: {alt!r} carries padding the grep would match"
            assert "|" not in alt, f"{name}: {alt!r} was not split"


def test_every_shipped_alternative_has_a_fixture() -> None:
    """No marker ships unproved, and no fixture proves a marker that is gone.

    Set EQUALITY in both directions. Adding a marker to the runner without a
    captured log turns this RED and names it; deleting one and leaving the
    fixture behind turns this RED too, so the corpus cannot drift into a
    description of a classifier that no longer exists.
    """
    for name, fixtures in (
        ("artifact_markers", ARTIFACT_FIXTURES),
        ("transport_markers", TRANSPORT_FIXTURES),
    ):
        shipped = set(_shipped_alternatives(name))
        covered = set(fixtures)
        unproved = sorted(shipped - covered)
        orphaned = sorted(covered - shipped)
        assert not unproved, f"{name}: shipped but never proved by a fixture: {unproved}"
        assert not orphaned, f"{name}: proved by a fixture but no longer shipped: {orphaned}"


def test_the_mutation_sweep_cannot_run_zero_cases() -> None:
    """Assert-checked-more-than-zero, applied to the control rod itself.

    ``SOLE_TRANSPORT`` is derived by subtracting ``SUBSUMED_TRANSPORT`` from the
    corpus, so an over-declared subsumption table would empty the mutation
    sweep — and a parametrised test with no cases is reported as green. Both
    sides of the subsumption declaration must also be alternatives the runner
    really ships, or the pair proof is grading strings that are not in the gate.
    """
    transport = set(_shipped_alternatives("transport_markers"))
    assert set(SUBSUMED_TRANSPORT) <= transport, sorted(set(SUBSUMED_TRANSPORT) - transport)
    assert set(SUBSUMED_TRANSPORT.values()) <= transport, sorted(
        set(SUBSUMED_TRANSPORT.values()) - transport
    )
    assert SOLE_TRANSPORT, "no transport alternative is proved by deletion on its own"
    assert len(SOLE_TRANSPORT) == len(transport) - len(SUBSUMED_TRANSPORT)
    assert len(SOLE_TRANSPORT) >= 2 * len(SUBSUMED_TRANSPORT), (
        f"{len(SUBSUMED_TRANSPORT)} of {len(transport)} alternatives are declared unprovable "
        "alone; the subsumption allow-list is the exception, not the mechanism"
    )


def test_the_parser_refuses_a_list_it_cannot_read() -> None:
    """An unreadable list raises; it never degrades to an empty tuple.

    This is what makes ``test_every_shipped_alternative_has_a_fixture``
    impossible to pass vacuously. All five refusal shapes are driven directly:
    a missing assignment, an EMPTY assignment, a duplicated one, a body whose
    grouping this parser will not guess at, and a body with a blank
    alternative — which as a bare ``grep -E`` alternation would match every
    log ever written.
    """
    with pytest.raises(MarkerListParseError):
        _split_marker_list("classify_pip_failure() {\n    local other='x'\n}", "transport_markers")
    with pytest.raises(MarkerListParseError):
        _split_marker_list("    local transport_markers=''", "transport_markers")
    with pytest.raises(MarkerListParseError):
        _split_marker_list(
            "    local transport_markers='a'\n    local transport_markers='b'",
            "transport_markers",
        )
    with pytest.raises(MarkerListParseError):
        _split_marker_list("    local transport_markers='(a|b)|c'", "transport_markers")
    with pytest.raises(MarkerListParseError):
        _split_marker_list("    local transport_markers='a||b'", "transport_markers")


# --------------------------------------------------------------------------
# 3. The control rod: these tests disagree with a broken classifier.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("alternative", SOLE_TRANSPORT)
def test_deleting_a_transport_alternative_produces_a_false_accusation(
    alternative: str, tmp_path: Path
) -> None:
    """Mutation proof, one alternative at a time.

    The shipped classifier is extracted, ONE transport alternative is deleted,
    and the same captured log is re-graded. It must flip to ``artifact`` — the
    false accusation against a released wheel that the 2026-07-27 incident
    produced, and what a typo or an upstream pip rewording in that alternative
    would silently cause. A suite that could not show this flip would only be
    agreeing with the code it grades.
    """
    log = TRANSPORT_FIXTURES[alternative]
    assert _classify_with(_shipped_classifier(), log, tmp_path) == "network", alternative
    mutant = _without(_shipped_classifier(), "transport_markers", alternative)
    assert _classify_with(mutant, log, tmp_path) == "artifact", alternative


@pytest.mark.parametrize(("alternative", "subsumer"), sorted(SUBSUMED_TRANSPORT.items()))
def test_a_subsumed_transport_alternative_is_really_subsumed(
    alternative: str, subsumer: str, tmp_path: Path
) -> None:
    """The three alternatives real pip never prints alone, proved as pairs.

    ``ReadTimeoutError`` always arrives with ``Read timed out``, and
    ``NewConnectionError`` always arrives with its own message text, so
    deleting either one alone cannot flip a verdict. This test asserts exactly
    that, then deletes BOTH and asserts the flip — which proves the pair is
    load-bearing and stops ``SUBSUMED_TRANSPORT`` from becoming a parking space
    for a marker nobody ever graded.
    """
    log = TRANSPORT_FIXTURES[alternative]
    assert subsumer in _shipped_alternatives("transport_markers"), subsumer
    one_gone = _without(_shipped_classifier(), "transport_markers", alternative)
    assert _classify_with(one_gone, log, tmp_path) == "network", alternative
    both_gone = _without(one_gone, "transport_markers", subsumer)
    assert _classify_with(both_gone, log, tmp_path) == "artifact", (alternative, subsumer)


@pytest.mark.parametrize("alternative", sorted(ARTIFACT_FIXTURES))
def test_deleting_an_artifact_alternative_launders_a_broken_wheel(
    alternative: str, tmp_path: Path
) -> None:
    """The mutation in the other direction, which is the dangerous one.

    Drop one artifact alternative and the same broken wheel, observed on a
    degrading link, becomes somebody else's network problem — a real release
    blocker excused as an alibi. Each artifact marker must be the sole reason
    its mixed log reads ``artifact``.
    """
    mixed = DEGRADED_TAIL + ARTIFACT_FIXTURES[alternative]
    assert _classify_with(_shipped_classifier(), mixed, tmp_path) == "artifact", alternative
    mutant = _without(_shipped_classifier(), "artifact_markers", alternative)
    assert _classify_with(mutant, mixed, tmp_path) == "network", alternative


# --------------------------------------------------------------------------
# 4. The docs are half the defect: keep the whole vocabulary taught.
# --------------------------------------------------------------------------


def test_the_operator_playbook_teaches_every_reason_the_runner_emits() -> None:
    """A reason code no document explains puts the operator back in the incident.

    ``artifact_install_failed`` was misreadable as "the artifact did not
    install" only because the playbook said so. The same binding has to hold
    for the whole vocabulary, not just for the one code this defect pass
    touched — otherwise the next reason code ships as a bare string an operator
    has to read the bash to understand.

    Non-vacuity first: the extraction must find a plausible number of reasons
    and must include the two the incident turns on. An empty extraction would
    make the loop below trivially green.
    """
    emitted = set(REASON_CODE.findall(RUNNER.read_text(encoding="utf-8")))
    assert len(emitted) >= 10, f"reason-code extraction found only {sorted(emitted)}"
    assert {"artifact_install_failed", "box_network_unreachable"} <= emitted, sorted(emitted)
    taught = PLAYBOOK.read_text(encoding="utf-8")
    untaught = sorted(reason for reason in emitted if reason not in taught)
    assert not untaught, f"{PLAYBOOK.name} explains no such reason: {untaught}"
