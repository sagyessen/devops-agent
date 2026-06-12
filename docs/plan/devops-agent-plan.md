# Project: AWS DevOps Agent — local-first investigation & analysis assistant

A locally-run (Docker Compose) agent that helps DevOps engineers investigate incidents
("why the 4xx spike at 3am?"), analyze logs across interconnected services, and produce
scheduled cost/security/log-anomaly digests — for AWS only in v1. It is built around an
**infrastructure knowledge graph** discovered primarily from **Terraform state in S3**,
enriched by read-only AWS APIs and a human-curated overlay. The repository itself is
prepared for AI-assisted development (CLAUDE.md, skills, hooks, permission guardrails).

---

## Assumptions (correct any that are wrong)

- A1. Single AWS organization; one or more AWS accounts; per-environment access via
  named AWS profiles or an assumable read-only role. v1 targets **one account per
  configured environment** (multi-account = config list of profiles, not org-crawling).
- A2. Terraform state lives in S3, JSON format, standard backend (optionally with
  DynamoDB locking — irrelevant to us, we only **read** state objects).
  Layout varies: `env/stack/terraform.tfstate` (multi-stack) or `env/terraform.tfstate`
  (mono-state). Both must work with zero code changes (config-only).
- A3. No X-Ray/OTel. Dependency edges come from Terraform references, AWS describe-call
  wiring, and the curated overlay.
- A4. Logs live in CloudWatch Logs (service logs) and S3-via-Athena (ALB/CloudFront/VPC
  flow logs, Glue catalog exists or tables are creatable by the user — the agent never
  creates Glue resources).
- A5. Runs on the engineer's machine (macOS or Linux) via Docker Compose. Native
  launchd/systemd packaging is explicitly deferred to a post-v1 epic.
- A6. 1–5 users per installation, single-tenant, no auth beyond loopback binding.
- A7. Anthropic API is the LLM provider. Sonnet-class model for the investigation loop,
  Haiku-class for high-volume summarization/triage, Batch API for digests. Model IDs are
  config values, never hardcoded.
- A8. Data sensitivity: log lines may contain PII/secrets. They stay on the local
  machine except the minimal excerpts sent to the Anthropic API; a redaction pass runs
  before any tool result reaches the model.

## Requirements

**Functional**
- F1. Interactive investigation: natural-language questions about errors, latency,
  spikes; agent plans, queries the knowledge graph, runs aggregated log queries across
  multiple services, and answers with cited evidence.
- F2. Infrastructure discovery: build/refresh the knowledge graph from Terraform state
  (S3) + AWS describe calls + Glue catalog; support multi-stack and mono-state layouts.
- F3. Curated overlay: human-owned YAML that adds/corrects nodes, edges, log mappings,
  and notes; always wins conflicts; agent proposes overlay entries, never writes them.
- F4. Log analysis tools: CloudWatch Logs Insights and Athena, aggregate-first, with
  hard output caps.
- F5. Cost analysis: Cost Explorer queries, top movers, anomaly heuristics, digest.
- F6. Security analysis: read Security Hub / GuardDuty / IAM Access Analyzer findings,
  summarize and prioritize.
- F7. Scheduled pipelines: nightly log-anomaly scan, daily cost digest, weekly security
  sweep — deterministic pre-processing + Batch API summarization.
- F8. Drift handling: each discovery run diffs the graph, reports changes, flags
  unmapped log sources.

**Non-functional**
- N1. Cost ceilings: per-investigation token budget (default 150k input / 8k output
  tokens, max 15 agent turns), enforced in code; Athena bytes-scanned cap per query;
  every LLM call logged with token counts and computed cost.
- N2. Security: read-only AWS access enforced by IAM (explicit denies), no mutation
  tools exposed to the model, no shell/Bash tool in the runtime agent, redaction of
  secrets-like patterns before model input, loopback-only API.
- N3. Self-protection: the AI development environment cannot edit its own guardrails
  (hooks + settings protected by hook, checksum CI gate, CODEOWNERS).
- N4. Local-first: all state (graph, sessions, audit log) in local volumes; works
  offline for graph queries; degrades gracefully without network.
- N5. Runs identically on macOS (Docker Desktop/OrbStack) and Linux (docker engine).
  CI tests on both OSes.
- N6. Latency: graph tools < 50 ms; typical investigation answer < 2 minutes.

**Interface type**: CLI (primary) + local REST API on loopback (for future UI) +
scheduled background pipelines. All inside Docker Compose.

## Recommended Stack

**Language: Python 3.12** — best-in-class AWS SDK (boto3), the Claude Agent SDK is
available in Python, Terraform state is plain JSON (trivial to parse), and DevOps teams
overwhelmingly read/write Python, which maximizes velocity for both humans and AI coding
agents. Docker Compose as the delivery vehicle removes Python's usual end-user
distribution pain — the image *is* the package.

**Key libraries/frameworks**
- `claude-agent-sdk` — interactive investigation loop (in-process MCP tools only).
- `anthropic` — direct API client for deterministic pipelines + Batch API digests.
- `boto3` — all AWS access (logs, athena, elbv2, ecs, lambda, glue, ce, securityhub,
  guardduty, s3 state reading).
- `pydantic` + `pydantic-settings` — config and tool I/O contracts.
- `typer` — CLI; `fastapi` + `uvicorn` — loopback API.
- `sqlite3` (stdlib, WAL mode) — knowledge graph, sessions, audit log. No server DB:
  single-writer discovery + many readers fits SQLite perfectly and keeps local-first.
- `ruff`, `mypy`, `pytest`, `moto` (AWS mocking), `pre-commit` — quality gates.

**Runner-up: Go** — rejected because there is no Agent SDK (hand-rolled tool loop ≈ +2–3
weeks), boto3/moto have no equally mature Go counterparts for this breadth of services,
and Go's single-binary distribution advantage is neutralized by the Docker Compose
decision.

**Model routing (config defaults)**: investigation loop = Sonnet-class; tool-side
summarization and pipeline triage = Haiku-class; digests = Batch API at 50% price;
system prompt + topology summary under prompt caching.

---

## System Design

### 1. High-level architecture

```
                    ┌────────────────────────── docker compose ─────────────────────────┐
                    │                                                                    │
 Terraform state ──▶│  discovery service ──writes──▶  SQLite graph  ◀──reads── agent     │
 (S3, read-only)    │  (scheduled / on-demand)        /data/graph.db          service    │
 AWS describe APIs ─▶│        ▲                            ▲                  (CLI+API)  │
 Glue catalog ──────▶│        │                            │                      │      │
                    │  overlay.yaml (human-edited, mounted read-only)               │      │
                    │                                                              ▼      │
                    │  scheduler service ──invokes──▶ pipelines ──▶ digests   Anthropic   │
                    │  (cron)                         (batch API)  /data/out  API (HTTPS) │
                    └────────────────────────────────────────────────────────────────────┘
 Evidence at investigation time: CloudWatch Logs Insights, Athena, Cost Explorer,
 Security Hub / GuardDuty — read-only boto3 calls from agent tools.
```

Boundaries: **core logic** (`graph/`, `discovery/`, `tools/`, `pipelines/`),
**interface layer** (`cli.py`, `api/`, `agent/` harness), **storage** (SQLite + files
under a single `/data` volume).

### 2. Component breakdown

| Module | Responsibility | Depends on |
|---|---|---|
| `graph/` | SQLite store: nodes, edges, log_sources, snapshots, changes; queries; topology summary | sqlite3 |
| `discovery/terraform_state.py` | List & parse `*.tfstate` under configured S3 prefixes; map resources→nodes/edges | boto3, graph |
| `discovery/aws_wiring.py` | Enrich: ALB→TG→ECS/EC2, Lambda event sources, tag harvesting | boto3, graph |
| `discovery/log_sources.py` | Map CloudWatch log groups & Glue/Athena tables to service nodes | boto3, graph |
| `overlay/` | Load curated YAML, validate, merge with precedence overlay > discovered | pydantic, graph |
| `tools/` | Read-only evidence tools behind a single contract (caps, redaction, audit) | boto3, graph |
| `agent/` | Claude Agent SDK harness: tool registration, system prompt, budget, sessions | claude-agent-sdk, tools |
| `pipelines/` | Deterministic scans + Batch API summarization → digests | anthropic, tools |
| `api/` + `cli.py` | Typer CLI, FastAPI loopback API | agent, pipelines |
| `settings.py` | Config precedence defaults → file → env → flags | pydantic-settings |

### 3. Process & service model

Docker Compose services (one image, different commands):
- `agent` — long-running FastAPI on `127.0.0.1:8765`; CLI runs via
  `docker compose run --rm agent devops-agent <cmd>` or a thin host wrapper script.
- `discovery` — one-shot job (`devops-agent discover run`), invoked by `scheduler` and
  on demand.
- `scheduler` — supercronic (or BusyBox crond) reading `config/crontab`: nightly scan,
  daily cost digest, weekly security sweep, daily discovery refresh.
Restart policy: `agent` `unless-stopped`; jobs are one-shot. Logs to stdout (Docker
captures) + structured JSONL audit at `/data/logs/`. Native launchd/systemd: deferred,
tracked as post-v1 epic E7.

### 4. Data & storage

Single named volume mounted at `/data`:
- `/data/graph.db` — SQLite (WAL). Tables: `nodes(id, kind, name, env, arn, attrs JSON,
  source, confidence, first_seen, last_seen)`, `edges(src, dst, kind, attrs, source,
  confidence)`, `log_sources(node_id, type cloudwatch|athena, locator, attrs)`,
  `snapshots(id, created_at, stats)`, `changes(snapshot_id, change_kind, entity, detail)`,
  `sessions(...)`, `llm_audit(ts, context, model, in_tokens, out_tokens, cost_usd)`.
- `/data/out/` — digests (markdown), proposed overlay diffs.
- `config/overlay.yaml` — host-mounted **read-only**; the app proposes edits as diff
  files in `/data/out/`, a human applies them.
Migrations: sequential SQL files in `src/devops_agent/graph/migrations/`, applied by
version table at startup. Schema changes only via new migration files.

### 5. Interfaces / IPC / API

- CLI verbs: `discover run|diff`, `graph show|query|summary`, `investigate "<question>"`
  (one-shot or `--repl`), `digest cost|security|logs`, `overlay propose|validate`.
- REST (loopback only): `POST /investigations`, `GET /investigations/{id}/events` (SSE
  stream of agent turns), `GET /graph/summary`, `GET /digests/latest`.
- Agent↔tools: in-process MCP tools via the Agent SDK (no external MCP servers, no
  Bash/filesystem tools registered).

### 6. Configuration

`config/default.yaml` (committed) → `config/local.yaml` (gitignored) → env vars
(`DEVOPS_AGENT_*`) → CLI flags. Key blocks: `aws` (profiles per env, region),
`discovery.terraform.backends[]` (`bucket`, `prefix`, `state_glob`, `env_from`,
`stack_from` — regex group extraction so both layouts are config-only),
`models` (loop/summarizer/batch model IDs), `budgets` (tokens, turns, athena bytes),
`schedule`, `redaction.patterns[]`.

### 7. Concurrency & performance

Async (asyncio) in the agent loop and API; boto3 calls via thread executor. SQLite WAL:
`discovery` is the only writer of graph tables; `agent` reads + writes only
sessions/audit. Graph queries are indexed lookups (<50 ms). Logs Insights/Athena are
asynchronous AWS jobs polled with timeout (default 60 s, config).

### 8. Security & privacy

- **AWS**: dedicated IAM role/profile per env using `iam/devops-agent-readonly.json`:
  Allow = describe/get/list for the touched services + `logs:StartQuery/GetQueryResults`
  + `athena:StartQueryExecution/GetQueryExecution/GetQueryResults` (scoped to one
  workgroup) + `s3:GetObject/ListBucket` on state buckets and the Athena results prefix
  (the **only** write: `s3:PutObject` on `athena-results/*`) + `ce:Get*`,
  `securityhub:Get*/List*`, `guardduty:Get*/List*`.
  **Explicit Deny**: `iam:*`, `sts:AssumeRole` (except the designated read-only role
  ARNs), `organizations:*`, and all mutating verbs (`Create*`, `Put*` except the results
  prefix, `Delete*`, `Update*`, `Modify*`, `Attach*`, `Terminate*`). Explicit deny beats
  any future allow — the agent cannot escalate even if a policy is later widened by
  mistake. Athena workgroup config enforces `BytesScannedCutoffPerQuery`.
- **Runtime agent**: tool allowlist only (no Bash, no file write, no network fetch);
  every tool is read-only by construction; redaction (`aws_secret`, `authorization:`,
  JWT, key=value secret patterns) runs in the tool contract before results reach the
  model; audit JSONL of every tool call and LLM call.
- **Credentials**: `ANTHROPIC_API_KEY` via env/`.env` (gitignored); AWS via mounted
  `~/.aws` read-only or env; nothing baked into images.
- **API**: binds 127.0.0.1 only; compose publishes `127.0.0.1:8765:8765`.
- **Dev-time AI guardrails**: see "AI-ready repository" section — hooks + settings deny
  self-modification and privileged commands.

### 9. Observability

`structlog` JSON logs to stdout; audit JSONL in `/data/logs/` rotated by size (10 MB ×
5); `devops-agent doctor` command validates config, AWS access (dry-run describes),
state bucket reachability, Anthropic key; per-session cost report printed at the end of
every investigation.

### 10. Error handling & resilience

Tool failures return structured `{ok:false, error_kind, hint}` to the model (it can
re-plan); AWS throttling → exponential backoff (botocore standard retry mode); budget
exceeded → graceful abort with partial findings + evidence so far; discovery failures
never corrupt the graph (write to staging tables, swap in one transaction); stale graph
(> configured age) → agent prepends a staleness warning to answers.

### 11. Packaging & distribution

Multi-stage Dockerfile (slim Python base, non-root user, `linux/amd64` + `linux/arm64`
buildx targets — arm64 covers Apple Silicon). Versioned image tags; `compose.yaml` +
`.env.example` + `config/default.yaml` are the install artifact. Host convenience
wrapper `bin/devops-agent` (shell) execs `docker compose run`. macOS note: Docker
Desktop/OrbStack required; file-watch and host networking differences are avoided by
loopback port publishing and named volumes. Native `.pkg`/Homebrew + `.deb`/systemd:
epic E7, post-v1.

### 12. Testing strategy

- Unit: parsers, mappers, contract caps, redaction (pure functions, no AWS).
- Integration: `moto` for boto3 services it supports; recorded-fixture JSON for the
  rest (Cost Explorer, Logs Insights responses) behind a fake boto3 client.
- Agent evals: canned scenarios (fixtures simulating the 4xx-spike case) with scripted
  fake tools; assert the agent reaches the correct root cause and stays under budget.
- CI matrix: GitHub Actions `ubuntu-latest` + `macos-latest` for lint/type/unit/
  integration; image build + compose smoke test on ubuntu; guardrail checksum job.

---
## Shared Technical Context (referenced by all stories — keep this section authoritative)

> AI implementers: read this section plus `CLAUDE.md` before any story. Stories below
> deliberately do not repeat it.

**C1 — Repository layout**
```
devops-agent/
├── CLAUDE.md                      # AI working instructions (see Sprint 0)
├── .claude/
│   ├── settings.json              # tool permissions (deny-first)
│   ├── hooks/pre_tool_guard.py    # PreToolUse guard (blocking)
│   ├── hooks/manifest.sha256      # checksums of guard files
│   └── skills/
│       ├── terraform-state/SKILL.md
│       ├── aws-read-only/SKILL.md
│       └── graph-schema/SKILL.md
├── compose.yaml  Dockerfile  .env.example  bin/devops-agent
├── config/{default.yaml, local.example.yaml, overlay.example.yaml, crontab}
├── iam/devops-agent-readonly.json
├── pyproject.toml  .pre-commit-config.yaml  CODEOWNERS
├── src/devops_agent/
│   ├── cli.py  settings.py
│   ├── api/{app.py, routes.py}
│   ├── graph/{schema.sql → migrations/, store.py, queries.py, summary.py, diff.py}
│   ├── discovery/{terraform_state.py, aws_wiring.py, log_sources.py, runner.py}
│   ├── overlay/{model.py, loader.py, propose.py}
│   ├── tools/{contract.py, redaction.py, graph_tools.py, logs_insights.py,
│   │          athena.py, changes.py, cost.py, security.py}
│   ├── agent/{harness.py, prompts.py, budget.py, sessions.py}
│   └── pipelines/{log_scan.py, cost_digest.py, security_sweep.py, batch.py}
└── tests/{unit/, integration/, evals/, fixtures/}
```

**C2 — Graph schema (DDL, migration 0001)**
```sql
CREATE TABLE nodes(
  id TEXT PRIMARY KEY,            -- "{env}:{kind}:{name}"
  kind TEXT NOT NULL,             -- service|alb|target_group|lambda|queue|db|log_group|athena_table|stack|cron|other
  name TEXT NOT NULL, env TEXT NOT NULL, arn TEXT,
  attrs TEXT NOT NULL DEFAULT '{}',          -- JSON
  source TEXT NOT NULL,           -- terraform|aws_api|glue|overlay|naming
  confidence REAL NOT NULL DEFAULT 1.0,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE edges(
  src TEXT NOT NULL, dst TEXT NOT NULL,
  kind TEXT NOT NULL,             -- routes_to|targets|calls|consumes|logs_at|member_of|deployed_by|triggers
  attrs TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (src, dst, kind));
CREATE TABLE log_sources(
  node_id TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN ('cloudwatch','athena')),
  locator TEXT NOT NULL,          -- log group name | "db.table"
  attrs TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(node_id, type, locator));
CREATE TABLE snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, stats TEXT);
CREATE TABLE changes(snapshot_id INTEGER, change_kind TEXT, entity TEXT, detail TEXT);
CREATE TABLE llm_audit(ts TEXT, context TEXT, model TEXT, in_tokens INT, out_tokens INT,
  cached_tokens INT, cost_usd REAL, session_id TEXT);
CREATE TABLE sessions(id TEXT PRIMARY KEY, created_at TEXT, question TEXT,
  status TEXT, turns INT, total_cost_usd REAL, transcript TEXT);
```
Indexes on `nodes(env,kind)`, `nodes(name)`, `edges(src)`, `edges(dst)`.

**C3 — Tool contract** (`tools/contract.py`)
Every model-visible tool is a function decorated `@evidence_tool(name, description,
input_model: pydantic)` returning `ToolResult`:
```python
class ToolResult(BaseModel):
    ok: bool
    data: Any            # JSON-serializable; post-truncation
    truncated: bool = False
    row_count: int | None = None
    source: str          # e.g. "athena:wg-devops-agent", "graph"
    query: str | None    # exact query executed (for citation)
    elapsed_ms: int
    error_kind: str | None = None   # throttled|timeout|not_found|denied|budget|invalid
    hint: str | None = None         # actionable re-plan hint for the model
```
The decorator centrally enforces: max 50 rows AND max 4096 bytes of `data` (truncate +
set flag), redaction via `redaction.py`, audit JSONL line, wall-clock timeout. Tools
never raise to the model; they return `ok:false`.

**C4 — Model-visible toolset (final list for v1)**
Graph (local, free): `get_service_map(env)`, `get_log_sources(service)`,
`trace_dependencies(service, direction, depth<=3)`, `get_recent_changes(env, days<=14)`.
Evidence (AWS): `query_logs(log_group, insights_query, start, end)`,
`query_athena(sql, start, end)` (SELECT-only, LIMIT injected),
`get_cost(group_by, start, end, filter)`, `get_security_findings(severity_min, days)`.
No other tools. No Bash, no file tools, no web tools in the runtime agent.

**C5 — Terraform state discovery config (must support both layouts)**
```yaml
discovery:
  terraform:
    backends:
      - bucket: acme-tf-states
        region: eu-central-1
        prefix: ""                      # scan whole bucket if empty
        state_glob: "*/**/terraform.tfstate"   # also matches env/terraform.tfstate
        env_from:  "^(?P<env>[^/]+)/"          # regex on object key
        stack_from: "^[^/]+/(?P<stack>.+)/terraform.tfstate$"  # optional; if no match → stack = "root"
```
Each matched object = one stack node; mono-state layout simply yields a single stack
per env (`stack=root`). Parser reads state JSON `resources[]` (schema version 4),
including `module` children.

**C6 — Terraform resource→graph mapping (initial table; extend in
`terraform_state.py:RESOURCE_MAP`)**
`aws_lb→alb`, `aws_lb_target_group→target_group` (+edge alb routes_to tg from
`aws_lb_listener`/`aws_lb_listener_rule`), `aws_ecs_service→service` (+edge tg targets
service via `load_balancer.target_group_arn`), `aws_lambda_function→lambda`,
`aws_lambda_event_source_mapping→edge consumes`, `aws_sqs_queue→queue`,
`aws_db_instance|aws_rds_cluster→db`, `aws_cloudwatch_log_group→log_group` (+
`logs_at` edge when `awslogs-group` appears in an ECS task definition or Lambda
`logging_config`), `aws_glue_catalog_table→athena_table`,
`aws_cloudwatch_event_rule(schedule)→cron` (+`triggers` edge),
`aws_ecs_task_definition→attrs on service`. Everything else → `other` node so nothing
is silently dropped. All nodes get `member_of` edge to their stack node.

**C7 — Budgets (config defaults)** `budgets.max_turns=15`,
`budgets.max_input_tokens=150000`, `budgets.max_output_tokens=8000`,
`budgets.athena_bytes_scanned=1073741824` (1 GiB, also set on the workgroup),
`budgets.tool_timeout_s=60`. `budget.py` tracks cumulative usage from SDK messages,
warns the model at 80% via injected system note, hard-stops at 100% with a final
"summarize findings so far" turn.

**C8 — Coding conventions** Python 3.12, full type hints, `ruff` (line 100) + `mypy
--strict` clean, pydantic v2 models for all I/O boundaries, no module-level boto3
clients (inject via `AwsClients` factory for testability), pure functions for parsing/
mapping, every public function unit-tested, conventional commits.

**Definition of Done (applies to every story)**: code merged via PR; ruff+mypy clean;
unit/integration tests added and green in CI on ubuntu **and** macos runners; compose
smoke test green; no IAM permissions added beyond `iam/devops-agent-readonly.json`;
guardrail checksum job green; README/docs updated if behavior changed; acceptance
criteria each verified by an automated test unless marked [manual].

---

## Delivery Plan

**Epics**
- **E1 — Foundations & AI-ready repository**: scaffold, CI matrix, compose skeleton,
  CLAUDE.md/skills/hooks/permissions, IAM baseline, config system.
- **E2 — Infrastructure knowledge graph**: SQLite store, Terraform-state discovery,
  AWS wiring & log-source enrichment, overlay, drift, topology summary.
- **E3 — Read-only evidence tools**: tool contract, Logs Insights, Athena, graph tools,
  changes, cost, security findings.
- **E4 — Interactive investigation agent**: Agent SDK harness, prompts & caching,
  budgets, sessions, CLI/REPL.
- **E5 — Scheduled analysis & digests**: log-anomaly scan, cost digest, security sweep,
  Batch API, scheduler.
- **E6 — Interfaces, quality & release**: loopback API, eval harness, observability,
  docs, release packaging.
- (E7 — native launchd/systemd + Homebrew/deb packaging: post-v1, not scheduled here.)

Sprint length: 2 weeks. Velocity target ≈ 20 points (1 dev + AI assistance).
---

### Sprint 0 — Walking skeleton & AI-ready repo (E1)

Goal: a cloneable repo where `docker compose run agent devops-agent doctor` works, CI is
green on both OSes, and an AI coding agent can develop safely under guardrails.

**S0-1 — Repo scaffold & quality gates (3 pts, deps: none)**
As a developer, I want a typed, linted Python project skeleton, so that every later
story lands on consistent rails.
- [ ] Layout per C1; `pyproject.toml` with deps from "Recommended Stack"; `src/` layout;
      `devops-agent --version` entry point via Typer.
- [ ] ruff + mypy(strict) + pytest configured; pre-commit runs ruff/mypy on commit.
- [ ] `settings.py` loads precedence default.yaml → local.yaml → `DEVOPS_AGENT_*` env →
      CLI flags (pydantic-settings); unit test proves precedence order.
- [ ] `tests/unit/test_settings.py` green.

**S0-2 — Dockerfile & compose skeleton (3 pts, deps: S0-1)**
As a user, I want one command to bring the stack up, so that install equals
`docker compose up`.
- [ ] Multi-stage Dockerfile, non-root `appuser`, image < 400 MB; buildx targets
      linux/amd64 + linux/arm64.
- [ ] `compose.yaml` defines `agent` (FastAPI placeholder on 127.0.0.1:8765),
      `discovery` (one-shot, `profiles: ["jobs"]`), `scheduler` (supercronic +
      `config/crontab`); named volume `data:/data`; `~/.aws` and `config/overlay.yaml`
      mounted read-only; `.env.example` documents `ANTHROPIC_API_KEY`, `AWS_PROFILE`.
- [ ] `bin/devops-agent` host wrapper execs `docker compose run --rm agent devops-agent "$@"`.
- [ ] Smoke test script `tests/smoke.sh`: compose up, curl `/healthz`, compose down.
- Platform notes: publish ports as `127.0.0.1:8765:8765` (works on Docker Desktop and
  Linux); document OrbStack/Docker Desktop requirement for macOS in README.

**S0-3 — CI matrix (3 pts, deps: S0-1, S0-2)**
As a maintainer, I want every PR verified on Linux and macOS, so that dual-OS parity is
enforced from day one.
- [ ] GitHub Actions: jobs `quality` (ruff, mypy) and `test` (pytest) on matrix
      [ubuntu-latest, macos-latest], Python 3.12.
- [ ] Job `image`: buildx build + `tests/smoke.sh` on ubuntu.
- [ ] Job `guardrails`: recompute sha256 of `.claude/hooks/*`, `.claude/settings.json`,
      `iam/*.json` and diff against `.claude/hooks/manifest.sha256`; fail on mismatch.
- [ ] Required checks documented in CONTRIBUTING.md.

**S0-4 — AI working-instructions pack: CLAUDE.md + skills (5 pts, deps: S0-1)**
As an AI coding agent, I want complete project context in-repo, so that stories can be
implemented without extra prompting.
- [ ] `CLAUDE.md` contains: project one-paragraph summary; repo map (C1); commands
      (`make test|lint|typecheck|smoke`, compose usage); coding conventions (C8);
      pointer to plan file and Shared Technical Context; explicit guardrail section:
      "never edit `.claude/`, `iam/`, `CODEOWNERS`; never run `aws` mutating commands,
      `terraform apply|destroy`, `sudo`, `docker --privileged`; AWS access in dev only
      via moto/fixtures, never real credentials".
- [ ] Skills per C1: `terraform-state` (state JSON schema v4 essentials, RESOURCE_MAP
      extension how-to, example state fixture), `aws-read-only` (how to add a tool under
      contract C3, redaction rules, moto patterns), `graph-schema` (C2 DDL, id
      conventions, query examples). Each SKILL.md ≤ 150 lines with frontmatter
      name/description.
- [ ] [manual] A fresh Claude Code session given only "implement story S1-2" locates all
      needed context from the repo.

**S0-5 — Dev-time guardrail hooks & permissions (5 pts, deps: S0-4)**
As a security owner, I want the AI dev environment unable to modify its own guardrails
or run privileged commands, so that it cannot escalate locally or in AWS.
- [ ] `.claude/settings.json`: deny Edit/Write on `.claude/**`, `iam/**`, `CODEOWNERS`,
      `.github/workflows/guardrails*`; deny Bash patterns `aws *`, `terraform *`,
      `sudo *`, `docker * --privileged*`, `curl *|*sh`; allow project-scoped
      Read/Edit/Write, `make *`, `pytest *`, `ruff *`, `mypy *`, `git *` (no push),
      `docker compose *` (no --privileged).
- [ ] `pre_tool_guard.py` PreToolUse hook (defense-in-depth behind settings): blocks
      (exit 2 + reason) any tool input touching protected paths incl. via `../`,
      symlink, or `git apply` patch text; blocks regexes for `aws iam|sts|organizations`,
      mutating aws verbs, `terraform (apply|destroy)`, `chmod` on hooks; unit-tested
      against ≥ 12 bypass attempts (path traversal, quoting, env-var indirection,
      heredoc writes).
- [ ] `manifest.sha256` generated; `make guardrails-verify` target; CI job from S0-3
      consumes it.
- [ ] `CODEOWNERS`: `.claude/`, `iam/`, `.github/` require human owner review.
- [ ] Rationale doc `docs/security-guardrails.md`: threat model = "coding agent
      attempts privilege escalation"; layers = settings deny → hook → checksum CI →
      CODEOWNERS human gate; explains why hook cannot be self-disabled (file protected
      by the layers above it).

**S0-6 — AWS read-only IAM baseline (3 pts, deps: none)**
As a security owner, I want the runtime agent's AWS permissions defined once, so that
read-only is enforced by AWS, not by app code.
- [ ] `iam/devops-agent-readonly.json` per System Design §8 (Allow list + explicit Deny
      list incl. `iam:*`, `sts:AssumeRole` NotResource designated ARNs,
      `organizations:*`, mutating verbs).
- [ ] `iam/athena-workgroup.md`: required workgroup config (results bucket prefix,
      BytesScannedCutoffPerQuery from C7, enforce workgroup config = true).
- [ ] `docs/aws-bootstrap.md`: create role/profile per env, trust policy for the
      engineer's principal, validation via `devops-agent doctor` [manual].
- [ ] Policy linted with IAM policy simulator or `parliament` in CI.

**S0-7 — `doctor` command (2 pts, deps: S0-1, S0-6)**
As a user, I want a preflight check, so that misconfiguration is caught before first use.
- [ ] `devops-agent doctor` validates: config parse; Anthropic key present (no call);
      AWS identity per env (`sts:GetCallerIdentity`); state buckets listable; Athena
      workgroup exists; graph DB writable. Prints PASS/FAIL table, exit code reflects.
- [ ] Integration test with moto for the AWS checks.

*Sprint 0 total: 24 pts (front-loaded; several stories are configuration-heavy and
AI-parallelizable).*

---

### Sprint 1 — Knowledge graph core from Terraform state (E2)

Goal: `devops-agent discover run` builds a queryable graph from real state files in S3,
regardless of layout.

**S1-1 — SQLite graph store (5 pts, deps: S0-1)**
As a developer, I want a typed graph store, so that all components share one persistence
layer.
- [ ] Migration runner (sequential SQL files, version table); migration 0001 = C2 DDL +
      indexes; WAL mode + busy_timeout set on connect.
- [ ] `store.py`: `upsert_nodes/edges/log_sources(batch)`, `begin_snapshot()/commit_snapshot(stats)`
      using staging-table swap (System Design §10); `queries.py`: `nodes_by(env,kind)`,
      `neighbors(node_id, kind, direction, depth≤3)`, `log_sources_for(node_id)`.
- [ ] Upserts preserve `first_seen`, update `last_seen`; conflict rule: higher
      confidence wins, `overlay` source always wins (enforced here, used in S2-3).
- [ ] Unit tests incl. concurrent reader-during-write (WAL) test.

**S1-2 — Terraform backend scanner (3 pts, deps: S0-1)**
As an operator, I want state files found from config alone, so that multi-stack and
mono-state projects both work without code changes.
- [ ] Implements C5: list S3 objects per backend, match `state_glob`, extract env/stack
      via `env_from`/`stack_from` regexes; missing stack match → `root`.
- [ ] Returns `[StateRef(bucket, key, env, stack, last_modified, size)]`; skips objects
      > 50 MB with warning; supports paginated listing.
- [ ] Unit tests: fixture key sets for layout A (`prod/networking/terraform.tfstate`…)
      and layout B (`prod/terraform.tfstate`), plus noise keys; moto S3 integration test.

**S1-3 — State parser & resource mapping (8 pts, deps: S1-1, S1-2)**
As an engineer, I want Terraform resources turned into graph nodes/edges, so that the
agent knows what exists and how it's wired.
- [ ] Parse state schema v4 incl. nested modules; tolerate unknown resource types
      (→ `other` node) and malformed instances (log + skip, never abort the run).
- [ ] Implement RESOURCE_MAP per C6 incl. the listed cross-resource edges
      (listener→routes_to, ecs `load_balancer`→targets, event source mapping→consumes,
      awslogs-group→logs_at, schedule rule→triggers); stack node + `member_of` edges.
- [ ] Node ids per C2 convention; `source="terraform"`, confidence 1.0; tags copied
      into `attrs.tags`.
- [ ] Fixtures: two real-shaped state files (multi-stack ECS+ALB+SQS+RDS; mono-state
      with Lambda+ALB) committed under `tests/fixtures/tfstate/`; golden-file tests
      assert exact node/edge sets.

**S1-4 — Discovery runner & CLI (3 pts, deps: S1-3)**
As an operator, I want one command to (re)build the graph, so that discovery is
repeatable and schedulable.
- [ ] `runner.py` orchestrates scan→parse→staged write→snapshot; per-backend errors
      isolated; summary stats (nodes/edges by kind, parse errors) stored in snapshot.
- [ ] `devops-agent discover run [--env X] [--backend N]`; non-zero exit on total
      failure only; JSON `--output json` mode.
- [ ] Wired as the `discovery` compose service command; scheduler crontab entry (daily)
      added but commented until Sprint 5.

**S1-5 — Graph CLI (2 pts, deps: S1-1)**
As an engineer, I want to inspect the graph, so that I can trust and debug discovery.
- [ ] `graph show <node-id|name>` (node + edges + log sources), `graph query --env
      --kind`, `graph stats`; table and `--output json` formats.
- [ ] Integration test over a discovered fixture graph.

*Sprint 1 total: 21 pts.*

---

### Sprint 2 — Enrichment, overlay & drift (E2)

Goal: the graph reflects live wiring and human knowledge; changes between runs are
visible; a compact topology summary exists for prompting.

**S2-1 — AWS wiring enrichment (5 pts, deps: S1-4)**
As an engineer, I want runtime wiring confirmed from AWS APIs, so that the graph is
correct even where state lags reality.
- [ ] `aws_wiring.py`: elbv2 describe (load balancers, listeners, target groups, target
      health → routes_to/targets edges, `source="aws_api"`); ecs list/describe services
      (cluster, task def log config → logs_at); lambda list (event source mappings →
      consumes; logging config → logs_at).
- [ ] Merge semantics: confirms (raises confidence to 1.0) or adds edges; never deletes
      terraform/overlay data; conflicts recorded in `changes`.
- [ ] moto integration tests for elbv2/ecs/lambda paths; throttling retry test.

**S2-2 — Log-source mapper (5 pts, deps: S1-4)**
As an engineer, I want every service linked to its logs, so that investigations know
where to look.
- [ ] CloudWatch: DescribeLogGroups; match to service nodes by (1) logs_at edges already
      present, (2) tags, (3) configurable naming regexes (`naming_rules` in config);
      matches by naming get `confidence 0.6, source="naming"`.
- [ ] Athena: Glue GetTables over configured databases; map tables to alb/cloudfront/
      vpc-flow log types via table properties/location heuristics; attach to the owning
      alb node where determinable, else to env node.
- [ ] Unmapped log groups/tables listed in snapshot stats and `discover diff` output.
- [ ] Tests with moto (logs, glue).

**S2-3 — Curated overlay (3 pts, deps: S1-1)**
As an engineer, I want a YAML file to correct and enrich the graph, so that knowledge
discovery can't infer (e.g. nginx→backend proxying) is captured once.
- [ ] `overlay/model.py`: pydantic schema — `nodes[]`, `edges[]`, `log_sources[]`,
      `notes{node_id: text}`, `ignore[]` (node ids or globs to exclude from graph).
- [ ] Loader validates and merges with `source="overlay"`, confidence 1.0, wins all
      conflicts (uses S1-1 rule); `ignore` removes nodes + incident edges post-merge.
- [ ] `devops-agent overlay validate` command; `config/overlay.example.yaml` documents
      every field with the nginx→backend example.
- [ ] Unit tests: override beats aws_api beats terraform beats naming; ignore globs.

**S2-4 — Drift diff & change report (3 pts, deps: S1-4)**
As an engineer, I want to see what changed between discovery runs, so that the map never
silently rots.
- [ ] `diff.py` compares latest two snapshots → added/removed/changed nodes & edges,
      new unmapped log sources; persisted to `changes`.
- [ ] `devops-agent discover diff` renders report; markdown copy written to
      `/data/out/discovery-diff-<ts>.md`.
- [ ] Golden test: fixture graphs v1 vs v2.

**S2-5 — Topology summary generator (3 pts, deps: S2-1..S2-3)**
As the agent, I want a compact always-true orientation block, so that investigations
start oriented at zero marginal token cost.
- [ ] `summary.py`: deterministic markdown per env — request path chains (alb→…→db),
      async paths (queue/cron), log source index, overlay notes; hard cap 800 tokens
      (tiktoken-free heuristic: ≤ 3200 chars), stable ordering (diff-friendly).
- [ ] `graph summary [--env]` CLI; regenerated at end of every discovery run and stored
      in snapshot.
- [ ] Golden-file test over fixture graph.

**S2-6 — Overlay proposals from drift (3 pts, deps: S2-2, S2-4)**
As an engineer, I want the tool to draft overlay entries for unmapped findings, so that
curation takes minutes, not hours.
- [ ] `overlay propose`: for unmapped log groups/tables and low-confidence naming
      matches, emit a ready-to-paste YAML snippet to `/data/out/overlay-proposal-<ts>.yaml`
      with commented rationale; never writes `config/overlay.yaml` (read-only mount).
- [ ] Pure-deterministic in this story (no LLM); unit-tested.

*Sprint 2 total: 22 pts.*
---

### Sprint 3 — Evidence tool layer (E3)

Goal: every AWS-touching capability the model will use exists as a capped, redacted,
audited, read-only tool — testable without the agent.

**S3-1 — Tool contract framework & redaction (5 pts, deps: S0-1)**
As a security owner, I want one chokepoint for all model-visible tools, so that caps,
redaction and audit can never be forgotten.
- [ ] `contract.py` implements C3 exactly: decorator, ToolResult, 50-row/4096-byte cap
      with `truncated=true`, wall-clock timeout (C7), audit JSONL line per call
      (`/data/logs/tool_audit.jsonl`).
- [ ] `redaction.py`: patterns for AWS access/secret keys, `Authorization:` headers,
      JWTs, `password|secret|token=`-style pairs, PEM blocks; replacement
      `«redacted:kind»`; configurable additions via `redaction.patterns`.
- [ ] Property test: no configured pattern survives in any ToolResult.data.
- [ ] Negative test: a tool that raises → `ok:false, error_kind`, audit still written.

**S3-2 — Graph tools (3 pts, deps: S2-5, S3-1)**
As the agent, I want free local orientation tools, so that planning costs no AWS calls.
- [ ] Implement C4 graph tools over `queries.py`; outputs compact JSON (ids, names,
      kinds, edge kinds, confidence, notes); `trace_dependencies` depth ≤ 3 enforced.
- [ ] `get_recent_changes` merges graph `changes` (last N days) — deploy-ish signals
      (taskdef revisions from S2-1 attrs, schedule rules) flagged.
- [ ] Each tool: docstring = model-facing description with one example call; unit tests.

**S3-3 — CloudWatch Logs Insights tool (5 pts, deps: S3-1)**
As the agent, I want aggregate-first log querying, so that evidence is cheap and small.
- [ ] `query_logs(log_group, insights_query, start, end)`: StartQuery/poll/GetResults
      with timeout; validates log group exists in graph log_sources (else
      `error_kind=not_found`, hint lists nearest matches).
- [ ] Query templates exposed in the tool description: error-count-by-pattern,
      top-messages, count-over-time(bin), latency-percentiles — model is instructed to
      prefer `stats` queries; raw-line queries auto-appended `| limit 50`.
- [ ] Time range required, max span 24 h per call (config).
- [ ] Integration tests with fake client fixtures (moto lacks Insights): recorded
      response shapes for the 4xx scenario.

**S3-4 — Athena tool (5 pts, deps: S3-1)**
As the agent, I want SQL over ALB/S3 logs, so that edge evidence is queryable.
- [ ] `query_athena(sql, start, end)`: SELECT-only (sqlglot or conservative regex
      gate: single statement, starts SELECT/WITH, no DDL/DML keywords); injects
      `LIMIT 200` if absent; runs in configured workgroup only; returns rows via
      GetQueryResults (capped by contract), plus `data_scanned_bytes` in `attrs`.
- [ ] Partition guard: if target table is partition-keyed by date and the SQL lacks a
      partition predicate, return `ok:false, error_kind=invalid, hint="add
      day/date partition filter"` — protects the bytes budget.
- [ ] Fake-client integration tests incl. cancellation on timeout.

**S3-5 — Cost tool (3 pts, deps: S3-1)**
As the agent, I want Cost Explorer access, so that "why did cost jump" is answerable.
- [ ] `get_cost(group_by∈{SERVICE,USAGE_TYPE,TAG:<key>}, start, end, filter?)` via
      ce:GetCostAndUsage daily granularity; returns top-20 groups + total + period-over-
      period delta computed in code.
- [ ] Fixture-based tests (CE not in moto): recorded response shapes.

**S3-6 — Security findings tool (3 pts, deps: S3-1)**
As the agent, I want current findings, so that security questions use real signals.
- [ ] `get_security_findings(severity_min, days)`: Security Hub GetFindings (filtered,
      paginated, max 50) + GuardDuty ListFindings/GetFindings; normalized to
      `{id, severity, title, resource, service, last_seen}`; graceful `ok:false,
      hint` when services are not enabled in the account.
- [ ] moto/fixture tests for both services and the not-enabled path.

*Sprint 3 total: 24 pts.*

---

### Sprint 4 — Interactive investigation agent (E4)

Goal: `devops-agent investigate "why did 4xx spike at 3am?"` produces a cited root-cause
answer within budget, using only the C4 toolset.

**S4-1 — Agent harness on Claude Agent SDK (8 pts, deps: S3-2..S3-4)**
As an engineer, I want a locked-down agent loop, so that capability never exceeds the
toolset.
- [ ] `harness.py`: claude-agent-sdk session with **only** C4 tools registered as
      in-process MCP tools (from the C3 decorator registry); built-in tools disabled
      (`allowed_tools` = our tool names only — no Bash/Read/Edit/Web); `max_turns` from
      C7; permission mode deny-by-default; model from `models.loop`.
- [ ] No filesystem settings loaded (`setting_sources` empty) — runtime agent never
      reads repo CLAUDE.md/skills (those are dev-time only).
- [ ] Streams SDK messages to a typed event callback (turn, tool_call, tool_result,
      text, usage) consumed by CLI/API.
- [ ] Eval-style integration test with scripted fake tools: 4xx scenario reaches the
      report-cron root cause in ≤ 10 turns (fixtures from tests/evals/).
- [ ] Test asserting an attempted unknown/builtin tool call is rejected by the harness.

**S4-2 — System prompt & prompt caching (3 pts, deps: S2-5, S4-1)**
As an operator, I want stable instructions + topology cached, so that per-question cost
stays low.
- [ ] `prompts.py`: system prompt = role & method (orient via graph tools → form
      hypotheses → gather aggregated evidence → answer with citations of tool
      queries → state confidence & gaps), tool-usage rules (prefer stats queries, time-
      box first, ≤ 3 services per hypothesis), output format (Findings / Evidence /
      Next steps); + latest topology summary block; cache_control breakpoints set so
      prompt+topology are cache hits across turns and sessions.
- [ ] Staleness warning injected when graph snapshot older than `discovery.max_age_h`.
- [ ] Snapshot test of rendered prompt; assert ≤ 2500 tokens excluding topology.

**S4-3 — Budget & cost tracking (5 pts, deps: S4-1)**
As a cost owner, I want hard limits per investigation, so that spend is bounded by
config, not model behavior.
- [ ] `budget.py` per C7: track cumulative input/output/cached tokens from SDK usage
      events; 80% → inject advisory system note; 100% → cancel loop, force final
      summarize turn; cost computed from `models.pricing` config map and written to
      `llm_audit` + `sessions`.
- [ ] End-of-run cost line always printed (model, turns, tokens, $).
- [ ] Unit tests: threshold transitions, abort path, audit rows.

**S4-4 — investigate CLI + sessions (5 pts, deps: S4-1, S4-3)**
As an engineer, I want one-shot and REPL investigation, so that the tool fits both quick
questions and deep dives.
- [ ] `investigate "<question>" [--env] [--repl] [--budget-tokens N]`; live render of
      turns/tool calls (rich); final answer + cost summary; `--output json` full
      transcript.
- [ ] Sessions persisted (C2 sessions table); `investigate --resume <id>` continues a
      session within remaining budget.
- [ ] Exit codes: 0 answered, 3 budget-stop with partial findings, 1 error.
- [ ] Integration test driving the CLI against scripted fake tools.

**S4-5 — Model routing & summarizer subcalls (3 pts, deps: S4-1)**
As a cost owner, I want big tool outputs compressed by a cheap model, so that the
expensive loop sees only distilled evidence.
- [ ] When a ToolResult.data exceeds `models.summarize_threshold_bytes` (default 2048),
      contract layer calls `models.summarizer` (Haiku-class, direct anthropic client)
      with a fixed compression prompt before returning to the loop; original stored in
      audit; result marked `attrs.summarized=true`.
- [ ] Configurable off; costs recorded in llm_audit with context="tool_summarize".
- [ ] Unit test with fake anthropic client.

*Sprint 4 total: 24 pts.*

---

### Sprint 5 — Scheduled pipelines & digests (E5)

Goal: the agent works for you overnight: anomaly scan, cost digest, security sweep —
deterministic first, Batch API for prose, scheduler wired.

**S5-1 — Nightly log-anomaly scan (5 pts, deps: S3-3)**
As an engineer, I want unusual error patterns flagged daily, so that issues surface
before users report them.
- [ ] `pipelines/log_scan.py`: for every graph log source (cloudwatch type): Insights
      stats query errors-by-pattern last 24 h vs trailing 7-day baseline (stored in
      SQLite `metric_baselines` table — new migration); flag pattern count > μ+3σ or
      new patterns; output structured findings JSON.
- [ ] Zero LLM tokens in this story (detection is deterministic).
- [ ] Fixture tests: known anomaly fixture flags exactly the planted spike.

**S5-2 — Batch summarization & digest renderer (5 pts, deps: S5-1)**
As an engineer, I want a readable morning digest, so that findings get acted on.
- [ ] `pipelines/batch.py`: submit findings (log scan + cost + security) as Anthropic
      **Batch API** requests (models.batch, Haiku-class) producing per-section prose;
      poll/collect; assemble `/data/out/digest-<date>.md` (sections: incidents, cost,
      security, graph drift); cost recorded in llm_audit.
- [ ] Fallback: if batch unavailable/timeout, render deterministic tables-only digest.
- [ ] `devops-agent digest logs|cost|security|all [--no-llm]` CLI.
- [ ] Fake-client tests for batch lifecycle incl. fallback.

**S5-3 — Cost digest pipeline (3 pts, deps: S3-5, S5-2)**
As a cost owner, I want daily movers and anomalies, so that spend surprises die early.
- [ ] Daily CE pull per env; top movers day/day and week/week; simple anomaly rule
      (service delta > config % and > config $); findings feed S5-2.
- [ ] Fixture tests with planted cost jump.

**S5-4 — Security sweep pipeline (3 pts, deps: S3-6, S5-2)**
As an engineer, I want a weekly prioritized findings review, so that security debt is
visible.
- [ ] Weekly findings pull; dedupe vs previous sweep (new/resolved/persisting);
      prioritization = severity × resource criticality (graph: nodes on request paths
      rank higher); feeds S5-2.
- [ ] Fixture tests incl. dedupe.

**S5-5 — Scheduler wiring (2 pts, deps: S5-1..S5-4, S0-2)**
As an operator, I want pipelines to run unattended, so that the agent is proactive.
- [ ] `config/crontab`: daily discovery refresh, nightly log scan, daily cost digest
      (after CE data lands), weekly security sweep; all invoking one-shot compose
      service commands; overlapping-run lock (flock on /data).
- [ ] Compose smoke test extended: scheduler container starts, dry-run flag executes
      each job once against fixtures.
- Platform notes: container cron (supercronic) keeps behavior identical on macOS/Linux;
  document that the machine must be awake for schedules (laptop caveat in README).

*Sprint 5 total: 18 pts.*

---

### Sprint 6 — API, evals, observability, release (E6)

Goal: v1.0 tag — loopback API for future UI, regression evals for agent quality,
operational polish, documented install.

**S6-1 — Loopback REST API (5 pts, deps: S4-4)**
As a future UI, I want HTTP access to investigations and digests, so that a frontend can
be added without touching the core.
- [ ] FastAPI: `POST /investigations` (question, env, budget) → id; `GET
      /investigations/{id}/events` SSE stream of harness events; `GET /graph/summary`;
      `GET /digests/latest?kind=`; `GET /healthz`.
- [ ] Binds 127.0.0.1 only; OpenAPI schema committed; integration tests via httpx.

**S6-2 — Agent evaluation harness (5 pts, deps: S4-1..S4-5)**
As a maintainer, I want scripted scenario evals, so that prompt/model changes can't
silently degrade quality.
- [ ] `tests/evals/`: ≥ 4 scenarios with fully scripted fake tools — 4xx-spike (cron
      root cause), latency (db saturation), cost jump (NAT data processing), red
      herring (no real issue → agent must say so); scoring = reached expected
      conclusion (keyword/structured check) + turns ≤ N + cost ≤ $X.
- [ ] `make evals` runs them with the real model behind `ANTHROPIC_API_KEY` (CI:
      optional job, manual trigger); deterministic fake-model mode for PR CI.
- [ ] Baseline scores recorded in `tests/evals/baseline.json`; regression fails eval job.

**S6-3 — Observability polish (3 pts, deps: S4-3)**
As an operator, I want diagnosis to be self-service, so that issues don't need a
maintainer.
- [ ] structlog JSON everywhere; audit/log rotation (10 MB × 5); `devops-agent costs
      [--days]` report from llm_audit (by context/model/day); doctor extended with
      Anthropic API ping and graph staleness check.
- [ ] Docs page `docs/troubleshooting.md` mapping common failures → fixes.

**S6-4 — User documentation (3 pts, deps: all)**
As a new user, I want a 30-minute path to first answer, so that adoption is easy.
- [ ] `README.md`: quickstart (clone → .env → IAM bootstrap → compose up → doctor →
      discover → investigate); `docs/`: aws-bootstrap, overlay guide (with nginx
      example), configuration reference (generated from pydantic models), security
      model, cost model (levers + expected ranges).
- [ ] [manual] Fresh-machine walkthrough on macOS and Linux executed and checked off.

**S6-5 — Release v1.0 (3 pts, deps: all)**
As a maintainer, I want reproducible releases, so that installs are pinned and
upgradable.
- [ ] Tagged multi-arch image push; compose pinned to tag; CHANGELOG; upgrade note
      (migrations auto-apply); smoke test against the released image in CI release job.

*Sprint 6 total: 19 pts.*

---

## Risks & Open Questions

**Risks → mitigations**
- Terraform state lacks runtime truth (drift, click-ops resources) → AWS wiring
  enrichment (S2-1/S2-2) + drift report make gaps visible; overlay covers the rest.
- State-file diversity breaks parsing (old schema versions, huge states, workspaces) →
  tolerant parser (skip+log), 50 MB guard, fixtures from real projects added as
  encountered; workspaces = additional `state_glob` patterns.
- LLM cost creep → budgets enforced in code (C7), llm_audit + `costs` report, Haiku
  summarizer layer, Batch API digests; eval harness tracks cost per scenario.
- Agent hallucinating infra facts → answers must cite tool queries (prompt rule +
  eval check); graph tools return provenance/confidence the model is told to surface.
- Prompt injection via log content → logs are data: system prompt instructs to treat
  tool output as untrusted; tools are read-only so worst case is a wrong answer, not an
  action; redaction limits data exposure.
- Guardrail bypass by dev-time AI → four layers (settings, hook, checksum CI,
  CODEOWNERS); hook test suite includes bypass attempts; periodic manual red-team task.
- Athena cost blowout → workgroup BytesScannedCutoff + partition-predicate gate (S3-4).
- SQLite contention if usage grows multi-user → single-writer design holds for v1;
  Postgres swap is isolated behind store.py if ever needed.

**Open questions (answers refine, don't block)**
- Q1. Which AWS regions/accounts in scope for v1 config defaults? (affects
  default.yaml and doctor checks)
- Q2. Does a Glue catalog over ALB logs already exist per env, or should
  docs/aws-bootstrap.md include the CREATE TABLE DDL for the user to apply? (agent
  itself never creates it)
- Q3. Digest delivery beyond `/data/out` — Slack webhook in v1.1? (deliberately out of
  v1 to keep write-capabilities at zero)
- Q4. Team's appetite for the optional real-model eval job cost in CI (~$1–3/run)?
