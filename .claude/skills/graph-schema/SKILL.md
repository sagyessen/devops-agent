---
name: graph-schema
description: SQLite knowledge-graph conventions — DDL location, node/edge id rules, source/confidence precedence, migrations, staging-swap writes, and query patterns. Use for any work in src/devops_agent/graph/, overlay merging, or anything reading/writing /data/graph.db.
---

# Knowledge graph: schema & conventions

## Authoritative DDL

Plan C2 is the schema source of truth; it lives as migration
`src/devops_agent/graph/migrations/0001_init.sql`. Schema changes ONLY via a new
sequentially-numbered migration file — never edit an applied migration. The migration
runner applies pending files in order inside one transaction and records versions.

## Conventions

- Node id: `{env}:{kind}:{name}` — lowercase env and kind; name as-is. Helper:
  `graph.ids.node_id(env, kind, name)`. Never format ids inline.
- kinds: service|alb|target_group|lambda|queue|db|log_group|athena_table|stack|cron|other.
- edge kinds: routes_to|targets|calls|consumes|logs_at|member_of|deployed_by|triggers.
  Need a new kind? That's a plan change → ask the human.
- `attrs` columns are JSON text; read/write through pydantic models
  (`graph/models.py`), never raw dict spelunking outside `store.py`.
- Provenance: `source` ∈ terraform|aws_api|glue|overlay|naming and `confidence`
  (naming matches = 0.6). Precedence on conflict (enforced in `store.py` upsert):
  overlay > aws_api > terraform > glue > naming; ties → higher confidence; equal →
  keep existing, update `last_seen`.
- `first_seen` is immutable after insert; every discovery touch updates `last_seen`.

## Write path (discovery only)

Discovery is the only writer of nodes/edges/log_sources. Writes go to staging tables
(`_staging_*`), validated, then swapped into place in one transaction with a new
`snapshots` row (plan §10). The agent process writes only `sessions` and `llm_audit`.
Connections: WAL mode + `busy_timeout=5000`, set in `store.connect()` — use it,
never `sqlite3.connect` directly elsewhere.

## Query patterns

- Use `queries.py` helpers; depth-limited traversal (`neighbors(..., depth<=3)`) is a
  recursive CTE — extend there, don't write ad-hoc recursion in tools.
- Tool-facing outputs must be compact: ids, names, kinds, edge kind, confidence,
  overlay notes. No raw attrs dumps (token cost).
- Topology summary (`summary.py`): deterministic, stable ordering, ≤ 3200 chars.
  Any change requires updating its golden-file test intentionally.

## Testing

Unit tests build throwaway DBs via `store.connect(":memory:")`+migrations. Fixture
graphs for integration tests are built through the public upsert API (never raw SQL
inserts) so precedence rules stay exercised.
