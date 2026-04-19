# Scout-3 / BON-337 / Bonfire Shape — Report

## 1. Role Taxonomy (v0.1 public)

v0.1 ships TWO parallel role namings — canonical enum `AgentRole` (8 professional terms) + workflow factories (8 gamified terms). They do NOT match 1:1.

**Canonical enum** — `src/bonfire/agent/roles.py:15-39`:

| Enum | Serialized | Display |
|---|---|---|
| RESEARCHER | "researcher" | Scout |
| TESTER | "tester" | Knight |
| IMPLEMENTER | "implementer" | Warrior |
| VERIFIER | "verifier" | Assayer/Prover |
| PUBLISHER | "publisher" | Bard |
| REVIEWER | "reviewer" | Wizard |
| CLOSER | "closer" | Herald |
| SYNTHESIZER | "synthesizer" | Sage |

**Workflow factories pass gamified strings** to `StageSpec.role` — `workflows/standard.py:52-87`, `workflows/research.py:18,28`:

| Stage | role string | Workflows |
|---|---|---|
| scout | "scout" | standard_build, debug, dual_scout, triple_scout, spike |
| knight | "knight" | standard_build |
| warrior | "warrior" | standard_build, debug |
| prover | "prover" | standard_build (uses verification gate) |
| bard | "bard" | standard_build (handler_name="bard") |
| wizard | "wizard" | standard_build (handler_name="wizard") |
| herald | "herald" | standard_build (handler_name="herald") |
| sage | "sage" | dual_scout, triple_scout, spike |

**Naming mismatch (flag for Sage):** `AgentRole` enum values don't match workflow-factory strings. Nothing in `dispatch/` consults `AgentRole`. Enum exists but is unused at dispatch seam. BON-337 picks ONE set — the gamified strings are what flow today.

**`StageSpec.role`** — `models/plan.py:53`: `role: str = ""` (free-form, empty default). This is the hook. BON-337 keys allow-list off it directly.

## 2. Current Tool Usage Per Role

**There is no per-role tool scoping in public v0.1 today.** Every role receives `tools=[]` in DispatchOptions. SDK interprets empty as "no `--allowedTools` flag" — *permissive*.

Evidence chain:
- `protocols.py:65` — `DispatchOptions.tools: list[str] = Field(default_factory=list)`
- `engine/executor.py:257-262` — `_dispatch_backend` constructs DispatchOptions. **No `tools=` argument.**
- `engine/pipeline.py:490-495` — `_execute_stage` backend branch. **No `tools=` argument.**
- `dispatch/sdk_backend.py:105` — `allowed_tools=options.tools` passes empty through.
- `.venv/.../subprocess_cli.py:196-197` — `if self._options.allowed_tools:` → flag only emitted when non-empty.

Current matrix is trivially uniform: every role unrestricted. Handlers are stub-only (`handlers/__init__.py`: "placeholder for v0.1 transfer"). standard_build will fail at bard with "Unknown handler: bard".

## 3. Private V1 Reference Patterns

Private V1 has working per-role allow-list from YAML frontmatter on agent axiom files.

**Seam — `bonfire/src/bonfire/engine/executor.py:261-273`:**

```python
async def _dispatch_backend(self, stage: StageSpec, envelope: Envelope) -> Envelope:
    role_tools: list[str] = []
    if self._compiler is not None and stage.role:
        role_tools = self._compiler.get_role_tools(stage.role)

    options = DispatchOptions(
        model=envelope.model or self._config.model,
        max_turns=self._config.max_turns,
        max_budget_usd=self._config.max_budget_usd,
        tools=role_tools,
        cwd=str(self._project_root) if self._project_root else "",
    )
```

Mirror at `engine/pipeline.py:432-442`.

**Lookup — `bonfire/src/bonfire/prompt/compiler.py:280-293`:**
```python
def get_role_tools(self, role: str) -> list[str]:
    try:
        _, meta = self.load_axiom_validated(role)
        return list(meta.tools)
    except ValueError:
        return []
```

**Validation — `bonfire/src/bonfire/prompt/axiom_meta.py:26-47`:**
```python
class AxiomMeta(BaseModel):
    role: str
    version: str
    truncation_priority: int = Field(gt=0)
    cognitive_pattern: Literal["observe","contract","execute","synthesize","audit","publish","announce"]
    tools: list[str] = Field(default_factory=list)
    output_contract: _OutputContract
```

**Axiom tool lists — `bonfire/agents/{role}/axiom.md`:**

| Role | Tools | Cognitive pattern |
|---|---|---|
| scout | [Read, Write, Grep, WebSearch, WebFetch] | observe |
| knight | [Read, Write, Edit, Grep, Glob] | contract |
| warrior | [Read, Write, Edit, Bash, Grep, Glob] | execute |
| prover | [Read, Bash, Grep, Glob] | audit |
| sage | [Read, Write, Grep] | synthesize |
| bard | [Read, Write, Grep, Glob] | publish |
| wizard | [Read, Grep, Glob] | audit |
| herald | [Read, Grep] | announce |

Wizard handler also self-scopes at handler level (`bonfire/handlers/wizard.py:286`: `tools=["Read","Grep","Glob"]`).

### **CRITICAL BLOCKER — Sage D3 collision**

Public v0.1 Sage decision D3 (`docs/audit/sage-decisions/bon-334-...md:57-71`) **explicitly drops the `compiler` kwarg**. Tests lock it:
- `tests/unit/test_engine_pipeline.py:449` — `test_rejects_compiler_kwarg` asserts `TypeError` when caller passes `compiler=`.
- `tests/unit/test_engine_executor.py:250` — same.

**Porting V1's exact `self._compiler.get_role_tools(stage.role)` mechanism is a non-starter.** BON-337 MUST use a different dependency name and different seam.

## 4. Proposed Role × Tool Matrix

Lifted from private V1 axiom (cross-lane scrubbed; see §6). Default / floor allow-list.

| Role | Read | Write | Edit | Grep | Glob | Bash | WebSearch | WebFetch | MCP-* |
|---|---|---|---|---|---|---|---|---|---|
| scout | ✓ | ✓ | ✗ | ✓ | ✗* | ✗ | ✓ | ✓ | ✗ |
| knight | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| warrior | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| prover | ✓ | ✗ | ✗ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| sage | ✓ | ✓ | ✗ | ✓ | ✗* | ✗ | ✗ | ✗ | ✗ |
| bard | ✓ | ✓ | ✗ | ✓ | ✓ | ✗** | ✗ | ✗ | ✗ |
| wizard | ✓ | ✗ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| herald | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |

**\*Glob:** V1 scout/sage omit. Keep parity or add — Sage call.
**\*\*Bard's `gh`:** axiom omits Bash; private V1 dispatches Bard through `StageHandler` that bypasses backend → bypasses allow-list. v0.1 choice: accept handler model OR include `Bash(gh:*)` scoped primitive.

Justifications:
- **scout:** "Never modify files" but Write IS in axiom. Reconciliation: writes reports to scratch path. BON-337 may want `Write(path)` suffix syntax — Sage decides.
- **knight:** "Output is tests only." Path discipline deferred.
- **warrior:** "Verify tools exist. Permission denial kills more warriors than bad logic." Matches memory. Does NOT modify tests ("Knight's word is law") — test-file immutability is future Wave.
- **prover:** "Never trust prior results. Run suite yourself." Bash required; no Write.
- **sage:** Write is for synthesis output, not code.
- **wizard:** "Review ONLY code introduced by this PR." Read-only by design.
- **herald:** "Output is display-only." Minimum surface.

**MCP-\***: all roles default deny. W4.1 is where users opt in per role.

**Trust triangle** — `docs/release-policy.md:41-43`:
- BON-337 = W1.5.3 default allow-list floor (this matrix).
- W4.1 = user TOML override.
- W4.2 = default security hook set (permission-callback layer; BON-338).

## 5. Integration Seam Proposal

**Do NOT port `_compiler` attribute.** Sage D3 locked it out. Use a new dependency name.

### New module: `src/bonfire/dispatch/tool_policy.py`

```python
class ToolPolicy(Protocol):
    def tools_for(self, role: str) -> list[str]: ...

class DefaultToolPolicy:
    """Built-in W1.5.3 floor allow-list. Keyed by StageSpec.role string."""
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

### Enforcement — TWO mirrored sites

v0.1 has BOTH `engine/executor.py:_dispatch_backend` (line 255) AND `engine/pipeline.py::_execute_stage` backend branch (lines 486-504). Same pre-existing duplication (not this ticket's to refactor).

**Change pattern:**
```python
# BEFORE (executor.py:257)
options = DispatchOptions(model=..., max_turns=..., max_budget_usd=..., cwd=...)

# AFTER
role_tools = (
    self._tool_policy.tools_for(stage.role)
    if self._tool_policy is not None and stage.role
    else []
)
options = DispatchOptions(
    model=envelope.model or self._config.model,
    max_turns=self._config.max_turns,
    max_budget_usd=self._config.max_budget_usd,
    tools=role_tools,
    cwd=str(self._project_root) if self._project_root else "",
)
```

### Constructor wiring

Add `tool_policy: ToolPolicy | None = None` to `StageExecutor.__init__` (executor.py:65-82) and `PipelineEngine.__init__` (pipeline.py:91-108). Default `None` keeps "permissive" behavior — important for backward compat with Sage D3's compiler-less constructor. Locked `test_rejects_compiler_kwarg` still passes (asserts `compiler=` specifically; `tool_policy=` is different parameter).

Add `_tool_policy` to `StageExecutor.__slots__`.

### Composition root

No bonfire-public composition root exists yet. Future CLI boot instantiates `DefaultToolPolicy()`. W4.1 lands TOML-driven `UserToolPolicy` overlay.

### Files touched by BON-337

- `src/bonfire/dispatch/tool_policy.py` — NEW
- `src/bonfire/protocols.py` — optionally re-export `ToolPolicy`
- `src/bonfire/engine/executor.py:65` — accept `tool_policy` kwarg
- `src/bonfire/engine/pipeline.py:91` — same
- `tests/unit/test_tool_policy.py` — NEW
- `tests/unit/test_engine_executor.py` — add tests
- `tests/unit/test_engine_pipeline.py` — same

### NOT touched

- `handlers/*` — handler branch doesn't call backend; handlers self-scope.
- `AgentRole` enum — not the policy key (mismatch with workflow strings). Reconciling is separate ticket.
- `permission_mode`, `setting_sources`, `stderr` — already correct in `sdk_backend.py`.

## 6. Cross-Lane Scrub Notes

Files READ but never modified: everything under `/home/ishtar/Projects/bonfire/`.

SAFE to reuse verbatim (generic terminology):
- `AxiomMeta` schema + 7 `cognitive_pattern` literals.
- Eight axiom frontmatter tool lists.
- Call-site pattern `role_tools = f(role)` → `tools=role_tools` in DispatchOptions.

AVOID porting:
- Attribute name `_compiler` — Sage D3 blocks; carries private V1 mega-compiler semantics.
- Method name `get_role_tools` on `PromptCompiler` — public v0.1 uses dedicated `ToolPolicy`.
- Two-tier template resolution — part of V1 PromptCompiler not ported.

Private-identifier scrub: Grepped axioms for private refs. Clean. "Forge" appears in wizard prompt as Bonfire metaphor — fine. No customer names.

## 7. Open Questions for Sage

1. **Default when no policy wired:** empty `tools=[]` (permissive, current) vs strict-by-default? V1 is permissive; release-policy says "floor" which leans strict. Pick one.
2. **Which role name canon wins?** `AgentRole` uses "researcher"/"tester"; workflow factories use "scout"/"knight". BON-337 can key to gamified strings flowing today; enum reconciliation is separate.
3. **Scout Write scope:** V1 grants `Write` but identity says "read-only". Intent: Write reports, not source. SDK supports `Write(path)` suffix. BON-337 path-scoped vs plain `"Write"` with path discipline deferred?
4. **Bard's `gh`:** axiom no Bash but PR publishing needs it. V1 dispatches via `StageHandler` (bypasses allow-list). v0.1 accepts handler model, or include `Bash(gh:*)` scoped primitive?

## Sources

- `src/bonfire/agent/roles.py:15-39`
- `src/bonfire/protocols.py:47-67`
- `src/bonfire/dispatch/sdk_backend.py:99-110`
- `src/bonfire/dispatch/tier.py:10-23`
- `src/bonfire/engine/executor.py:255-271`
- `src/bonfire/engine/pipeline.py:486-504`
- `src/bonfire/workflows/standard.py:52-87`
- `src/bonfire/workflows/research.py:18,28`
- `src/bonfire/models/plan.py:46-63`
- `src/bonfire/handlers/__init__.py:1`
- `docs/release-policy.md:35-43`
- `docs/audit/sage-decisions/bon-334-sage-2026-04-18T19-14-42Z.md:57-71`
- `tests/unit/test_engine_executor.py:250-259`, `test_engine_pipeline.py:449-458`
- `bonfire/src/bonfire/engine/executor.py:261-281` (V1 reference)
- `bonfire/src/bonfire/engine/pipeline.py:432-450` (V1 reference)
- `bonfire/src/bonfire/prompt/compiler.py:280-293` (V1 reference)
- `bonfire/src/bonfire/prompt/axiom_meta.py:26-47` (V1 reference)
- `bonfire/src/bonfire/handlers/wizard.py:286` (V1 reference)
- `bonfire/agents/{scout,knight,warrior,prover,sage,bard,wizard,herald}/axiom.md` (V1 reference)
- `.venv/.../subprocess_cli.py:196-206`
