"""Publisher pipeline stage handler (gamified display: Bard).

Creates feature branches, stages listed artifacts, commits, verifies the
commit introduced a real diff against base, pushes, and opens pull requests.

Contract preserved from the reference implementation:

  - Stages only files from ``envelope.artifacts`` (type-filtered); empty
    artifact list -> FAILED envelope before any git call.
  - Branch slug capped at 40 chars + 12-hex envelope_id suffix;
    ``GitWorkflow.create_branch`` owns the ``bonfire/`` auto-prefix.
  - Post-commit SHA is compared to the base SHA captured at handler entry;
    equality -> FAILED with ``error_type="no_diff_after_commit"``.
  - ``TaskStatus.COMPLETED`` enum identity is the only success marker.

Not a retry-wrapped LLM dispatcher: this handler has no ``.execute`` method
and dispatches no sub-agent. Stage-iteration retry (via
``StageSpec.max_iterations``) is the only retry layer.

The module exposes ``ROLE: AgentRole = AgentRole.PUBLISHER`` for generic-
vocabulary discipline. Display translation (publisher -> "Bard") happens in
the display layer via ``ROLE_DISPLAY[ROLE].gamified``; this module never
hardcodes the gamified name in code.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_PR_URL,
    ErrorDetail,
    TaskStatus,
)

if TYPE_CHECKING:
    from bonfire.models.config import PipelineConfig
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec

# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.PUBLISHER

# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

_SLUG_MAX_LEN: int = 40
_SLUG_ID_LEN: int = 12
_SLUG_RE: re.Pattern[str] = re.compile(r"[^a-z0-9]+")
_SLUG_FALLBACK: str = "task"

_FILE_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {"file_written", "file_modified"},
)

# Metadata keys. When the authoritative META_* constants land in
# ``bonfire.models.envelope`` they will hold these exact string values,
# which makes the xfail'd tests flip GREEN automatically.
_META_BRANCH: str = "bard_branch"
_META_BASE_SHA: str = "bard_base_sha"
_META_COMMIT_SHA: str = "bard_commit_sha"
_META_STAGED_FILES: str = "bard_staged_files"
_META_STAGING_FAILURE_REASON: str = "bard_staging_failure_reason"


# ---------------------------------------------------------------------------
# Module-scope helpers
# ---------------------------------------------------------------------------


def _slugify_task(task: str, envelope_id: str) -> str:
    """Build a deterministic, collision-resistant branch slug.

    Pure (no I/O, no ``self``). Final length bound:
    ``_SLUG_MAX_LEN + 1 + _SLUG_ID_LEN`` = 53 chars. Empty-after-sanitization
    falls back to ``_SLUG_FALLBACK`` ("task") so the slug never begins with
    the id suffix alone.
    """
    sanitized = _SLUG_RE.sub("-", task.lower()).strip("-")
    truncated = sanitized[:_SLUG_MAX_LEN].rstrip("-")
    if not truncated:
        truncated = _SLUG_FALLBACK
    return f"{truncated}-{envelope_id[:_SLUG_ID_LEN]}"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class BardHandler:
    """Pipeline stage handler for the publisher role.

    Stages typed artifacts from the envelope, opens a feature branch,
    commits with a diff check, pushes, and opens a pull request. Not an
    LLM caller.
    """

    def __init__(
        self,
        *,
        git_workflow: Any,
        github_client: Any,
        base_branch: str = "master",
        config: PipelineConfig | None = None,
    ) -> None:
        self._git_workflow = git_workflow
        self._github_client = github_client
        self._base_branch = base_branch
        # ``config`` is accepted and stored but not yet consumed by the
        # handler body: it is held so future policy (retry caps, PR
        # templating) can read it without a constructor churn.
        self._config = config

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Stage artifacts, open a branch, commit with a diff check, and PR it."""
        base_sha: str | None = None
        branch_name: str | None = None
        commit_sha: str | None = None
        staged_paths: list[str] = []

        try:
            # 1. Derive staged paths from typed artifacts.
            staged_paths = [
                a.name for a in envelope.artifacts if a.artifact_type in _FILE_ARTIFACT_TYPES
            ]

            # 2. Empty-artifacts precondition: fail BEFORE any git call.
            if not staged_paths:
                return envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            _META_STAGING_FAILURE_REASON: "empty_artifacts",
                        },
                        "error": ErrorDetail(
                            error_type="empty_artifacts",
                            message=(
                                "BardHandler refused to commit: envelope.artifacts "
                                "contains no file_written/file_modified entries. "
                                f"envelope_id={envelope.envelope_id}, stage={stage.name}."
                            ),
                            stage_name=stage.name,
                        ),
                        "status": TaskStatus.FAILED,
                    },
                )

            # 3. Capture base SHA at entry -- before any branch-moving operation.
            base_sha = await self._git_workflow.rev_parse(self._base_branch)

            # 4. Build branch name (no leading "bonfire/" -- create_branch adds it).
            branch_name = f"{stage.name}/{_slugify_task(envelope.task, envelope.envelope_id)}"

            # 5. Create branch; structured error on collision.
            try:
                await self._git_workflow.create_branch(branch_name)
            except RuntimeError as branch_exc:
                if "already exists" in str(branch_exc):
                    return envelope.model_copy(
                        update={
                            "metadata": {
                                **envelope.metadata,
                                _META_BRANCH: branch_name,
                                _META_BASE_SHA: base_sha,
                                _META_STAGING_FAILURE_REASON: "branch_collision",
                            },
                            "error": ErrorDetail(
                                error_type="branch_collision",
                                message=(
                                    f"Branch {branch_name!r} already exists; "
                                    "refusing to rewrite history."
                                ),
                                stage_name=stage.name,
                            ),
                            "status": TaskStatus.FAILED,
                        },
                    )
                raise

            # 6. Stage + commit. Returns full HEAD SHA.
            commit_sha = await self._git_workflow.commit(
                envelope.task,
                paths=staged_paths,
            )

            # 7. Post-commit assert: did the commit actually introduce a diff?
            if commit_sha == base_sha:
                return envelope.model_copy(
                    update={
                        "metadata": {
                            **envelope.metadata,
                            _META_BRANCH: branch_name,
                            _META_BASE_SHA: base_sha,
                            _META_COMMIT_SHA: commit_sha,
                            _META_STAGED_FILES: json.dumps(staged_paths),
                            _META_STAGING_FAILURE_REASON: "no_diff_after_commit",
                        },
                        "error": ErrorDetail(
                            error_type="no_diff_after_commit",
                            message=(
                                f"BardHandler detected phantom commit: HEAD SHA "
                                f"{commit_sha} equals base ({self._base_branch}) "
                                f"SHA {base_sha}. No changes were introduced -- "
                                "refusing to push or open PR."
                            ),
                            stage_name=stage.name,
                        ),
                        "status": TaskStatus.FAILED,
                    },
                )

            # 8. Push (keyword-only branch arg -- GitWorkflow.push signature).
            await self._git_workflow.push(branch=branch_name)

            # 9. Open PR.
            pr_info = await self._github_client.create_pr(
                envelope.task,
                branch_name,
                self._base_branch,
            )

            # 10. Happy-path envelope.
            new_metadata = {
                **envelope.metadata,
                _META_BRANCH: branch_name,
                _META_BASE_SHA: base_sha,
                _META_COMMIT_SHA: commit_sha,
                _META_STAGED_FILES: json.dumps(staged_paths),
                META_PR_NUMBER: str(pr_info.number),
                META_PR_URL: pr_info.url,
            }
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": f"PR #{pr_info.number}: {pr_info.url}",
                },
            )

        except Exception as exc:
            partial_metadata: dict[str, Any] = {**envelope.metadata}
            if branch_name is not None:
                partial_metadata[_META_BRANCH] = branch_name
            if base_sha is not None:
                partial_metadata[_META_BASE_SHA] = base_sha
            if commit_sha is not None:
                partial_metadata[_META_COMMIT_SHA] = commit_sha
                partial_metadata[_META_STAGED_FILES] = json.dumps(staged_paths)
            return envelope.model_copy(
                update={
                    "metadata": partial_metadata,
                    "error": ErrorDetail(
                        error_type=type(exc).__name__,
                        message=str(exc),
                        stage_name=stage.name,
                    ),
                    "status": TaskStatus.FAILED,
                },
            )
