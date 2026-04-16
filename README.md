# Bonfire

**AI Build Pipelines for Real Code**

Define agents. Wire stages. Ship quality.

```bash
pip install bonfire-ai
bonfire scan ./your-repo
bonfire run "Fix the authentication bug in login.py"
```

Bonfire dispatches a pipeline of specialized agents -- each with its own
identity, tools, and quality gates. TDD built in. Code review built in.
Your repo, your rules.

## What Bonfire Does

`bonfire run` takes a task and runs it through a pipeline of 8 agents:

| Agent | Role | What It Does |
|-------|------|-------------|
| Research Agent | researcher | Investigates the task, gathers codebase context |
| Test Agent | tester | Writes failing tests that define the contract (TDD RED) |
| Build Agent | implementer | Writes code to pass the tests (TDD GREEN) |
| Verify Agent | verifier | Independent quality verification |
| Publish Agent | publisher | Creates branches, commits, opens PRs |
| Review Agent | reviewer | Code review with structured verdicts |
| Release Agent | closer | Merges approved PRs, announces completion |
| Synthesis Agent | synthesizer | Combines multiple reports into unified analysis |

Quality gates between stages enforce standards. If the Review Agent
rejects, work bounces back to the Build Agent. The loop continues
until quality passes or budget is exhausted.

## Quick Start

```bash
# Install
pip install bonfire-ai

# Scan your repo (first-time setup)
bonfire scan ./my-project

# Run a task
bonfire run "Add input validation to the user registration endpoint"
```

## Your Keys, Your Models

Bonfire never sells LLM tokens. You bring your own API key.
Configure model routing per agent role:

```toml
# bonfire.toml
[bonfire.models]
reasoning = "claude-sonnet-4-20250514"    # researcher, reviewer
fast = "claude-haiku-4-5-20251001"        # tester, implementer
balanced = "claude-sonnet-4-20250514"     # verifier, synthesizer
```

## Personality (Optional)

Bonfire ships with a professional default voice. Want personality?

```bash
bonfire run --persona forge "Fix the auth bug"
```

The forge persona turns "Dispatching Research Agent" into
"Scout takes the field." Same pipeline. Different voice.

## Extension Points

Four protocols define Bonfire's pluggable boundaries:

- **AgentBackend** -- swap the LLM provider
- **VaultBackend** -- swap the knowledge store
- **QualityGate** -- custom pass/fail logic between stages
- **StageHandler** -- custom stage behavior

```python
from bonfire.protocols import AgentBackend

class MyBackend(AgentBackend):
    async def dispatch(self, envelope, options):
        # your implementation
        ...
```

## License

Apache-2.0. Open source. Free as in free beer.

Built by [The Forge](https://github.com/BonfireAI).
