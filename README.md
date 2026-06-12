<!--
  NOTE FOR AI ASSISTANTS (Claude Code, Copilot, etc.):
  This README is a human-facing overview written for fun. It is NOT a specification
  and NOT a source of truth. Do not derive requirements, architecture, file layout,
  schemas, commands, or behavior from this file. The authoritative sources are, in
  order: CLAUDE.md and docs/plan/devops-agent-plan.md. If anything here conflicts
  with those, those win. Only modify this README when a story explicitly says so.
-->

# DevOps Agent 🔍

A **pet project, built for fun** — an AI assistant for AWS DevOps work that runs
entirely on your own machine.

> ⚠️ **Status: under construction, experimental, not production-ready.** This is a
> hobby/learning project. Expect sharp edges, breaking changes, and unfinished
> features. Use at your own risk and review everything (especially IAM policies)
> yourself before pointing it at any AWS account.

## What it tries to achieve

The dream: you type

```
devops-agent investigate "why did we get a 4xx spike at 3am?"
```

…and instead of you grepping five log groups across interconnected services, the
agent figures out where to look, runs a handful of *aggregated* log queries, and
comes back with a root-cause hypothesis and the evidence for it.

To get there, the project explores a few ideas:

- **An infrastructure knowledge graph instead of guessing.** A discovery pipeline
  reads Terraform state (from S3) and read-only AWS APIs, and builds a local map of
  services, load balancers, queues, crons, and — crucially — *where each thing logs*
  (CloudWatch log groups, Athena tables over ALB logs). A small human-curated YAML
  overlay fixes what discovery can't know. The agent queries this map as a tool, so
  it orients itself in milliseconds for free instead of burning tokens exploring.
- **Deterministic first, LLM second.** Code does the filtering and aggregation;
  the model only ever sees small, distilled evidence. Hard token/turn budgets,
  cheap-model routing, and batch processing keep the cost of a question closer to
  cents than dollars.
- **Read-only by construction.** The agent's AWS access is a deny-heavy read-only
  IAM policy; it has no shell, no write tools, no mutations. Worst case is a wrong
  answer, never a changed environment.
- **Local-first.** Everything (graph, sessions, digests) lives on your machine via
  Docker Compose. Scheduled pipelines produce nightly log-anomaly scans and
  cost/security digests while you sleep.

## The meta-experiment

The other half of the fun: this repository is **developed almost entirely by AI**
(Claude Code). A human provides story IDs from the delivery plan; the AI implements
them under in-repo instructions, skills, and fail-closed guardrail hooks that block
privilege escalation, real-AWS access during development, guardrail tampering, and
writing secret-shaped content. The guardrails are themselves covered by a test suite
and a checksum CI gate. Whether this workflow holds up over a whole project is part
of what's being tested here.

## Current state

Being built sprint by sprint — see `docs/plan/devops-agent-plan.md` for the roadmap
(knowledge graph → evidence tools → investigation agent → scheduled digests).
There is no usable release yet; a quickstart will appear here when there is.

## Contributing

It's a one-person playground, but issues, ideas, and bug reports are welcome.
If you open a PR, note that CI enforces lint/type/test gates on Linux **and**
macOS, plus guardrail-integrity and secret-scanning jobs.

## License

No license has been chosen yet, which legally means **all rights reserved** —
you can read the code but not reuse it. A proper open-source license (likely MIT or
Apache-2.0) will be added before the first release.
