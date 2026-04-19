# BON-337 Sage Decision — Wave 4 (Unified)

**Date:** 2026-04-18
**Ticket:** BON-337 — Per-role tool allow-lists (W1.5.3 default floor + W4.1 seam)
**Sources:**
- `docs/audit/scouts/bon-337-scout-1-sdk-security.md` (SDK surface, 5-layer scoping, lockdown recipe)
- `docs/audit/scouts/bon-337-scout-2-polp.md` (PoLP threat model, 8-role profile table, failure modes)
- `docs/audit/scouts/bon-337-scout-3-bonfire-shape.md` (Bonfire terrain, `_compiler` blocker, mirror call sites)
- `docs/audit/sage-decisions/bon-334-sage-2026-04-18T19-14-42Z.md` §D3 (`_compiler` kwarg blocked)
- `docs/release-policy.md:41-43` (trust-triangle definition)

**Decoupling contract:**

> This ticket delivers the **allow-list floor** — a `ToolPolicy` protocol + `DefaultToolPolicy` implementation + role plumbing into `DispatchOptions.tools` — and nothing else. BON-337 **does not** touch any security hook, does not create a `bonfire/security/` subpackage, does not add any `Security*` event, does not define `SecurityHookConfig`, does not add `extra_deny_patterns`, does not add `HookMatcher` imports, does not define regex pattern catalogues, does not touch `sdk_backend.py`'s `hooks=` kwarg. BON-337's *entire* footprint at the SDK seam is two kwargs added side-by-side to the existing `ClaudeAgentOptions(...)` call: `tools=` (presence layer) and `allowed_tools=` (already present — reaffirmed). Knight, Warrior, Wizard, and Herald may review this ticket without reading BON-338. A revert of BON-337 deletes one new module + one new Pydantic field and leaves BON-338 (if merged) fully functional with `role=""` as the permissive default.

---

## 1. Canonical Decisions

### D1 — NEW MODULE: `src/bonfire/dispatch/tool_policy.py`

**Decision:** Create a new module inside the existing `bonfire.dispatch` subpackage. Module is a sibling of `sdk_backend.py`, `runner.py`, `result.py`, `tier.py`, `pydantic_ai_backend.py`. Do **NOT** create `src/bonfire/security/`. Co-locating with the dispatch seam honors Scout-3/337 §5's recommendation, avoids the "shared security package" gravity well Scout-3/338 proposed, and keeps BON-338 out of this ticket's footprint.

**Why:** Scout-3/337 §5 names `src/bonfire/dispatch/tool_policy.py` explicitly. The existing dispatch package already contains every file this policy interacts with. Adding one sibling file is a cleaner seam than introducing a new top-level subpackage.

**Lockdown:** The full absolute path is `/home/ishtar/Projects/bonfire-public/src/bonfire/dispatch/tool_policy.py`. No other location is permitted. The module must not import from `bonfire.security` (which does not exist) or reference `SecurityHookConfig` (which is BON-338 territory).

---

### D2 — `ToolPolicy` PROTOCOL (exact signature)

**Decision:** Define a single `@runtime_checkable Protocol` named `ToolPolicy` with one method: `tools_for(role: str) -> list[str]`.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ToolPolicy(Protocol):
    """Resolves a role name to its permitted tool list.

    Callers pass a role string (e.g. ``"scout"``, ``"warrior"``) and receive
    the list of SDK tool names that role is allowed to invoke. An empty list
    means "no tools permitted" (SDK interprets ``allowed_tools=[]`` as deny-all
    when combined with ``permission_mode='dontAsk'``).

    Implementations MUST be pure: the same role argument returns the same list
    across calls. Implementations MUST return a fresh list each call (callers
    may mutate).
    """

    def tools_for(self, role: str) -> list[str]: ...
```

**Why:** Scout-3/337 §5 — fresh dependency name avoids collision with Sage D3's `_compiler` lockout. `tools_for` (verb-noun) mirrors SDK vocabulary (`allowed_tools`). `@runtime_checkable` matches the existing `AgentBackend` / `VaultBackend` / `QualityGate` / `StageHandler` protocols in `protocols.py:104-194`.

**Lockdown:**
- Method name: `tools_for` — **not** `get_role_tools` (V1 name, Sage D3 blocks the V1 mechanism).
- Parameter name: `role: str` — free-form; does **not** use `AgentRole` enum. Scout-3/337 §1 confirms workflow factories emit gamified strings (`"scout"`, `"knight"`, ...) while `AgentRole` uses professional terms (`"researcher"`, `"tester"`, ...). Enum reconciliation is explicitly out of scope.
- Return type: `list[str]` — a new list each call. Not `Sequence[str]`, not `tuple[str, ...]`, not `frozenset[str]`. Dual Knights must match this exactly.

---

### D3 — `DefaultToolPolicy` IMPLEMENTATION + 8-role FLOOR MATRIX

**Decision:** Ship a concrete `DefaultToolPolicy` class with a hardcoded `dict[str, list[str]]` floor. The floor is the W1.5.3 "default allow-list floor" deliverable — non-overridable at this ticket's layer. W4.1 user override is a separate future concern, not BON-337 scope.

```python
class DefaultToolPolicy:
    """W1.5.3 default allow-list floor for Bonfire v0.1.

    Role strings match the gamified names emitted by workflow factories
    (workflows/standard.py, workflows/research.py). Unmapped roles return
    ``[]`` — SDK interprets empty ``allowed_tools`` combined with
    ``permission_mode='dontAsk'`` as deny-all.
    """

    _FLOOR: dict[str, list[str]] = {
        "scout":   ["Read", "Write", "Grep", "WebSearch", "WebFetch"],
        "knight":  ["Read", "Write", "Edit", "Grep", "Glob"],
        "warrior": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "prover":  ["Read", "Bash", "Grep", "Glob"],
        "sage":    ["Read", "Write", "Grep"],
        "bard":    ["Read", "Write", "Grep", "Glob"],
        "wizard":  ["Read", "Grep", "Glob"],
        "herald":  ["Read", "Grep"],
    }

    def tools_for(self, role: str) -> list[str]:
        return list(self._FLOOR.get(role, []))
```

**Why:** Values lifted verbatim from Scout-3/337 §4 floor matrix (scrubbed from private-V1 axiom frontmatter, cross-lane-clean per Scout-3/337 §6). These are the eight canonical roles documented in `src/bonfire/agent/roles.py:15-39` and consumed by `src/bonfire/workflows/standard.py:52-87`.

Scout-2/337 §4 documents the PoLP reasoning: per-tool scoping catches ~80% of excess-functionality paths at zero infrastructure cost. Scout-2/337 §5 validates each per-role tool choice against OWASP LLM06:2025.

**Lockdown:**
- Class name: `DefaultToolPolicy` — singular, no "v1"/"v01" suffix.
- Attribute: `_FLOOR` (class-level, underscore-prefix private, exactly this name).
- Eight keys exactly as above. Adding a ninth role is out of scope. Modifying values is out of scope. Dual Knights MUST assert each row byte-for-byte.
- `tools_for` returns `list(self._FLOOR.get(role, []))` — the `list(...)` wrap is load-bearing: callers must receive a fresh list, and missing-role default is an empty list, not `None`.
- **Bard's Bash omission is intentional** (Scout-3/337 §4 note). Bard's `gh` invocation is a future StageHandler concern, not this ticket. Bard gets `Write` so it can stage PR bodies via files; the handler (out of scope) will shell out to `gh` in-process.

---

### D4 — `DispatchOptions.role: str` — NEW FIELD

**Decision:** Add exactly one new field to the existing `DispatchOptions` Pydantic model in `src/bonfire/protocols.py`:

```python
role: str = ""
```

Default empty string. Not `Optional[str]`, not `None`. Preserves Scout-1/337 §7.3 discipline (frozen model, no accidental mutation).

**Why:** BON-337 needs a place where the role string travels from `StageSpec.role` through to `sdk_backend.py`. Scout-3/337 §5 considers three candidates (envelope.agent_name, options.tools, new field) and recommends a new explicit field — identical reasoning applies here. Adding it to `DispatchOptions` is the smallest-surface change that does not overload an existing semantic.

**Lockdown:**
- Field name: `role` (singular, lowercase). Not `agent_role`, not `stage_role`.
- Type: `str` (not `Literal[...]`, not enum). Values are the gamified strings the workflow factories already emit.
- Default: `""` (empty string). This is the "unset / backward-compat permissive" signal per the three-tier ratchet below (D6).
- Placement in `protocols.py`: immediately below the existing `tools` field (line 65 today). Add under the "Agent isolation" comment block. See File Manifest §2 for exact insertion line.
- This field does **NOT** validate against `AgentRole` enum. Enum reconciliation is a future ticket.

---

### D5 — CONSTRUCTOR KWARG: `tool_policy: ToolPolicy | None = None`

**Decision:** Add `tool_policy: ToolPolicy | None = None` to both `StageExecutor.__init__` and `PipelineEngine.__init__`. Default `None`. Store as `self._tool_policy`. Add `"_tool_policy"` to `StageExecutor.__slots__`.

**Why:** Scout-3/337 §5 confirms this satisfies Sage D3 (`test_rejects_compiler_kwarg` asserts `compiler=` specifically; `tool_policy=` is a different parameter name that does not collide). `None` default keeps backward compatibility with every existing caller in the codebase (executor fixture + pipeline fixture tests do not pass this kwarg; they must continue to pass).

**Lockdown:**
- Parameter name: `tool_policy` (snake_case). Not `toolPolicy`, not `policy`, not `role_policy`.
- Type hint: `ToolPolicy | None = None` — imported from `bonfire.dispatch.tool_policy`. Import MUST be gated behind `TYPE_CHECKING` to avoid a circular import when `dispatch.tool_policy` imports nothing from `engine.executor`.
- Attribute name: `self._tool_policy` (single underscore, matches existing `self._backend`, `self._bus` style).
- `__slots__` entry: `"_tool_policy"` — append alphabetically (executor.py:55-63: `"_backend", "_bus", "_config", "_context_builder", "_handlers", "_project_root", "_tool_policy", "_vault_advisor"`).
- `PipelineEngine` does not use `__slots__` today — just store `self._tool_policy = tool_policy`.

---

### D6 — THREE-TIER RATCHET at call site

**Decision:** Inside both `StageExecutor._dispatch_backend` (executor.py:255-271) and `PipelineEngine._execute_stage` backend branch (pipeline.py:486-504), compute `role_tools` using this exact ladder:

```python
if self._tool_policy is None or not stage.role:
    role_tools: list[str] = []
else:
    role_tools = self._tool_policy.tools_for(stage.role)
```

Then pass `tools=role_tools, role=stage.role` into `DispatchOptions(...)`.

**Why:** Per the pre-answered design question from the brief:
- No policy wired (`self._tool_policy is None`) → empty list → SDK permissive. Preserves current behavior for callers that have not opted in. Ensures every pre-existing test in the suite (which does not pass `tool_policy=`) stays green.
- Policy wired but `stage.role == ""` → empty list. Backward compat for stages that don't set a role.
- Policy wired + role set but unmapped in floor → `DefaultToolPolicy.tools_for` returns `[]` → SDK interprets as strict (paired with `dontAsk`, no tools permitted). Explicit policy + unknown role = deny-all. This is the "strict by default once opted in" pledge.
- Policy wired + role mapped → floor entry.

**Lockdown:**
- The guard clause is `self._tool_policy is None or not stage.role`. The `not stage.role` catches both `""` (current default) and any falsy corruption. Do NOT use `stage.role is None` (it's `str`, default `""`, never `None`).
- The variable name is `role_tools` (exact — matches both mirror sites, dual Warriors must not drift to `allowed`, `tools`, etc.).
- Do NOT attempt to deduplicate this logic into a helper — the two mirror sites at executor.py:255 and pipeline.py:486 are existing pre-Sage-D11 duplication, not BON-337's to refactor.

---

### D7 — `sdk_backend.py` CHANGES (belt-and-suspenders)

**Decision:** At `src/bonfire/dispatch/sdk_backend.py:99-110`, modify the `ClaudeAgentOptions(...)` call as follows:

```python
agent_options = ClaudeAgentOptions(
    model=options.model,
    max_turns=options.max_turns,
    max_budget_usd=options.max_budget_usd,
    cwd=options.cwd or None,
    permission_mode=options.permission_mode,
    tools=list(options.tools),          # NEW — PRESENCE layer
    allowed_tools=options.tools,        # UNCHANGED — APPROVAL layer
    setting_sources=["project"],
    thinking=thinking_config,
    effort=effort_level,
    stderr=lambda line: logger.warning("[CLI stderr] %s", line),
)
```

**Why:** Scout-1/337 §1 documents the SDK's 5-layer model. `tools` is the PRESENCE layer (removes the tool from Claude's tool-context entirely), `allowed_tools` is the APPROVAL layer (skips permission prompt). Today Bonfire only sets the latter; Scout-1/337 §7.3 recommends setting both ("belt and suspenders"). For empty lists, `tools=[]` is the SDK's hard kill-switch (Scout-1/337 §1 wire format). Combined with `permission_mode='dontAsk'` (already default), this yields deterministic deny-all for unmapped roles.

**Lockdown:**
- `tools=list(options.tools)` — use `list(...)` to produce a fresh list each call (SDK stores reference; defensive). The `DispatchOptions` model is frozen, so `options.tools` is immutable from Pydantic's side, but SDK code path may retain the reference.
- `allowed_tools=options.tools` — **unchanged**. Do not delete this line. Scout-1/337 §7.3 is explicit: both fields together form the correct lockdown.
- Order: `tools=` comes immediately before `allowed_tools=`. This is the one line BON-337 adds. BON-338 will add a `hooks=` kwarg elsewhere in the same call (immediately before `setting_sources=["project"]`); the two changes share the same constructor but add non-overlapping kwargs. Merge conflict is trivial and textual.

**`disallowed_tools` is NOT added in this ticket.** Scout-1/337 §7 floats it as a future nicety; release-policy §41-43 does not require it for the W1.5.3 floor. Defer to a follow-up (file as tech debt note, see §6).

---

### D8 — NO re-export of `ToolPolicy` from `protocols.py`

**Decision:** Do not add `ToolPolicy` to `bonfire.protocols.__all__`. Users import from `bonfire.dispatch.tool_policy`.

**Why:** `bonfire.protocols` is the extension-point home (`AgentBackend`, `VaultBackend`, `QualityGate`, `StageHandler`). `ToolPolicy` is a dispatch-layer concern, not a user-facing extension point for v0.1. Making it a named protocol in `bonfire.protocols` elevates it prematurely; W4.1 (user override) can promote it later if needed. This also keeps Scout-3/337's naming-conflict warning (private V1 `compiler.get_role_tools`) at maximum distance from `protocols.py`.

**Lockdown:** `bonfire.protocols.__all__` (protocols.py:29-36) is NOT modified by this ticket. `ToolPolicy` is imported as `from bonfire.dispatch.tool_policy import ToolPolicy, DefaultToolPolicy`.

---

## 2. File Manifest

### Created

| Path | Purpose |
|------|---------|
| `src/bonfire/dispatch/tool_policy.py` | `ToolPolicy` Protocol + `DefaultToolPolicy` implementation + `_FLOOR` matrix |
| `tests/unit/test_dispatch_tool_policy.py` | Unit tests for `ToolPolicy` protocol conformance + `DefaultToolPolicy` floor matrix + empty-role handling |

### Modified

| Path | Line range | Modification |
|------|-----------|--------------|
| `src/bonfire/protocols.py` | 65-67 | Insert `role: str = ""` field under "Agent isolation" comment block, after `permission_mode`. |
| `src/bonfire/engine/executor.py` | 55-63 | Add `"_tool_policy"` to `__slots__` (alphabetical between `_project_root` and `_vault_advisor`). |
| `src/bonfire/engine/executor.py` | 65-82 | Add `tool_policy: ToolPolicy | None = None` kwarg. Store as `self._tool_policy`. Add `TYPE_CHECKING` import of `ToolPolicy`. |
| `src/bonfire/engine/executor.py` | 255-271 | `_dispatch_backend` — compute `role_tools` via three-tier ratchet, pass `tools=role_tools, role=stage.role` into `DispatchOptions(...)`. |
| `src/bonfire/engine/pipeline.py` | 91-108 | Add `tool_policy: ToolPolicy | None = None` kwarg. Store as `self._tool_policy`. Add `TYPE_CHECKING` import of `ToolPolicy`. |
| `src/bonfire/engine/pipeline.py` | 486-504 | backend branch — same ratchet as executor, pass `tools=role_tools, role=spec.role`. |
| `src/bonfire/dispatch/sdk_backend.py` | 99-110 | Add `tools=list(options.tools)` kwarg to `ClaudeAgentOptions(...)` (immediately before existing `allowed_tools=options.tools`). |
| `tests/unit/test_engine_executor.py` | append | New test class `TestToolPolicyWiring` — see Knight Handoff §3. |
| `tests/unit/test_engine_pipeline.py` | append | New test class `TestToolPolicyWiring` — mirror of executor tests. |
| `tests/unit/test_dispatch_sdk_backend.py` | append | New test class `TestToolsKwargPropagation` — assert `tools=` reaches `ClaudeAgentOptions`. |

### NOT touched (verify no drift)

- `src/bonfire/security/` — does not exist, is NOT created by this ticket.
- `src/bonfire/models/events.py` — no new event added by this ticket.
- `src/bonfire/agent/roles.py` — `AgentRole` enum is NOT the policy key.
- `src/bonfire/handlers/*` — handler-dispatch path does not touch backend, not in scope.
- `src/bonfire/dispatch/pydantic_ai_backend.py` — alternate backend; protocol is structural, this backend ignores the new `role`/`tools` surface. No change required.

---

## 3. Knight Handoff — RED test contract

### 3.1 `tests/unit/test_dispatch_tool_policy.py` (NEW)

**Fixtures required:** none (pure unit tests).

**Required imports:**
```python
from bonfire.dispatch.tool_policy import DefaultToolPolicy, ToolPolicy
```

**Test scenarios:**

```python
class TestToolPolicyProtocol:
    def test_default_policy_satisfies_protocol(self) -> None:
        """``DefaultToolPolicy`` must structurally satisfy the ``ToolPolicy`` Protocol."""
        policy = DefaultToolPolicy()
        assert isinstance(policy, ToolPolicy)

    def test_protocol_is_runtime_checkable(self) -> None:
        """``ToolPolicy`` must be ``@runtime_checkable``."""
        # Duck type with a no-op class
        class _FakePolicy:
            def tools_for(self, role: str) -> list[str]:
                return []
        assert isinstance(_FakePolicy(), ToolPolicy)

    def test_protocol_rejects_missing_method(self) -> None:
        """Objects lacking ``tools_for`` MUST NOT satisfy the protocol."""
        class _NotAPolicy:
            def get_tools(self, role: str) -> list[str]:
                return []
        assert not isinstance(_NotAPolicy(), ToolPolicy)


class TestDefaultToolPolicyFloor:
    # Exact byte-for-byte assertions — D3 lockdown.
    def test_scout_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("scout") == [
            "Read", "Write", "Grep", "WebSearch", "WebFetch"
        ]

    def test_knight_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("knight") == [
            "Read", "Write", "Edit", "Grep", "Glob"
        ]

    def test_warrior_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("warrior") == [
            "Read", "Write", "Edit", "Bash", "Grep", "Glob"
        ]

    def test_prover_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("prover") == [
            "Read", "Bash", "Grep", "Glob"
        ]

    def test_sage_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("sage") == ["Read", "Write", "Grep"]

    def test_bard_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("bard") == ["Read", "Write", "Grep", "Glob"]

    def test_wizard_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("wizard") == ["Read", "Grep", "Glob"]

    def test_herald_floor(self) -> None:
        assert DefaultToolPolicy().tools_for("herald") == ["Read", "Grep"]


class TestDefaultToolPolicyEdges:
    def test_unknown_role_returns_empty(self) -> None:
        """Unmapped role MUST return an empty list (strict-once-opted-in)."""
        assert DefaultToolPolicy().tools_for("unknown_role") == []

    def test_empty_string_role_returns_empty(self) -> None:
        """Empty role string MUST return an empty list."""
        assert DefaultToolPolicy().tools_for("") == []

    def test_returns_fresh_list_each_call(self) -> None:
        """Caller must be safe to mutate; ``tools_for`` returns a new list every call."""
        policy = DefaultToolPolicy()
        a = policy.tools_for("scout")
        b = policy.tools_for("scout")
        assert a == b
        assert a is not b
        a.append("Bash")
        assert "Bash" not in policy.tools_for("scout")

    def test_case_sensitive(self) -> None:
        """Role lookup MUST be case-sensitive — ``"Scout"`` != ``"scout"``."""
        assert DefaultToolPolicy().tools_for("Scout") == []
        assert DefaultToolPolicy().tools_for("scout") != []
```

### 3.2 `tests/unit/test_engine_executor.py` — append

```python
class TestToolPolicyWiring:
    def test_default_tool_policy_none(self, bus: EventBus, config: PipelineConfig) -> None:
        """Constructor MUST accept no ``tool_policy`` kwarg and default to None."""
        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)
        assert ex._tool_policy is None

    def test_accepts_tool_policy_kwarg(self, bus: EventBus, config: PipelineConfig) -> None:
        """Constructor MUST accept ``tool_policy=`` kwarg."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        policy = DefaultToolPolicy()
        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, tool_policy=policy)
        assert ex._tool_policy is policy

    @pytest.mark.asyncio
    async def test_dispatch_passes_tools_from_policy(
        self, bus: EventBus, config: PipelineConfig, monkeypatch
    ) -> None:
        """When policy is wired + stage.role set, ``DispatchOptions.tools`` MUST be the floor list."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        captured: dict[str, object] = {}

        async def fake_execute_with_retry(backend, env, options, **kwargs):
            captured["options"] = options
            result = DispatchResult(envelope=env.with_result(result="ok", cost_usd=0.0))
            return result

        monkeypatch.setattr("bonfire.engine.executor.execute_with_retry", fake_execute_with_retry)

        policy = DefaultToolPolicy()
        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config, tool_policy=policy)
        stage = StageSpec(name="s", agent_name="warrior-agent", role="warrior")
        plan = _minimal_plan([stage])
        await ex.execute_single(stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="sid")

        opts = captured["options"]
        assert opts.tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts.role == "warrior"

    @pytest.mark.asyncio
    async def test_dispatch_permissive_when_policy_none(
        self, bus: EventBus, config: PipelineConfig, monkeypatch
    ) -> None:
        """Backward compat: no policy → empty tools → SDK permissive."""
        captured: dict[str, object] = {}

        async def fake_execute_with_retry(backend, env, options, **kwargs):
            captured["options"] = options
            return DispatchResult(envelope=env.with_result(result="ok", cost_usd=0.0))

        monkeypatch.setattr("bonfire.engine.executor.execute_with_retry", fake_execute_with_retry)

        ex = StageExecutor(backend=_MockBackend(), bus=bus, config=config)  # no tool_policy
        stage = StageSpec(name="s", agent_name="warrior-agent", role="warrior")
        plan = _minimal_plan([stage])
        await ex.execute_single(stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="sid")

        assert captured["options"].tools == []
        assert captured["options"].role == "warrior"  # role still propagates

    @pytest.mark.asyncio
    async def test_dispatch_empty_role_stays_permissive(
        self, bus: EventBus, config: PipelineConfig, monkeypatch
    ) -> None:
        """Policy wired, stage.role='' → empty tools (backward compat for unkeyed stages)."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        captured: dict[str, object] = {}

        async def fake_execute_with_retry(backend, env, options, **kwargs):
            captured["options"] = options
            return DispatchResult(envelope=env.with_result(result="ok", cost_usd=0.0))

        monkeypatch.setattr("bonfire.engine.executor.execute_with_retry", fake_execute_with_retry)

        ex = StageExecutor(
            backend=_MockBackend(), bus=bus, config=config,
            tool_policy=DefaultToolPolicy(),
        )
        stage = StageSpec(name="s", agent_name="a", role="")  # explicit unset
        plan = _minimal_plan([stage])
        await ex.execute_single(stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="sid")

        assert captured["options"].tools == []

    @pytest.mark.asyncio
    async def test_dispatch_unmapped_role_empty_list(
        self, bus: EventBus, config: PipelineConfig, monkeypatch
    ) -> None:
        """Policy wired, stage.role unmapped → empty list (strict-once-opted-in)."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy
        captured: dict[str, object] = {}

        async def fake_execute_with_retry(backend, env, options, **kwargs):
            captured["options"] = options
            return DispatchResult(envelope=env.with_result(result="ok", cost_usd=0.0))

        monkeypatch.setattr("bonfire.engine.executor.execute_with_retry", fake_execute_with_retry)

        ex = StageExecutor(
            backend=_MockBackend(), bus=bus, config=config,
            tool_policy=DefaultToolPolicy(),
        )
        stage = StageSpec(name="s", agent_name="a", role="gardener")
        plan = _minimal_plan([stage])
        await ex.execute_single(stage=stage, prior_results={}, total_cost=0.0, plan=plan, session_id="sid")

        assert captured["options"].tools == []
        assert captured["options"].role == "gardener"

    def test_rejects_compiler_kwarg_still_holds(
        self, bus: EventBus, config: PipelineConfig
    ) -> None:
        """Sage D3 lockdown MUST remain green — ``compiler=`` still raises."""
        with pytest.raises(TypeError):
            StageExecutor(
                backend=_MockBackend(), bus=bus, config=config, compiler=object()
            )
```

### 3.3 `tests/unit/test_engine_pipeline.py` — append

Mirror `TestToolPolicyWiring` from §3.2 adapted to `PipelineEngine`. Dispatch through the backend branch of `_execute_stage` (pipeline.py:486-504). Patch `bonfire.engine.pipeline.execute_with_retry`. Use `WorkflowPlan` with a single stage + `handler_name=None`. Same six scenarios (default None, accepts kwarg, policy+role passes tools, no-policy permissive, empty-role permissive, unmapped-role strict). Same `test_rejects_compiler_kwarg_still_holds` sentinel.

### 3.4 `tests/unit/test_dispatch_sdk_backend.py` — append

```python
class TestToolsKwargPropagation:
    @pytest.mark.asyncio
    async def test_tools_kwarg_reaches_sdk_options(self, monkeypatch) -> None:
        """``DispatchOptions.tools`` MUST propagate to ``ClaudeAgentOptions.tools``
        AND ``allowed_tools`` (belt-and-suspenders)."""
        from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
        from bonfire.protocols import DispatchOptions
        captured: dict[str, object] = {}

        class _FakeOptions:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        async def fake_query(*, prompt, options):
            if False:
                yield None  # async generator

        monkeypatch.setattr("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", _FakeOptions)
        monkeypatch.setattr("bonfire.dispatch.sdk_backend.query", fake_query)

        backend = ClaudeSDKBackend()
        envelope = Envelope(task="t", agent_name="warrior-agent")
        options = DispatchOptions(
            model="claude-opus-4-7",
            tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            role="warrior",
        )
        await backend.execute(envelope, options=options)

        assert captured["tools"] == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert captured["allowed_tools"] == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]

    @pytest.mark.asyncio
    async def test_empty_tools_passes_empty_lists(self, monkeypatch) -> None:
        """Empty ``tools`` + permission_mode='dontAsk' = SDK deny-all."""
        # ... mirrors above with options=DispatchOptions(tools=[])
        # Asserts captured["tools"] == [] and captured["allowed_tools"] == []
```

**Edge cases the Knight MUST cover (from Scout findings):**
- Scout-3/337 §3 CRITICAL blocker — `test_rejects_compiler_kwarg` must remain green after this ticket. Add assertion in both executor + pipeline test classes.
- Scout-1/337 §6 gotcha — case-sensitive tool names. `test_case_sensitive` in `TestDefaultToolPolicyEdges`.
- Scout-1/337 §6 gotcha — `tools=[]` is hard kill-switch, not "default preset". `test_empty_tools_passes_empty_lists` in SDK backend tests.
- Scout-2/337 §3.3 — allow-list drift. Floor matrix tests are the frozen-snapshot guard rail.

---

## 4. Warrior Handoff — stub signatures

### `src/bonfire/dispatch/tool_policy.py`

```python
"""Per-role tool allow-list policy — W1.5.3 default floor.

The ``ToolPolicy`` Protocol lets the dispatch layer ask "for this role, which
tools are permitted?" without any particular implementation. The bundled
``DefaultToolPolicy`` ships the W1.5.3 floor — eight canonical roles mapped
to tool lists lifted from the Bonfire v0.1 axiom tables.

W4.1 (user TOML override) is a future concern; users who wish to override
can implement ``ToolPolicy`` and pass it into ``StageExecutor`` /
``PipelineEngine`` via the ``tool_policy=`` constructor kwarg.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["DefaultToolPolicy", "ToolPolicy"]


@runtime_checkable
class ToolPolicy(Protocol):
    """Resolves a role name to its permitted tool list.

    Callers pass a role string (e.g. ``"scout"``, ``"warrior"``) and receive
    the list of SDK tool names that role is allowed to invoke. An empty list
    means "no tools permitted" (SDK interprets ``allowed_tools=[]`` combined
    with ``permission_mode='dontAsk'`` as deny-all).

    Implementations MUST be pure (same role → same list) and MUST return a
    fresh list each call so callers may mutate.
    """

    def tools_for(self, role: str) -> list[str]: ...


class DefaultToolPolicy:
    """Built-in W1.5.3 floor allow-list.

    Role strings match the gamified names emitted by Bonfire workflow
    factories (``workflows/standard.py``, ``workflows/research.py``). Unmapped
    roles return an empty list.
    """

    _FLOOR: dict[str, list[str]] = {
        "scout":   ["Read", "Write", "Grep", "WebSearch", "WebFetch"],
        "knight":  ["Read", "Write", "Edit", "Grep", "Glob"],
        "warrior": ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
        "prover":  ["Read", "Bash", "Grep", "Glob"],
        "sage":    ["Read", "Write", "Grep"],
        "bard":    ["Read", "Write", "Grep", "Glob"],
        "wizard":  ["Read", "Grep", "Glob"],
        "herald":  ["Read", "Grep"],
    }

    def tools_for(self, role: str) -> list[str]:
        return list(self._FLOOR.get(role, []))
```

### `src/bonfire/protocols.py` diff (around line 65)

```python
# Agent isolation
tools: list[str] = Field(default_factory=list)
cwd: str = ""
permission_mode: str = "dontAsk"
role: str = ""  # NEW — propagated from StageSpec.role; empty = backward-compat permissive
```

### `src/bonfire/engine/executor.py` — constructor + dispatch

```python
# Top of file, TYPE_CHECKING block:
if TYPE_CHECKING:
    from bonfire.dispatch.tool_policy import ToolPolicy
    # ... existing imports ...

# __slots__ update (keep alphabetical):
__slots__ = (
    "_backend",
    "_bus",
    "_config",
    "_context_builder",
    "_handlers",
    "_project_root",
    "_tool_policy",
    "_vault_advisor",
)

# Constructor signature:
def __init__(
    self,
    *,
    backend: Any,
    bus: EventBus,
    config: PipelineConfig,
    handlers: dict[str, StageHandler] | None = None,
    context_builder: _ContextBuilderLike | None = None,
    vault_advisor: VaultAdvisor | None = None,
    project_root: Any | None = None,
    tool_policy: ToolPolicy | None = None,
) -> None:
    self._backend = backend
    self._bus = bus
    self._config = config
    self._handlers = handlers or {}
    self._context_builder = context_builder or ContextBuilder()
    self._vault_advisor = vault_advisor
    self._project_root = project_root
    self._tool_policy = tool_policy

# _dispatch_backend (replaces executor.py:255-271):
async def _dispatch_backend(self, stage: StageSpec, envelope: Envelope) -> Envelope:
    """Execute via backend through execute_with_retry."""
    if self._tool_policy is None or not stage.role:
        role_tools: list[str] = []
    else:
        role_tools = self._tool_policy.tools_for(stage.role)

    options = DispatchOptions(
        model=envelope.model or self._config.model,
        max_turns=self._config.max_turns,
        max_budget_usd=self._config.max_budget_usd,
        tools=role_tools,
        role=stage.role,
        cwd=str(self._project_root) if self._project_root else "",
    )
    result = await execute_with_retry(
        self._backend,
        envelope,
        options,
        max_retries=0,
        timeout_seconds=None,
        event_bus=self._bus,
    )
    return result.envelope
```

### `src/bonfire/engine/pipeline.py` — constructor + backend branch

Mirror the executor changes:
- `__init__` gains `tool_policy: ToolPolicy | None = None`; stores as `self._tool_policy`.
- TYPE_CHECKING import of `ToolPolicy`.
- `_execute_stage` backend branch (pipeline.py:485-504) — compute `role_tools` via same ratchet, pass `tools=role_tools, role=spec.role` into `DispatchOptions(...)`.

### `src/bonfire/dispatch/sdk_backend.py` — `ClaudeAgentOptions` call

Insert exactly one new kwarg line between `permission_mode=options.permission_mode,` (line 104) and the existing `allowed_tools=options.tools,` (line 105):

```python
agent_options = ClaudeAgentOptions(
    model=options.model,
    max_turns=options.max_turns,
    max_budget_usd=options.max_budget_usd,
    cwd=options.cwd or None,
    permission_mode=options.permission_mode,
    tools=list(options.tools),          # NEW
    allowed_tools=options.tools,
    setting_sources=["project"],
    thinking=thinking_config,
    effort=effort_level,
    stderr=lambda line: logger.warning("[CLI stderr] %s", line),
)
```

**The `role` field on `DispatchOptions` is NOT consumed by `sdk_backend.py` in BON-337.** It is added for propagation; `sdk_backend.py` only consumes `options.tools`. (BON-338 will consume `options.role` via `options.security_hooks` — entirely orthogonal.) If the dual Warrior reaches for `options.role` in `sdk_backend.py`, that is drift — stop them. This ticket does not wire a hook.

---

## 5. Cross-lane scrub

### Private-V1 references to AVOID

Per Scout-3/337 §6:

- **Do NOT port** the attribute name `_compiler`. Sage D3 blocks it via `test_rejects_compiler_kwarg`. Use `_tool_policy`.
- **Do NOT port** the method name `get_role_tools` on `PromptCompiler`. Use `tools_for` on `ToolPolicy`.
- **Do NOT port** two-tier template resolution or any `PromptCompiler` machinery.
- **Do NOT import from** `/home/ishtar/Projects/bonfire/` — that tree is private V1 and must never appear in public-v0.1 import statements.
- **Do NOT reference** "Seal #N" labels or `docs/constraint-index.md` constraint numbers (Scout-3/338 §7.1 — also applies here since both scouts grep the same private tree).

### Axiom lift is clean

Scout-3/337 §6 scrubbed the axiom tool lists for private-V1 terminology. The eight rows in `_FLOOR` (D3) are the scrubbed values — generic role names + generic tool names. No customer names, no private project markers.

### `bonfire/security/` is REJECTED

Scout-3/338 proposes `src/bonfire/security/` as a shared subpackage. **This ticket does NOT create that directory.** The entire BON-337 footprint lives in `bonfire.dispatch`. BON-338 (separate, decoupled) may introduce its own files in `bonfire.dispatch` as well without conflicting. Any cross-cutting "security" concept is refused for v0.1 — the two tickets stand alone.

---

## 6. Open questions (Wizard review, not Sage re-litigation)

1. **`disallowed_tools`** — Scout-1/337 §7.3 proposes adding `disallowed_tools: list[str] = []` to `DispatchOptions` + piping to `ClaudeAgentOptions.disallowed_tools`. Release-policy §41-43 does not demand it for the W1.5.3 floor. **Decision: DEFER to a follow-up ticket** (file as tech debt under "v0.1 tool policy v2 — add deny-rule field"). BON-337 ships without it.
2. **Scout `Glob` tool** — Scout-3/337 §4 flags that private V1 omits Glob for scout/sage while the floor matrix matches V1 exactly. Keeping parity per Scout-3/337's "Keep parity or add — Sage call." **Decision: parity — Glob omitted for scout and sage.** Wizard verifies Knight assertions match.
3. **Scout `Write(path)` suffix syntax** — Scout-2/337 §5 uses per-arg path-scoping notation. SDK does NOT support this syntactically today (Scout-1/337 §1 confirms SDK tool-scoping is string-only, no suffix parsing). **Decision: plain `"Write"` — path discipline deferred.** Future BON-337-follow-up can add arg-filter layer; BON-338 hook will cover destructive Write paths in the meantime.
4. **Workflow factory defaulting** — current `_stage("scout", "scout")` in `workflows/standard.py:52` passes role string. Workflows are ready. No action needed for BON-337 — the field already propagates.
5. **Bard's `gh`** — Bard's axiom omits Bash per Scout-3/337 §4. Private V1 routes Bard through a StageHandler. v0.1 does not ship a Bard handler yet (handlers/__init__.py is placeholder per Scout-3/337 §2). **Out of scope for BON-337.** When the Bard handler lands, it bypasses this backend-dispatch path and invokes `gh` in-process; allow-list stays honest.

**Tech-debt notes Wizard should file on PR:**
- Follow-up: add `disallowed_tools` field + wiring (Scout-1/337 §7.3).
- Follow-up: add arg-filter layer for Bash + Write (Scout-2/337 §5 per-tool-with-args).
- Follow-up: `AgentRole` enum ↔ workflow-string reconciliation (Scout-3/337 §1 naming mismatch).
- Follow-up: Bard `gh` handler (separate Wave 5+ ticket).

---

*End of BON-337 Sage Decision.*
