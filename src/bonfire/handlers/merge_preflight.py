# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Verifier pipeline stage handler -- pre-merge full-suite pytest.

Runs full-suite pytest against a simulated merged tip BEFORE
``gh pr merge``. Detects cross-wave interactions between sibling PRs
(e.g. the historical enum-widening incident where two independently-
green PRs broke each other on merge).

Design summary:
    - Module path: ``bonfire.handlers.merge_preflight``. Module-level
      ``ROLE: AgentRole = AgentRole.VERIFIER``. NOT in
      ``HANDLER_ROLE_MAP`` (deterministic handler bypasses
      gamified-display map).
    - 6-verdict deterministic classifier; first-match-wins ordering
      (collection-error -> green -> pre-existing-debt -> cross-wave
      -> pure-warrior-bug; merge-conflict produced by the handler
      shell, not the pure classifier).
    - Sibling-batch detection via
      ``client.list_open_prs(base, exclude=current_pr_number)``.
    - ``ALLOW-WITH-ANNOTATION`` path for pre-existing debt: classifier
      returns the verdict; handler downstream marks
      ``META_PREFLIGHT_TEST_DEBT_NOTED``.

The module exposes ``ROLE: AgentRole = AgentRole.VERIFIER`` for generic-
vocabulary discipline. Display translation (verifier -> "Cleric") happens
in the display layer via ``ROLE_DISPLAY[ROLE].gamified``; this module
never hardcodes the gamified name in code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from bonfire.agent.roles import AgentRole
from bonfire.handlers.preflight_pytest import (
    _PYTEST_STDOUT_TAIL_BYTES,
    FailingTest,
    PreflightClassification,
    PreflightVerdict,
    _extract_pr_number,
    _extract_verdict,
    _PytestResult,
    classify_pytest_run,
    parse_pytest_junit_xml,
    parse_pytest_stdout_fallback,
)
from bonfire.models.envelope import (
    META_PREFLIGHT_CLASSIFICATION,
    META_PREFLIGHT_TEST_DEBT_NOTED,
    ErrorDetail,
    TaskStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from bonfire.git.scratch import ScratchWorktreeFactory, ScratchWorktreeInfo
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.VERIFIER


# ---------------------------------------------------------------------------
# Pytest-parsing + classification layer (moved to a sibling leaf module).
#
# ``PreflightVerdict``, ``FailingTest``, ``PreflightClassification``,
# ``_PytestResult``, ``classify_pytest_run``, ``parse_pytest_junit_xml``,
# ``parse_pytest_stdout_fallback``, ``_extract_pr_number``, and
# ``_extract_verdict`` now live in ``bonfire.handlers.preflight_pytest`` and
# are re-exported via the top-of-module import so external callers/tests that
# import them from this module keep working unchanged. The shared
# ``_PYTEST_STDOUT_TAIL_BYTES`` budget is imported from there too.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Module-private metadata key constants. The cross-module ``META_PREFLIGHT_*``
# constants live in ``bonfire.models.envelope``; these are handler-internal
# (mirrors BardHandler ``_META_*`` style).
# ---------------------------------------------------------------------------

_META_PREFLIGHT_VERDICT: str = "preflight_verdict"
_META_PREFLIGHT_PR_NUMBER: str = "preflight_pr_number"
_SKIP_RESULT_TEMPLATE: str = "preflight: skipped (wizard verdict not approve)"

# Maximum number of failing-test entries retained in the classification
# result before truncation (Sage §D-CL.7 #6 envelope-size discipline). On
# overflow the live body appends a sentinel ``FailingTest`` whose
# ``file_path`` carries an overflow marker.
_FAILING_TESTS_LIMIT: int = 100
_FAILING_TESTS_OVERFLOW_PATH: str = "<overflow>"

# Filename of the JUnit XML emitted into the scratch worktree by pytest.
# Passed explicitly via ``--junit-xml=<path>`` to override any project
# pyproject.toml junit config (Sage §D-CL.7 #3 path-traversal safety).
_JUNIT_XML_FILENAME: str = "preflight-junit.xml"


# ---------------------------------------------------------------------------
# Sibling-batch detection (Sage §D5 lines 510-522)
# ---------------------------------------------------------------------------


async def detect_sibling_prs(
    client: Any,
    base: str,
    *,
    current_pr_number: int,
    sibling_detection: bool = True,
) -> tuple[dict[int, frozenset[str]], str]:
    """Detect open sibling PRs targeting ``base``, excluding ``current``.

    Calls ``client.list_open_prs(base, exclude=current_pr_number)`` and
    folds the response into ``{pr_number: frozenset(file_paths)}``. Sage
    §A Q5 lines 128-136 + §D5 lines 510-522.

    Status semantics (Sage §A Q4 line 105):
        - ``"skipped"`` -- caller passed ``sibling_detection=False`` at
          handler init (no API call made)
        - ``"ok"``      -- API returned a list (possibly empty)
        - ``"error"``   -- API raised RuntimeError or other Exception
                           (graceful degradation, classifier ignores
                           sibling data when status != "ok")
    """
    if not sibling_detection:
        return ({}, "skipped")

    try:
        prs = await client.list_open_prs(base, exclude=current_pr_number)
    except (RuntimeError, OSError):
        return ({}, "error")

    files_by_pr: dict[int, frozenset[str]] = {}
    for pr in prs:
        # PRSummary or compatible duck-type with .number + .file_paths.
        files_by_pr[pr.number] = frozenset(pr.file_paths)
    return (files_by_pr, "ok")


# ---------------------------------------------------------------------------
# Handler (Sage §D2)
# ---------------------------------------------------------------------------


class MergePreflightHandler:
    """Pipeline stage handler for the verifier role -- pre-merge pytest.

    Runs between Wizard approve and Steward merge. Creates a scratch
    worktree at ``origin/<base>``, applies the PR diff (and any open
    sibling PR diffs), runs pytest, classifies failures deterministically,
    and blocks merge on cross-wave interaction or pure-warrior-bug.

    NEVER raises -- :class:`StageHandler` Protocol contract
    (``protocols.py:195``). All exceptions in the handler body produce a
    FAILED envelope with structured :class:`ErrorDetail`.

    The ``handle()`` body covers the spine (PR-number extraction, Wizard
    verdict gate, sibling detection, scratch acquisition, classifier
    dispatch, result envelope construction). The full git-apply /
    pytest-invocation / JUnit-parse pipeline lives in
    :py:meth:`_classify_preflight_run` plus the three private helpers
    :py:meth:`_apply_diff_to_worktree`, :py:meth:`_run_pytest_in_worktree`,
    and :py:meth:`_get_baseline_failures`. End-to-end behaviour is
    exercised in :file:`tests/integration/test_merge_preflight_pipeline.py`
    via canned handlers; the unit-level classifier surface is exercised
    in :file:`tests/unit/test_merge_preflight_handler.py` directly
    against :py:func:`classify_pytest_run` (pure function).
    """

    def __init__(
        self,
        *,
        github_client: Any,
        scratch_worktree_factory: ScratchWorktreeFactory | Any,
        repo_path: Path,
        base_branch: str = "main",
        pytest_command: tuple[str, ...] = ("pytest", "tests/"),
        pytest_timeout_seconds: int | None = 600,
        sibling_detection: bool = True,
        baseline_cache: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._github_client = github_client
        self._scratch_factory = scratch_worktree_factory
        self._repo_path = repo_path
        self._base_branch = base_branch
        self._pytest_command = pytest_command
        self._pytest_timeout_seconds = pytest_timeout_seconds
        self._sibling_detection = sibling_detection
        self._baseline_cache = baseline_cache if baseline_cache is not None else {}

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Route the pre-merge full-suite pytest stage.

        Outer try/except wraps the entire body (mirror BardHandler line 254).
        Any uncaught exception returns a FAILED envelope.
        """
        try:
            # Step 1: PR-number extraction (Steward-mirror chain).
            pr_number = _extract_pr_number(prior_results, envelope)
            if pr_number is None:
                return envelope.with_error(
                    ErrorDetail(
                        error_type="ValueError",
                        message=("No PR number found in prior_results or envelope metadata"),
                        stage_name=stage.name,
                    ),
                )

            # Step 2: Wizard verdict gate (mirror Wizard's verdict handling).
            verdict = _extract_verdict(prior_results)
            if verdict != "approve":
                return envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            _META_PREFLIGHT_PR_NUMBER: str(pr_number),
                        },
                        "status": TaskStatus.COMPLETED,
                        "result": _SKIP_RESULT_TEMPLATE,
                    },
                )

            # Step 3: Sibling-batch detection (Sage §D2 line 272 + §D5
            # lines 510-522). Performed BEFORE scratch acquire so the
            # sibling file-set is in hand when diffs are applied.
            sibling_files, sibling_status = await detect_sibling_prs(
                self._github_client,
                self._base_branch,
                current_pr_number=pr_number,
                sibling_detection=self._sibling_detection,
            )

            # Step 4: Acquire scratch worktree (try/finally guarantee
            # via async-with). Sage §D2 line 273.
            ctx = self._scratch_factory.acquire(
                self._base_branch,
                pr_number=pr_number,
            )
            async with ctx as info:
                # Steps 5-10: Apply current PR diff, apply sibling diffs,
                # run pytest, parse, classify. Sage §D2 lines 273-291.
                classification = await self._classify_preflight_run(
                    info=info,
                    pr_number=pr_number,
                    sibling_files=sibling_files,
                    sibling_status=sibling_status,
                )

                # Step 11: Build result envelope per the verdict.
                return self._build_result_envelope(
                    envelope=envelope,
                    classification=classification,
                    stage=stage,
                    pr_number=pr_number,
                )

        except Exception as exc:  # noqa: BLE001
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    stage_name=stage.name,
                ),
            )

    # -- algorithm-body steps (private) -----------------------------------

    async def _classify_preflight_run(
        self,
        *,
        info: ScratchWorktreeInfo,
        pr_number: int,
        sibling_files: dict[int, frozenset[str]],
        sibling_status: Literal["ok", "skipped", "error"],
    ) -> PreflightClassification:
        """Live body: apply diff, run pytest, classify.

        Supersedes the prior v0.1 stub that returned GREEN unconditionally;
        this method now drives the full subprocess pipeline (current PR
        diff -> sibling diffs -> pytest -> JUnit parse -> baseline cache
        -> deterministic classifier).

        Step ordering mirrors the §D2 pseudocode exactly:
            5. Apply current PR diff in scratch (``git apply --3way``).
            6. Apply sibling-batch diffs in ascending PR-number order
               (Sage §D-CL.7 #4: later PR's diff takes precedence on
               conflict via ``--3way``).
            7. Run pytest with ``--junit-xml=<known-path>`` (§D-CL.7 #3).
            8. Parse failures from JUnit XML; fall back to stdout regex
               if XML is empty AND returncode != 0.
            9. Compute / cache baseline failures on ``origin/<base>``.
           10. Call :py:func:`classify_pytest_run` (Warrior B's pure fn).

        Envelope-size discipline (§D-CL.7 #6):
            - ``pytest_stdout_tail`` is truncated to 2KB.
            - ``failing_tests`` is truncated to 100 entries; on overflow
              a sentinel ``FailingTest`` with ``file_path='<overflow>'``
              is appended so downstream forensics can detect truncation.

        Path-guard discipline (§D-CL.7 #7): error messages name PRs by
        number and never embed the absolute scratch worktree path.

        Subprocess discipline (§D-CL.7 #8): all invocations use
        ``asyncio.create_subprocess_exec`` with ``tuple[str, ...]`` args;
        no shell interpolation anywhere in the chain.
        """
        # Step 5: apply current PR's diff. Exceptions from get_pr_diff
        # propagate to handle()'s outer try/except; apply failures
        # downgrade to a MERGE_CONFLICT verdict (no raise).
        diff_text = await self._github_client.get_pr_diff(pr_number)
        try:
            await self._apply_diff_to_worktree(diff_text, info.path)
        except RuntimeError as exc:
            return PreflightClassification(
                verdict=PreflightVerdict.MERGE_CONFLICT,
                failing_tests=(),
                sibling_pr_numbers=tuple(sorted(sibling_files.keys())),
                sibling_detection_status=sibling_status,
                pytest_returncode=-1,
                pytest_duration_seconds=0.0,
                pytest_stdout_tail=(f"git apply --3way failed for PR #{pr_number}: {exc}")[
                    :_PYTEST_STDOUT_TAIL_BYTES
                ],
            )

        # Step 6: apply each sibling's diff in ascending PR-number order
        # (Sage §D-CL.7 #4: deterministic ordering, later PR wins on
        # conflict via ``--3way``). Sibling-fetch errors are logged + skipped
        # (graceful degradation -- a transient gh failure should NOT block
        # the whole preflight). Sibling-apply failures DO produce a
        # MERGE_CONFLICT verdict naming the offending PR.
        for sibling_pr_n in sorted(sibling_files.keys()):
            try:
                sibling_diff = await self._github_client.get_pr_diff(
                    sibling_pr_n,
                )
            except (RuntimeError, OSError):
                logger.warning(
                    "merge_preflight.sibling_diff_fetch_failed pr=%d",
                    sibling_pr_n,
                )
                continue

            try:
                await self._apply_diff_to_worktree(sibling_diff, info.path)
            except RuntimeError as exc:
                return PreflightClassification(
                    verdict=PreflightVerdict.MERGE_CONFLICT,
                    failing_tests=(),
                    sibling_pr_numbers=tuple(sorted(sibling_files.keys())),
                    sibling_detection_status=sibling_status,
                    pytest_returncode=-1,
                    pytest_duration_seconds=0.0,
                    pytest_stdout_tail=(
                        f"git apply --3way failed for sibling PR #{sibling_pr_n}: {exc}"
                    )[:_PYTEST_STDOUT_TAIL_BYTES],
                )

        # Step 7: run pytest in scratch worktree.
        result = await self._run_pytest_in_worktree(info.path)

        # Step 8: parse failures from JUnit XML; fall back to stdout regex
        # only when the XML yielded nothing AND pytest exited non-zero.
        failing = parse_pytest_junit_xml(result.junit_xml_path)
        if not failing and result.returncode != 0:
            failing = parse_pytest_stdout_fallback(result.stdout_tail)

        # Envelope-size bound (Sage §D-CL.7 #6): truncate failing_tests
        # to 100 entries; append an overflow sentinel so forensics see it.
        if len(failing) > _FAILING_TESTS_LIMIT:
            failing = (
                *failing[:_FAILING_TESTS_LIMIT],
                FailingTest(file_path=_FAILING_TESTS_OVERFLOW_PATH),
            )

        # Step 9: baseline failures on origin/<base> (cached).
        baseline = await self._get_baseline_failures(info.base_sha)

        # Step 10: deterministic classification (Warrior B pure function).
        # Sage §A Q4 lines 79-122. ``pytest_stdout`` is already 2KB-tail
        # bounded inside _run_pytest_in_worktree.
        return classify_pytest_run(
            failing_tests=failing,
            sibling_files=sibling_files,
            baseline_failures=baseline,
            sibling_detection_status=sibling_status,
            pytest_returncode=result.returncode,
            pytest_duration_seconds=result.duration_seconds,
            pytest_stdout=result.stdout_tail,
        )

    async def _apply_diff_to_worktree(
        self,
        diff_text: str,
        worktree_path: Path,
    ) -> None:
        """Apply *diff_text* to *worktree_path* via ``git apply --3way``.

        Sage §D2 line 275 + §D-CL.7 #8 (no shell, args as tuple) +
        §D-CL.7 #4 (``--3way`` lets later PRs win on textual conflict).
        Diff content is piped via stdin; we never write a temporary file
        on disk. Empty diff is a no-op (git apply with empty stdin returns
        zero).

        Raises ``RuntimeError`` on non-zero git exit. Error message names
        only the worktree's basename to honour §D-CL.7 #7 (no absolute
        paths in error messages).
        """
        proc = await asyncio.create_subprocess_exec(
            *(
                "git",
                "-C",
                str(worktree_path),
                "apply",
                "--3way",
                "-",
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=diff_text.encode("utf-8"))
        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            # Truncate stderr so a verbose 3-way conflict message does not
            # blow the envelope budget (§D-CL.7 #6). Path-guard (§D-CL.7
            # #7): we name only the basename of the worktree.
            tail = stderr_text[:512]
            raise RuntimeError(
                f"git apply --3way failed (exit {proc.returncode}) "
                f"in scratch '{worktree_path.name}': {tail}",
            )

    async def _run_pytest_in_worktree(
        self,
        worktree_path: Path,
    ) -> _PytestResult:
        """Run pytest inside *worktree_path*; return a :class:`_PytestResult`.

        Sage §D2 lines 279-280 + §D-CL.7 #2/#3/#8.

        Subprocess discipline:
            - Args built as a ``tuple[str, ...]``; never a shell string
              (§D-CL.7 #8).
            - Explicit ``--junit-xml=<known-path>`` overrides any project
              pyproject.toml junit setting (§D-CL.7 #3).
            - On ``asyncio.TimeoutError`` we call ``proc.kill()`` AND
              ``await proc.wait()`` before returning so the kernel
              releases the pid before the worktree is torn down
              (§D-CL.7 #2 resource-leak discipline).

        On timeout the result is shaped to drive the classifier into
        ``PYTEST_COLLECTION_ERROR`` (returncode=-1, no failing_tests).
        """
        junit_xml_path = worktree_path / _JUNIT_XML_FILENAME

        # ``self._pytest_command`` already begins with "pytest" by default
        # (see __init__). We append the junit + quiet flags as additional
        # args; tuple concatenation keeps argv as ``tuple[str, ...]`` per
        # §D-CL.7 #8 ("never as a single shell string").
        pytest_args: tuple[str, ...] = (
            *self._pytest_command,
            f"--junit-xml={junit_xml_path}",
            "--no-header",
            "-q",
        )

        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *pytest_args,
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timeout = self._pytest_timeout_seconds
        try:
            if timeout is not None:
                stdout_b, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            else:
                stdout_b, _ = await proc.communicate()
        except TimeoutError:
            # §D-CL.7 #2: actively kill + reap before the worktree is
            # torn down so the process holds no FDs into the scratch.
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            elapsed = time.monotonic() - start
            return _PytestResult(
                returncode=-1,
                duration_seconds=elapsed,
                stdout_tail="pytest timed out",
                junit_xml_path=junit_xml_path,
            )

        elapsed = time.monotonic() - start
        stdout_text = stdout_b.decode("utf-8", errors="replace")
        # Tail-truncate to envelope-size budget (§D-CL.7 #6).
        stdout_tail = stdout_text[-_PYTEST_STDOUT_TAIL_BYTES:]
        return _PytestResult(
            returncode=proc.returncode if proc.returncode is not None else -1,
            duration_seconds=elapsed,
            stdout_tail=stdout_tail,
            junit_xml_path=junit_xml_path,
        )

    async def _get_baseline_failures(
        self,
        base_sha: str,
    ) -> frozenset[str]:
        """Return cached baseline failures on ``origin/<base>``; compute on miss.

        Sage §D2 line 281 + §A Q7 line 165 ("one-time amortization").
        On miss we acquire a SECOND scratch worktree at the base ref (NO
        PR diff applied), run pytest there, and intersect the failing
        test file paths into a frozenset. The result is cached on
        ``self._baseline_cache`` keyed by ``base_sha`` so subsequent
        preflights in the same session reuse the work.

        Failures during baseline computation degrade to an empty
        frozenset (the classifier then cannot classify any failure as
        PRE_EXISTING_DEBT, which is the safe default -- pure-Warrior bug
        is the harsher verdict).
        """
        cached = self._baseline_cache.get(base_sha)
        if cached is not None:
            return cached

        try:
            ctx = self._scratch_factory.acquire(
                self._base_branch,
                pr_number=None,
                prefix="baseline",
            )
            async with ctx as baseline_info:
                result = await self._run_pytest_in_worktree(baseline_info.path)
                failing = parse_pytest_junit_xml(result.junit_xml_path)
                if not failing and result.returncode != 0:
                    failing = parse_pytest_stdout_fallback(result.stdout_tail)
                baseline = frozenset(ft.file_path for ft in failing)
        except Exception:  # noqa: BLE001
            logger.warning(
                "merge_preflight.baseline_compute_failed base_sha=%s",
                base_sha[:12],
            )
            baseline = frozenset()

        self._baseline_cache[base_sha] = baseline
        return baseline

    def _build_result_envelope(
        self,
        *,
        envelope: Envelope,
        classification: PreflightClassification,
        stage: StageSpec,
        pr_number: int,
    ) -> Envelope:
        """Convert a :class:`PreflightClassification` into a result envelope.

        Routes all six verdicts per Sage §D2 lines 285-291 + §A Q6
        ALLOW-WITH-ANNOTATION (line 156, ratified):

            - GREEN
                -> COMPLETED, ``result="preflight: PASSED ..."``,
                   metadata[META_PREFLIGHT_CLASSIFICATION]=verdict-value
            - PRE_EXISTING_DEBT
                -> COMPLETED with ``META_PREFLIGHT_TEST_DEBT_NOTED=True``
                   + ``META_PREFLIGHT_CLASSIFICATION``; pipeline proceeds
                   to Steward (Q6 ALLOW-WITH-ANNOTATION)
            - CROSS_WAVE_INTERACTION
                -> FAILED, ErrorDetail(error_type="cross_wave_interaction")
            - PURE_WARRIOR_BUG
                -> FAILED, ErrorDetail(error_type="pure_warrior_bug")
            - PYTEST_COLLECTION_ERROR
                -> FAILED, ErrorDetail(error_type="pytest_collection_error")
            - MERGE_CONFLICT
                -> FAILED, ErrorDetail(error_type="merge_conflict")
        """
        verdict = classification.verdict
        new_metadata: dict[str, Any] = {
            **envelope.metadata,
            _META_PREFLIGHT_PR_NUMBER: str(pr_number),
            _META_PREFLIGHT_VERDICT: verdict.value,
            META_PREFLIGHT_CLASSIFICATION: verdict.value,
        }

        if verdict == PreflightVerdict.GREEN:
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": (
                        f"preflight: PASSED "
                        f"({len(classification.failing_tests)} failing, "
                        f"{classification.pytest_duration_seconds:.2f}s)"
                    ),
                },
            )

        if verdict == PreflightVerdict.PRE_EXISTING_DEBT:
            new_metadata[META_PREFLIGHT_TEST_DEBT_NOTED] = True
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": (
                        f"preflight: PASSED with debt "
                        f"({len(classification.failing_tests)} pre-existing failures)"
                    ),
                },
            )

        # All four blocking verdicts share the same FAILED envelope shape;
        # the error_type literal differs per Sage §D2 lines 287-289.
        message_map: dict[PreflightVerdict, str] = {
            PreflightVerdict.CROSS_WAVE_INTERACTION: (
                "Cross-wave interaction detected with "
                f"PRs {classification.sibling_pr_numbers}. "
                "Run reconciliation lane or close one PR + re-run."
            ),
            PreflightVerdict.PURE_WARRIOR_BUG: (
                "preflight blocks merge: pure-Warrior bug; re-run Warrior cycle"
            ),
            PreflightVerdict.PYTEST_COLLECTION_ERROR: (
                "preflight blocks merge: pytest collection error "
                f"(rc={classification.pytest_returncode})"
            ),
            PreflightVerdict.MERGE_CONFLICT: (
                "preflight blocks merge: PR diff did not apply cleanly to base"
            ),
        }
        message = message_map.get(verdict, f"preflight: {verdict.value}")

        return envelope.model_copy(
            update={
                "metadata": new_metadata,
                "error": ErrorDetail(
                    error_type=verdict.value,
                    message=message,
                    stage_name=stage.name,
                ),
                "status": TaskStatus.FAILED,
            },
        )


# ---------------------------------------------------------------------------
# Public exports (Sage §D1 lines 200-208)
# ---------------------------------------------------------------------------


__all__ = [
    "FailingTest",
    "MergePreflightHandler",
    "PreflightClassification",
    "PreflightVerdict",
    "ROLE",
    # Algorithmic surface (Knight B tests imports).
    "classify_pytest_run",
    "detect_sibling_prs",
    "parse_pytest_junit_xml",
    "parse_pytest_stdout_fallback",
]
