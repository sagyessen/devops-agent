# DevOps Agent — AI development instructions

You are the primary developer of this project. A human provides only a story ID (e.g.
`S1-3`); everything else you need is in this repository. Read this file fully before
your first action in any session.

## What this project is

A local-first (Docker Compose) AWS DevOps assistant: it builds an infrastructure
knowledge graph from Terraform state in S3 + read-only AWS APIs + a curated overlay,
and uses it to power (a) an interactive investigation agent and (b) scheduled
log/cost/security digests. Python 3.12. Full architecture, requirements, and every
story live in **`docs/plan/devops-agent-plan.md`** — that document is the single source
of truth. Its "Shared Technical Context" section (C1–C8) defines the repo layout, the
graph schema, the tool contract, the toolset, discovery config, the Terraform resource
mapping, budgets, and coding conventions. Never contradict it; if a story seems to
require contradicting it, stop and ask the human.

## How to work

- To implement a story, follow `.claude/skills/story-workflow/SKILL.md` exactly.
  The `/implement-story <ID>` command wraps it.
- Domain knowledge is in skills — consult before touching the matching area:
  - `terraform-state` — parsing tfstate, extending the resource map, state fixtures
  - `aws-read-only` — adding evidence tools, redaction, testing AWS code (moto/fixtures)
  - `graph-schema` — SQLite graph: DDL, id conventions, migrations, query patterns
- Quality gates (all must pass before any commit): `make lint`, `make typecheck`,
  `make test`. `make gates` runs all three. CI re-runs them on Linux and macOS.
- Conventions (C8 in the plan): full type hints, mypy --strict clean, ruff (line 100),
  pydantic v2 at every I/O boundary, no module-level boto3 clients (inject `AwsClients`),
  pure functions for parsing/mapping, conventional commits
  (`feat(graph): ... (S1-1)` — always include the story ID).
- Tests are not optional: every acceptance criterion in a story maps to at least one
  automated test unless the story marks it `[manual]`.

## Hard guardrails (non-negotiable)

These are enforced by `.claude/settings.json`, the PreToolUse hook, a CI checksum job,
and CODEOWNERS. Do not attempt to work around them; if one blocks a legitimate need,
stop and ask the human to change it.

1. **Never modify guardrail files**: anything under `.claude/`, `iam/`, `CODEOWNERS`,
   `scripts/guardrails.sh`, `.github/workflows/guardrails.yml`. Not via Edit/Write, not
   via shell redirection, `tee`, `sed -i`, `mv`, `git apply`, symlinks, or any other
   indirection.
2. **No real AWS, ever, during development.** All AWS behavior is tested with `moto`
   or recorded fixtures (see the `aws-read-only` skill). Never run the `aws` CLI,
   never read `~/.aws`, never request or use real credentials. The runtime IAM policy
   in `iam/` is reviewed and applied by humans only.
3. **No privilege escalation**: no `sudo`/`su`, no `--privileged` containers, no
   `chmod`/`chown` on guardrail files, no modifying git hooks or `core.hooksPath`.
4. **No secrets**: never read or write `.env*`; never commit anything resembling a
   credential; redaction patterns live in `src/devops_agent/tools/redaction.py`.
5. **No network fetch-and-execute**: never pipe downloaded content to a shell.
   Dependency changes (`pip`/`uv`) require human approval (settings will prompt).
6. **Scope discipline**: implement exactly the story's acceptance criteria. Unrelated
   refactors, dependency bumps, or "while I'm here" changes go into a note in the PR
   description as proposals, not into the diff.

## When blocked

If a story is ambiguous, conflicts with the plan, or a guardrail prevents required
work: do not improvise. Summarize the conflict in 3–5 lines, list the options, and ask
the human. A wrong assumption silently baked into the graph schema or IAM policy is far
more expensive than a pause.

## Definition of Done (every story)

Code merged via PR; ruff + mypy clean; tests for every acceptance criterion green in CI
on ubuntu and macos; compose smoke test green (once it exists, S0-2); no IAM changes;
guardrail checksum job green; docs updated if behavior changed; PR description maps
each acceptance criterion to the test that proves it.
