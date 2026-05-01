# Contributing to Bonfire

Bonfire is an open-source framework for running AI build pipelines
against real code. It dispatches a sequence of specialized agents
through typed stages with quality gates between them. This document
is for developers who want to contribute code, tests, or documentation
to the project.

## Release Status

`bonfire-ai` ships a public functional release line at `v0.1.x`. The
PyPI classifier is `Development Status :: 4 - Beta`. Pipeline
primitives, BYOK model routing, and the browser-based onboarding scan
are wired and exercised by the test suite. Knowledge-graph storage
("the vault") and the end-to-end project workflow remain in progress
and ship in subsequent 0.1.x releases. The vocabulary, the protocols,
and the config schema are stable for 0.1.x. See
[`docs/release-policy.md`](docs/release-policy.md) for the full
versioning policy and what counts as a breaking change, and
[`CHANGELOG.md`](CHANGELOG.md) for per-release notes.

## Development Setup

Bonfire requires Python 3.12 or newer. All development happens inside
a virtual environment.

```bash
# Clone the repository
git clone https://github.com/BonfireAI/bonfire.git
cd bonfire

# Create and activate a Python 3.12 venv
python3.12 -m venv .venv
source .venv/bin/activate

# Install the package in editable mode with dev extras
pip install -e ".[dev]"
```

Once installed, the standard development commands are:

```bash
# Run the full test suite
pytest tests/

# Lint
ruff check src/ tests/

# Check formatting without modifying files
ruff format --check src/ tests/

# Apply formatting fixes
ruff format src/ tests/
```

CI runs `pytest`, `ruff check`, and `ruff format --check` on every
push and pull request. Run them locally before opening a PR.

## Role Glossary

Bonfire uses a three-layer naming system for agent roles. Code always
uses the generic identifier — the professional and gamified names are
display concerns handled by the persona layer. When you read or write
narrative prose in this repository, use the generic names. The
professional and gamified names appear only in user-facing output
and in the table below.

The source of truth is the `ROLE_DISPLAY` dictionary in
[`src/bonfire/naming.py`](src/bonfire/naming.py). The table below
must match that file exactly. If you change one, change the other.

| Generic (code) | Professional (display) | Gamified (display) |
|----------------|------------------------|--------------------|
| researcher     | Research Agent         | Scout              |
| tester         | Test Agent             | Knight             |
| implementer    | Build Agent            | Warrior            |
| verifier       | Verify Agent           | Assayer            |
| publisher      | Publish Agent          | Bard               |
| reviewer       | Review Agent           | Wizard             |
| closer         | Release Agent          | Herald             |
| synthesizer    | Synthesis Agent        | Sage               |
| analyst        | Analysis Agent         | Architect          |

## How to Add a New Role

Adding a role touches the enum, the display map, the test suite, and
this document. All four changes belong in a single pull request.

1. Add a new member to the `AgentRole` `StrEnum` in
   [`src/bonfire/agent/roles.py`](src/bonfire/agent/roles.py).
2. Add a matching entry to `ROLE_DISPLAY` in
   [`src/bonfire/naming.py`](src/bonfire/naming.py) with the
   professional and gamified display names.
3. Add a unit test that asserts the new role has both display names
   defined. Place it alongside the existing naming tests.
4. Update the role glossary table in this file so the documentation
   matches the code.

## Testing Conventions

Tests use `pytest`. The project is configured with
`asyncio_mode = "auto"`, so async test functions are picked up
automatically — you do not need to decorate them with
`@pytest.mark.asyncio`.

Tests are organized into two directories:

- `tests/unit/` — fast, isolated tests for individual modules.
  These run on every CI invocation and must stay deterministic.
- `tests/integration/` — broader tests that exercise multiple
  modules together. Still deterministic; no network calls.

Tests that require a real API key are marked with
`@pytest.mark.live` and are skipped by default.

Coverage is measured with the `coverage` package. To produce a local
coverage report:

```bash
coverage run -m pytest tests/
coverage report
```

## Pull Request Process

1. **Branch naming.** Create a branch off `main` using
   `your-name/short-description` or `topic/short-description`.
   Keep the description lowercase and hyphenated.

2. **Commits.** Write commit messages in the imperative mood
   ("add role glossary", not "added role glossary"). Conventional
   Commits prefixes (`feat:`, `fix:`, `docs:`, etc.) are welcome
   but not required. Keep each commit to one logical change; it
   makes review and revert dramatically easier.

3. **No internal references.** This is a public repository. Do not
   include internal tracker IDs, project codenames, or other
   references that would be meaningless to outside readers in
   commit messages, code comments, or documentation.

4. **CI must pass.** Your PR needs green checks on `pytest`,
   `ruff check`, and `ruff format --check` before it can be merged.

5. **PR description.** Include a short summary of the change and a
   test plan — the specific commands a reviewer can run to verify
   the behavior. Link to any relevant documents under `docs/`.

## Code of Conduct

A formal `CODE_OF_CONDUCT.md` is forthcoming. Until it lands,
contributors are expected to be respectful, constructive, and
patient with one another. Disagreements are fine; disrespect is not.

## License

Bonfire is released under the Apache License 2.0. By contributing,
you agree that your contributions will be licensed under the same
terms.
