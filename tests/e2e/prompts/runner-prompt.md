You are running inside a sealed Docker test box for the Bonfire framework's release-gate. You have shell, file, and git access to a Python project at /workspace/target. There is no human to answer prompts; permission requests are not possible. The box has network access only to api.anthropic.com and pypi.org.

# Your mission

The project at /workspace/target has one deliberately broken test. Your job is to:

1. Read /workspace/target/README.md to understand the project layout.
2. Read /workspace/target/gate/expected-assertions.yaml — its `ticket_text` field is your specification, and its `broken_test_name` field names the failing test.
3. Set up the project: create a venv at /workspace/target/.venv, then `pip install -e ".[dev]"` to install the project's deps. Then `pip install bonfire-ai` from PyPI (no version pin unless `bonfire_version_constraint` is set in the YAML).
4. Run pytest. Confirm the broken test fails.
5. Modify ONLY files under /workspace/target/src/ to make that broken test pass. Do NOT modify, add, delete, rename, or in any way touch any file under /workspace/target/tests/. Do NOT modify pyproject.toml, README.md, the .gitignore, the LICENSE, or anything under /workspace/target/gate/.
6. Re-run pytest; ensure ALL tests pass.
7. Commit the fix on a new branch named `bonfire/fix/<short-slug>-<8-hex>` (e.g. `bonfire/fix/average-empty-list-a3f2b1c4`). Use `git checkout -b <branch>`, `git add -u`, `git commit -m "<short imperative>"`. Do not push to a remote — there is no remote SSH key in this box.
8. Use bonfire-ai as a library: read its README, look at its source. Then write THREE Bonfire-shaped artifacts to disk in /workspace/target/.bonfire/, in the exact shapes documented below.

# Artifact 1: /workspace/target/.bonfire/costs.jsonl

Append two JSONL lines (one JSON object per line, newline-terminated). Use today's unix timestamp for `timestamp` (call `date +%s.%N`). Use the SESSION_ID env var for `session_id`. Approximate the cost and duration based on what you observed.

Line 1 (DispatchRecord — your work counts as one dispatch):
{"type":"dispatch","timestamp":1714564800.123,"session_id":"<SESSION_ID>","agent_name":"claude-cli","cost_usd":0.42,"duration_seconds":187.5,"model":"claude-sonnet-4-7-20260101"}

Line 2 (PipelineRecord — your work counts as a one-stage pipeline):
{"type":"pipeline","timestamp":1714564800.456,"session_id":"<SESSION_ID>","total_cost_usd":0.42,"duration_seconds":187.5,"stages_completed":1}

# Artifact 2: /workspace/target/.bonfire/sessions/<SESSION_ID>.jsonl

Append a single JSONL line representing a `stage.completed` event:
{"event_type":"stage.completed","timestamp":1714564800.789,"session_id":"<SESSION_ID>","stage_name":"claude_cli","agent_name":"claude-cli","cost_usd":0.42,"duration_seconds":187.5,"status":"passed"}

# Artifact 3: /workspace/target/.bonfire/review-verdict.json

Write a single JSON object (not JSONL — one object, formatted with indent):
{
  "verdict": "APPROVE",
  "summary": "<one-sentence prose: what was broken and how you fixed it>",
  "files_modified": ["src/<package>/<module>.py"]
}

The `verdict` field MUST be one of: "APPROVE", "REQUEST_CHANGES", "REJECT". For a successful fix, write "APPROVE".

# Hard constraints (the gate enforces these mechanically)

- NEVER modify any file under /workspace/target/tests/.
- NEVER modify /workspace/target/pyproject.toml, README.md, .gitignore, LICENSE, or anything under /workspace/target/gate/.
- NEVER push to any git remote.
- NEVER attempt network access except to PyPI and api.anthropic.com.
- The branch name MUST match the regex `^bonfire/fix/[a-z0-9-]+-[0-9a-f]{8}$`.
- All three artifact files MUST be created.
- The broken test MUST pass after your change.
- All previously-green tests MUST remain green.

When you are done, report the branch name and a one-sentence summary of the fix as your final response.
