"""Workflow plan models — DAG-validated, frozen Pydantic v2 models.

All models are frozen (immutable). WorkflowPlan validates its stage DAG
at construction time: duplicate names, dangling references, self-bounces,
and cycles are rejected with descriptive error messages including cycle paths.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class WorkflowType(StrEnum):
    """Supported workflow execution patterns."""

    STANDARD = "standard"
    SINGLE = "single"
    RESEARCH = "research"
    DEBUG = "debug"
    CUSTOM = "custom"


class GateContext(BaseModel):
    """Immutable context passed to gate evaluation functions."""

    model_config = ConfigDict(frozen=True)

    pipeline_cost_usd: float
    prior_results: dict[str, str] = Field(default_factory=dict)


class GateResult(BaseModel):
    """Immutable result from a gate evaluation."""

    model_config = ConfigDict(frozen=True)

    gate_name: str
    passed: bool
    severity: str
    message: str = ""


class StageSpec(BaseModel):
    """Immutable specification for a single pipeline stage."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str
    agent_name: str = Field(validation_alias=AliasChoices("agent", "agent_name"))
    role: str = ""
    handler_name: str | None = None
    gates: list[str] = Field(default_factory=list)
    on_gate_failure: str | None = None
    parallel_group: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    max_iterations: int = 1
    model_override: str | None = Field(
        default=None, validation_alias=AliasChoices("model", "model_override")
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowPlan(BaseModel):
    """Immutable, DAG-validated workflow plan.

    Construction fails if:
    - stages is empty (except for WorkflowType.SINGLE)
    - duplicate stage names exist
    - depends_on or on_gate_failure references an unknown stage
    - self-bounce: depends_on or on_gate_failure pointing to self
    - the combined dependency graph (depends_on + on_gate_failure) contains a cycle
      Error messages include the exact cycle path: A -> B -> C -> A.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str = Field(validation_alias=AliasChoices("name", "task"))
    workflow_type: WorkflowType
    stages: list[StageSpec] = Field(default_factory=list)
    budget_usd: float = 10.0
    description: str = ""
    task_description: str = ""

    @model_validator(mode="after")
    def _validate_dag(self) -> WorkflowPlan:
        """Ensure the stage graph is a valid DAG."""
        if not self.stages:
            if self.workflow_type == WorkflowType.SINGLE:
                return self
            raise ValueError("stages must not be empty")

        stage_names: set[str] = set()

        # -- 1. Unique names --
        for stage in self.stages:
            if stage.name in stage_names:
                raise ValueError(
                    f"Duplicate stage name: '{stage.name}'. "
                    "All stage names must be unique within a workflow plan."
                )
            stage_names.add(stage.name)

        # -- 2. Dangling references --
        for stage in self.stages:
            for dep in stage.depends_on:
                if dep not in stage_names:
                    raise ValueError(
                        f"Stage '{stage.name}' depends_on unknown stage '{dep}'. "
                        f"Known stages: {sorted(stage_names)}"
                    )
            if stage.on_gate_failure and stage.on_gate_failure not in stage_names:
                raise ValueError(
                    f"Stage '{stage.name}' on_gate_failure references unknown stage "
                    f"'{stage.on_gate_failure}'. Known stages: {sorted(stage_names)}"
                )

        # -- 3. Self-bounce detection --
        for stage in self.stages:
            if stage.name in stage.depends_on:
                raise ValueError(
                    f"Stage '{stage.name}' has a self-dependency (self-bounce). "
                    "A stage cannot depend on itself."
                )
            if stage.on_gate_failure == stage.name:
                raise ValueError(
                    f"Stage '{stage.name}' has on_gate_failure pointing to itself "
                    "(self-bounce). A stage cannot be its own failure fallback."
                )

        # -- 4. Cycle detection (combined graph: depends_on + on_gate_failure) --
        adjacency: dict[str, list[str]] = {s.name: [] for s in self.stages}
        for stage in self.stages:
            for dep in stage.depends_on:
                adjacency[stage.name].append(dep)
            if stage.on_gate_failure and stage.on_gate_failure != stage.name:
                adjacency[stage.name].append(stage.on_gate_failure)

        white, gray, black = 0, 1, 2
        color: dict[str, int] = {name: white for name in stage_names}
        parent: dict[str, str | None] = {name: None for name in stage_names}

        def _dfs(node: str) -> list[str] | None:
            """Return the cycle path if found, else None."""
            color[node] = gray
            for neighbor in adjacency[node]:
                if color[neighbor] == gray:
                    # Reconstruct cycle path
                    cycle = [neighbor, node]
                    current = node
                    while parent[current] is not None and parent[current] != neighbor:
                        current = parent[current]  # type: ignore[assignment]
                        cycle.append(current)
                    cycle.reverse()
                    cycle.append(neighbor)  # close the cycle
                    return cycle
                if color[neighbor] == white:
                    parent[neighbor] = node
                    result = _dfs(neighbor)
                    if result is not None:
                        return result
            color[node] = black
            return None

        for name in stage_names:
            if color[name] == white:
                cycle = _dfs(name)
                if cycle is not None:
                    path_str = " \u2192 ".join(cycle)
                    raise ValueError(
                        f"Cycle detected in workflow DAG: {path_str}. "
                        "Workflows must form a directed acyclic graph."
                    )

        return self

    def describe(self) -> str:
        """Return a human-readable summary of this workflow plan."""
        lines: list[str] = []
        lines.append(f"Workflow: {self.name} ({self.workflow_type.value})")
        if self.task_description:
            lines.append(f"  Task: {self.task_description}")
        if self.description:
            lines.append(f"  {self.description}")
        lines.append(f"  Budget: ${self.budget_usd:.2f}")
        lines.append(f"  Stages ({len(self.stages)}):")
        for stage in self.stages:
            parts = [f"    {stage.name}"]
            if stage.depends_on:
                deps = ", ".join(stage.depends_on)
                parts.append(f"\u2190 {deps}")
            if stage.on_gate_failure:
                parts.append(f"(fail \u2192 {stage.on_gate_failure})")
            if stage.parallel_group:
                parts.append(f"[group: {stage.parallel_group}]")
            lines.append(" ".join(parts))
        return "\n".join(lines)
