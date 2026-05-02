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
  - pr.comment
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

The GitHub adapter wires bonfire's publish and close stages to the `gh`
CLI. It is the default forge for projects whose remote is hosted on
GitHub and serves as the reference implementation contributors copy
when adding new forge adapters.

## Setup

1. Install the GitHub CLI from <https://cli.github.com>.
2. Run `gh auth login` and complete the interactive flow.
3. Verify with `gh auth status`.
4. (Optional) Set `GITHUB_TOKEN` or `GH_TOKEN` for non-interactive
   environments such as CI runners.

## Capabilities

- **pr.open** — Bard opens a pull request from the warrior's branch.
- **pr.merge** — Herald merges the PR after the Wizard approves.
- **pr.review** — Wizard posts a structured review on the PR diff.
- **pr.comment** — Stage handlers post status comments on the PR.
- **issue.close** — Herald closes the linked issue when the merge lands.

## Troubleshooting

- `gh: command not found` — install the CLI per Setup step 1.
- `gh auth status` reports unauthenticated — re-run `gh auth login`.
- PR creation fails with a 401 — refresh the token, or set
  `GITHUB_TOKEN` to a personal-access token with `repo` scope.
