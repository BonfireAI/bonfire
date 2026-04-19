# Scout-1 / BON-337 / SDK Security — Report

**SDK version under study:** `claude_agent_sdk==0.1.60`, installed at `/home/ishtar/Projects/bonfire-public/.venv/lib/python3.12/site-packages/claude_agent_sdk/`. Fetched 2026-04-18.

## 1. API Surface

Five fields form the tool-scoping surface on `ClaudeAgentOptions` (`types.py:1174-1212`):

```python
@dataclass
class ClaudeAgentOptions:
    tools: list[str] | ToolsPreset | None = None          # PRESENCE layer
    allowed_tools: list[str] = field(default_factory=list) # AUTO-APPROVE layer
    disallowed_tools: list[str] = field(default_factory=list) # HARD DENY layer
    permission_mode: PermissionMode | None = None          # DEFAULT FALLBACK
    can_use_tool: CanUseTool | None = None                 # RUNTIME CALLBACK
    hooks: dict[HookEvent, list[HookMatcher]] | None = None
    agents: dict[str, AgentDefinition] | None = None       # PER-SUBAGENT SCOPE
```

`PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"]`.

### Semantic layer cheat sheet

| Layer | Field | What it does |
|-------|-------|--------------|
| Presence | `tools` | Which tools appear in Claude's tool-definitions. `None` = default preset; `[]` = zero built-ins; explicit list = only those. |
| Auto-approve | `allowed_tools` | Tools that skip permission prompt. Does NOT gate availability. |
| Hard deny | `disallowed_tools` | Always blocked, even in `bypassPermissions`. Checked first. |
| Default | `permission_mode` | What happens to unmatched tool calls. |
| Runtime | `can_use_tool` | Last-resort callback. Requires streaming mode. |

### Wire format

Python SDK is thin shell around Node CLI subprocess. From `_internal/transport/subprocess_cli.py:184-206`:

```python
if self._options.tools is not None:
    tools = self._options.tools
    if isinstance(tools, list):
        if len(tools) == 0:
            cmd.extend(["--tools", ""])        # hard kill-switch
        else:
            cmd.extend(["--tools", ",".join(tools)])

if self._options.allowed_tools:
    cmd.extend(["--allowedTools", ",".join(self._options.allowed_tools)])

if self._options.disallowed_tools:
    cmd.extend(["--disallowedTools", ",".join(self._options.disallowed_tools)])
```

Enforcement happens CLI-side, not in Python.

### AgentDefinition — per-sub-agent scope (types.py:81-99)

Has `tools: list[str] | None` and `disallowedTools: list[str] | None`. Added in SDK 0.1.51. Subagents are sent via `initialize` control-protocol, not CLI flag.

## 2. Denial Semantics

### Canonical evaluation order

1. **Hooks.** Allow/deny/continue.
2. **Deny rules.** `disallowed_tools` + settings.json. Holds even in `bypassPermissions`.
3. **Permission mode.** `bypassPermissions` approves; `acceptEdits` approves file ops; others fall through.
4. **Allow rules.** `allowed_tools` approves.
5. **canUseTool callback.** Skipped in `dontAsk` (tool denied instead).

### Denial — three physical signals

1. `permission_denials: list[Any]` on `ResultMessage` (`types.py:1021`). CLI emits list of dicts with at least `tool_name`.
2. Tool-result block with `is_error=True`. `PermissionResultDeny.message` (types.py:199-205) is injected so model can react. `interrupt=True` stops loop entirely.
3. `is_error=True` + `errors` on `ResultMessage` if session fails.

### The catch

**`allowed_tools` is approval, not presence.** Listing `["Read"]` does NOT remove Write from Claude's tool-context. Web confirms (Issue #361): "allowed_tools is a permission allowlist ... It does not remove tools from Claude's toolset."

### The lockdown recipe (docs verbatim)

> "For a locked-down agent, pair `allowedTools` with `permissionMode: 'dontAsk'`."

```python
ClaudeAgentOptions(
    allowed_tools=["Read", "Glob", "Grep"],
    permission_mode="dontAsk",
)
```

### Bonfire's current state is correct

`protocols.py:67`: `permission_mode: str = "dontAsk"` by default.
`sdk_backend.py:104-105`: `permission_mode=options.permission_mode, allowed_tools=options.tools`.

**So a Bonfire Scout with `tools=["Read","Grep","Glob"]` in its envelope is CURRENTLY locked down.** What's missing for BON-337: per-role discipline (making sure every envelope's `tools` reflects the role) plus `disallowed_tools` as belt-and-suspenders.

## 3. MCP Tool Interaction

MCP tools: `mcp__<server-name>__<tool-name>`. Double-underscore. Case-sensitive.

Wildcards: `mcp__claude-code-docs__*` — trailing `*` on tool-name segment of MCP tool only. Not documented for built-ins. No regex.

**Gotcha:** `permissionMode: "acceptEdits"` does NOT auto-approve MCP tools. Only file edits and filesystem Bash.

**Task→Agent rename:** `permission_denials[].tool_name` may report `"Task"` while transcripts say `"Agent"`. Match both when writing assertions.

## 4. Hook Ordering

**Hooks run FIRST** (step 1). Before `disallowed_tools`. Before `permission_mode`. Before `allowed_tools`. Before `can_use_tool`.

PreToolUse returns:
```python
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow" | "deny" | "ask",
        "permissionDecisionReason": "...",
        "updatedInput": {...},
    }
}
```

Within hooks: `deny > ask > allow` — any deny wins.

## 5. Dynamic vs Static

- `tools` / `allowed_tools` / `disallowed_tools` are static at subprocess spawn.
- Only `permission_mode` is mutable mid-session via `set_permission_mode()` (client.py:255-280).
- Per-sub-agent: `AgentDefinition` locks at options-construction time.

**Inheritance warning (verbatim):**
> "When the parent uses `bypassPermissions`, `acceptEdits`, or `auto`, all subagents inherit that mode and it cannot be overridden per subagent."

For BON-337 this is load-bearing — if top-level session uses `bypassPermissions`, every sub-agent is free.

## 6. Gotchas

1. `allowed_tools` is approval, not presence.
2. `bypassPermissions` overrides everything except deny rules and hooks.
3. Subagents inherit `bypassPermissions`/`acceptEdits`/`auto` and cannot override.
4. Deny rules beat allow rules in every mode — `disallowed_tools` is the only truly absolute block.
5. `dontAsk` is SDK/CLI-specific. Standard `default` mode in non-interactive SDK subprocess is undefined.
6. `can_use_tool` requires streaming mode (AsyncIterable prompt, not string). Bonfire's current string-prompt path avoids needing it.
7. MCP wildcard only works trailing.
8. Case-sensitive tool names.
9. `tools=[]` is hard kill-switch; `tools=None` is default preset. Don't confuse.
10. Task→Agent rename — match both in assertions.
11. `max_turns` exit skips hooks (audit gaps at turn-limit).
12. `setting_sources` controls whether `.claude/settings.json` deny rules are read.

## 7. Bonfire Integration Observations

### The seam is already carved

`src/bonfire/protocols.py:47-67` — `DispatchOptions.tools: list[str]` and `permission_mode: str = "dontAsk"`.

`src/bonfire/dispatch/sdk_backend.py:99-110` — only site Bonfire constructs `ClaudeAgentOptions`:
```python
agent_options = ClaudeAgentOptions(
    model=options.model,
    max_turns=options.max_turns,
    max_budget_usd=options.max_budget_usd,
    cwd=options.cwd or None,
    permission_mode=options.permission_mode,
    allowed_tools=options.tools,          # <-- critical mapping
    setting_sources=["project"],
    ...
)
```

Bonfire passes `DispatchOptions.tools` → `ClaudeAgentOptions.allowed_tools` (approval layer, not presence). Combined with `dontAsk`, effective physical enforcement.

### Gaps BON-337 closes

1. `DispatchOptions` has no `disallowed_tools` field.
2. `permission_mode` is free `str`, not `Literal`. Forbid `"bypassPermissions"`/`"acceptEdits"` at type level.
3. No per-role default map. Roles are free-form strings; need canonical mapping `role → allowed_tools`.
4. `AgentDefinition` (SDK's per-subagent) is NOT used. Bonfire uses top-level `query()` per role — simpler, `DispatchOptions.tools` is complete.
5. No hook audit layer. `hooks` not set anywhere.
6. No tests asserting denial.

### Recommended seam

```python
class DispatchOptions(BaseModel):
    tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)  # NEW
    permission_mode: Literal["dontAsk", "plan", "default"] = "dontAsk"  # TIGHTEN

# in sdk_backend.py:
agent_options = ClaudeAgentOptions(
    ...,
    tools=list(options.tools),                    # ALSO set presence layer
    allowed_tools=options.tools,
    disallowed_tools=options.disallowed_tools,
    permission_mode=options.permission_mode,
    hooks={"PreToolUse": [HookMatcher(hooks=[vault_audit_hook])]},
)
```

Belt-and-suspenders: presence + approval + hard-deny together.

## Sources

- `https://code.claude.com/docs/en/agent-sdk/permissions` — 5-step evaluation order; dontAsk; bypassPermissions warning; subagent inheritance
- `https://code.claude.com/docs/en/agent-sdk/python` — ClaudeAgentOptions reference
- `https://code.claude.com/docs/en/agent-sdk/hooks` — PreToolUseHookSpecificOutput schema; deny>ask>allow priority
- `https://code.claude.com/docs/en/agent-sdk/mcp` — mcp__server__tool naming; wildcard; acceptEdits gotcha
- `https://code.claude.com/docs/en/agent-sdk/subagents` — AgentDefinition.tools; Task→Agent rename
- `https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md` — 0.1.51 disallowedTools; 0.1.60 setting_sources fix
- `https://github.com/anthropics/claude-agent-sdk-python/issues/361` — allowed_tools-as-approval confirmation
- `.venv/.../claude_agent_sdk/types.py:24-26,81-99,189-212,1021,1174-1248`
- `.venv/.../claude_agent_sdk/_internal/transport/subprocess_cli.py:184-206`
- `.venv/.../claude_agent_sdk/_internal/query.py:273-316`
- `.venv/.../claude_agent_sdk/_internal/message_parser.py:211`
- `.venv/.../claude_agent_sdk/client.py:116-134,255-280`
- `src/bonfire/protocols.py:47-67`
- `src/bonfire/dispatch/sdk_backend.py:99-110`
