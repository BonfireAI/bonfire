# Instruction Set Markup (ISM) — Specification v1

**Status:** Draft v1.
**Audience:** Contributors authoring or reviewing third-party tool integrations for `bonfire-public`.
**Scope:** This document defines the ISM v1 file format, schema, validation rules, and two-tier discovery model. It does **not** define execution semantics for detection rules — that contract ships with the ISM scanner.

## 1. Why ISM exists

Bonfire is a pipeline runtime. Pipelines reach out to third-party tools: a forge to open pull requests, a ticketing service to close issues, a comms service to post a notification, a vault backend to persist knowledge, an IDE-aware surface to wire context. Today every one of those bindings is hand-coded Python in a stage handler.

A contributor adding GitLab support, a user on a niche stack, or a maintainer wiring a new comms target should not have to write Python and edit core handlers. ISM turns the integration surface into a documented contract: one declarative file per integration. Bonfire's bundled adapters are reference implementations under Apache-2.0; users override them with project-local files.

## 2. File format

ISM documents are **markdown files with a YAML frontmatter block**. Filenames end in `.ism.md`. A document has two parts:

```markdown
---
# YAML frontmatter — machine-readable schema (this section)
ism_version: 1
name: github
display_name: GitHub
# ...
---
# Markdown body — human-readable content (this section)

## Overview
GitHub is the default forge for bonfire.

## Setup
1. Install the gh CLI.
2. Run `gh auth login`.
```

The frontmatter is delimited by lines containing exactly `---`. Everything between the delimiters is parsed as YAML. Everything after the closing delimiter is preserved as the markdown body and made available to the loader.

## 3. Frontmatter schema

The frontmatter is a YAML mapping. Field-by-field:

| Field           | Type             | Required | Notes                                                                                     |
|-----------------|------------------|----------|-------------------------------------------------------------------------------------------|
| `ism_version`   | integer          | yes      | Must equal `1`. Future versions add new schema variants without breaking v1.              |
| `name`          | string           | yes      | Slug. Regex `^[a-z][a-z0-9_-]*$`. Used as the registry key and the filename stem.         |
| `display_name`  | string           | yes      | Non-empty. The user-facing label.                                                         |
| `category`      | string (enum)    | yes      | One of: `forge`, `ticketing`, `comms`, `vault`, `ide`.                                    |
| `summary`       | string           | yes      | One-line description. Non-empty.                                                          |
| `provides`      | list of strings  | yes      | Capability tokens. Non-empty. Each token regex `^[a-z][a-z0-9_.-]*$`.                     |
| `detection`     | list of objects  | yes      | Detection rules, discriminated by `kind`. Non-empty. See §4.                              |
| `credentials`   | object           | no       | Hint for the welcomer. Fields: `env_vars: list[str]`, `auth_command: str`.                |
| `fallback`      | object           | no       | Shown when detection fails. Fields: `missing_message: str`, `install_url: str`.           |
| `handler_hint`  | string           | no       | Module path of the bonfire handler that will consume this integration when wired.         |

Frontmatter must be a YAML *mapping*; sequences or scalars at the top level are rejected. Unknown top-level keys are rejected — additions go through ISM v2.

## 4. Detection rules

A detection rule is a YAML mapping with a `kind` field. v1 defines four kinds. Each rule is independently evaluable; a scanner will eventually run all rules and aggregate the result. The `detection` list **must be non-empty**.

### 4.1 `kind: command`

```yaml
- kind: command
  command: gh
  args: ["--version"]   # optional, default []
  expect_exit: 0        # optional, default 0
```

Probe: invoke `command` with `args` and check the exit code matches `expect_exit`. Used to detect a CLI binary on `PATH`.

### 4.2 `kind: env_var`

```yaml
- kind: env_var
  name: GITHUB_TOKEN
  required: false       # optional, default false
```

Probe: read environment variable `name`. If `required: true`, the integration is considered unavailable when the variable is absent or empty. If `required: false`, the rule contributes informational signal (welcomer can prompt the user to set it) but does not gate availability.

### 4.3 `kind: file_match`

```yaml
- kind: file_match
  path: .git/config
  pattern: "github\\.com"   # optional regex
```

Probe: stat `path` relative to the project root. If `pattern` is set, also read the file and check the regex matches anywhere in the content. Useful for detecting which forge a repo is wired to (e.g., `github.com` in `.git/config`).

### 4.4 `kind: python_import`

```yaml
- kind: python_import
  module: lancedb
```

Probe: attempt `importlib.util.find_spec(module)` in the bonfire process. Used for vault backends and other Python-hosted integrations that ship as optional extras.

### 4.5 Future kinds

ISM v2 will be additive — new `kind` values will be supported without retiring v1 kinds. v1 readers reject unknown `kind` values; v2 readers accept the v1 set unchanged.

## 5. Capability tokens

The `provides` list declares which abstract capabilities an integration supports. Tokens are dotted-lowercase strings (`pr.open`, `issue.close`, `vector.upsert`). v1 does not lock the namespace — handlers and scanners decide which tokens they require for a given role binding. The bonfire-bundled adapters use these conventions, which we recommend for contributor adapters:

- **Forge:** `pr.open`, `pr.merge`, `pr.close`, `pr.review`, `pr.comment`, `branch.create`, `issue.close`.
- **Ticketing:** `ticket.create`, `ticket.update`, `ticket.close`, `ticket.comment`, `ticket.transition`.
- **Comms:** `message.post`, `thread.reply`, `mention.user`, `attachment.upload`.
- **Vault:** `vector.upsert`, `vector.query`, `record.get`, `record.delete`, `schema.migrate`.
- **IDE:** `config.read`, `mcp.list`, `memory.read`.

Adapters declare only the tokens they actually implement. Handlers consuming ISM look up adapters by required-capability set, not by name.

## 6. Markdown body conventions

The body is plain CommonMark. The future welcomer reads it; the loader exposes it raw on the `ISMDocument.body` field. Recommended structure:

```markdown
# {display_name}

## Overview
One or two paragraphs explaining what this integration does and when
to use it.

## Setup
1. Numbered steps the welcomer presents one at a time.
2. Steps may include code fences with shell commands; the welcomer
   can offer to run them.
3. Steps that prompt the user for a token MUST mention the relevant
   environment variable name from the frontmatter `credentials.env_vars`.

## Capabilities
A short paragraph per capability token from the frontmatter `provides`
list, describing the bonfire pipeline behavior the capability unlocks.

## Troubleshooting
Optional. Common error messages and the fix.
```

The body is informational in v1. The welcomer ticket (BON-729) defines a stricter contract for the `## Setup` section.

## 7. Validation rules

`ISMDocument(...)` validation runs at parse time and rejects:

1. `ism_version != 1`.
2. `name` not matching `^[a-z][a-z0-9_-]*$`.
3. `display_name` empty or whitespace-only.
4. `category` not one of `forge`, `ticketing`, `comms`, `vault`, `ide`.
5. `summary` empty.
6. `provides` empty, missing, or containing tokens that fail the regex.
7. `detection` empty or missing.
8. Any detection rule with an unknown `kind`.
9. Any detection rule missing required fields for its kind (`command` requires `command`; `env_var` requires `name`; `file_match` requires `path`; `python_import` requires `module`).
10. Unknown top-level frontmatter keys.
11. Unknown keys inside `credentials`, `fallback`, or any detection rule.
12. Frontmatter that is not a YAML mapping at the top level.

The loader's `load(name)` is **total** — it returns `None` on any failure (missing file, malformed YAML, schema violation) and logs at WARNING. The loader's `validate(name)` is **strict** — it raises `ISMSchemaError` describing the first violation. This split mirrors `bonfire.persona.loader.PersonaLoader` and lets the runtime keep going while authoring tools surface failures hard.

## 8. Two-tier discovery

The `ISMLoader` is constructed with two directories:

- **`builtin_dir`** — the bundled adapters under `src/bonfire/integrations/builtins/` in the installed bonfire wheel.
- **`user_dir`** — the project-local override directory, conventionally `.bonfire/integrations/` at the project root.

Lookup order: `user_dir` is searched first, then `builtin_dir`. The user-dir copy wins on name collision. This is how a user replaces the bundled GitHub adapter with a fork that adds a custom field (without forking the framework).

`available()` returns the deduplicated, sorted union of names from both directories.

## 9. Worked example — forge

```yaml
---
ism_version: 1
name: github
display_name: GitHub
category: forge
summary: GitHub forge for pull-request lifecycle and issue closing.
provides:
  - pr.open
  - pr.merge
  - pr.review
  - issue.close
detection:
  - kind: command
    command: gh
    args: ["--version"]
  - kind: env_var
    name: GITHUB_TOKEN
    required: false
  - kind: file_match
    path: .git/config
    pattern: "github\\.com"
credentials:
  env_vars:
    - GITHUB_TOKEN
    - GH_TOKEN
  auth_command: gh auth login
fallback:
  missing_message: "Install the GitHub CLI to enable GitHub forge integration."
  install_url: "https://cli.github.com"
handler_hint: bonfire.handlers.bard
---
# GitHub

## Overview
The GitHub adapter wires bonfire's publish and close stages to the
`gh` CLI.

## Setup
1. Install the GitHub CLI from <https://cli.github.com>.
2. Run `gh auth login` and complete the flow.
3. Verify with `gh auth status`.

## Capabilities
- **pr.open** — Bard opens a pull request from the warrior's branch.
- **pr.merge** — Herald merges after the Wizard approves.
- **pr.review** — Wizard posts a structured review on the PR diff.
- **issue.close** — Herald closes the linked issue when merge lands.
```

## 10. Worked example — ticketing

```yaml
---
ism_version: 1
name: linear
display_name: Linear
category: ticketing
summary: Linear ticketing via the Linear MCP server.
provides:
  - ticket.update
  - ticket.close
  - ticket.comment
detection:
  - kind: file_match
    path: .mcp.json
    pattern: "linear"
  - kind: env_var
    name: LINEAR_API_KEY
    required: false
credentials:
  env_vars:
    - LINEAR_API_KEY
  auth_command: ""
fallback:
  missing_message: "Wire the Linear MCP server in .mcp.json or set LINEAR_API_KEY."
  install_url: "https://linear.app/developers"
handler_hint: bonfire.handlers.herald
---
# Linear

## Overview
Linear is consumed via its MCP server. Bonfire's Herald handler closes
tickets when a PR merges and posts comments at stage transitions.

## Setup
1. Add the Linear MCP server to your `.mcp.json`.
2. Authenticate against your Linear workspace when the MCP first runs.
3. (Optional) Set `LINEAR_API_KEY` for non-MCP fallback paths.

## Capabilities
- **ticket.update** — Herald updates ticket state at stage transitions.
- **ticket.close** — Herald moves the ticket to Done on merge.
- **ticket.comment** — Herald posts a brief PR-link comment when the
  pipeline completes.
```

## 11. Non-goals for v1

- **Detection-rule execution.** The scanner that actually runs `command` / `env_var` / `file_match` / `python_import` rules ships in BON-727. v1 defines the schema; the runner ships separately so its security model (subprocess sandboxing, timeouts, privilege boundaries) gets its own review.
- **Welcomer step semantics.** The body's `## Setup` section is informational in v1. BON-729 defines the interactive contract.
- **Handler binding.** Bard, Herald, and future stage handlers do not yet read the configured ISM out of `bonfire.toml`. BON-730 adds that wiring.
- **ISM v2.** New detection kinds, capability vocabulary, schema fields, and welcomer step types are deliberately out of scope. v2 will be additive over v1.

## 12. Versioning policy

- **Major version (`ism_version`).** Bumped only when an existing field's meaning changes or a v1 document would no longer parse.
- **Additive changes.** New detection kinds, new optional fields, new capability tokens — all additive, all non-breaking, all stay on `ism_version: 1` until they accumulate enough churn to justify a v2 cut.
- **Bonfire compatibility.** A bonfire release lists the ISM versions it understands. The loader rejects future `ism_version` values it does not recognize (logged at WARNING from `load()`, raised from `validate()`).

## 13. References

- Persona two-tier loader as architectural parallel: `src/bonfire/persona/loader.py`.
- Front Door scanner shape: `src/bonfire/onboard/scanners/mcp_servers.py`.
- Protocol seam discipline: `src/bonfire/protocols.py`.
- ADR-001 naming vocabulary: `docs/adr/ADR-001-naming-vocabulary.md`.
