---
name: aws-read-only
description: How to add or modify evidence tools under the tool contract (caps, redaction, audit), and how to test any boto3-touching code with moto or recorded fixtures. Use for any work in src/devops_agent/tools/ or src/devops_agent/discovery/aws_*.py and all AWS-related tests. Real AWS is forbidden in development.
---

# AWS code: read-only tools & testing

## Iron rules

- Every model-visible tool goes through `tools/contract.py` (`@evidence_tool`).
  No exceptions, no direct boto3 calls from `agent/`.
- Read-only by construction: only describe/get/list/query APIs. The single allowed
  write anywhere is Athena's own result writing (server-side, via workgroup).
- Tools never raise to the caller: return `ToolResult(ok=False, error_kind=..., hint=...)`
  (plan C3 has the exact model). `hint` must be actionable for an LLM re-plan
  ("add a day partition filter", "nearest log groups: ...").
- All boto3 clients come from the injected `AwsClients` factory — never construct a
  client at module level (breaks tests and region handling).

## Adding a tool (checklist)

1. Pydantic input model with constrained fields (time ranges required and bounded,
   enums for group_by-style params, depth/limit caps).
2. Implement function; decorate `@evidence_tool(name, description, InputModel)`.
   The description is model-facing: include one example call and the preferred
   query patterns (aggregate-first).
3. Confirm the contract handles your output size (50 rows / 4096 bytes); structure
   `data` so truncation degrades gracefully (most important rows first).
4. Verify the IAM actions you use exist in `iam/devops-agent-readonly.json`. If not:
   STOP — propose the addition to the human; never widen the policy yourself.
5. Tests (below) including: happy path, empty result, AWS error mapping
   (throttle → error_kind=throttled), redaction, truncation flag.

## Testing AWS code

- Prefer `moto` (`@mock_aws`) for services it covers: s3, logs (groups), elbv2, ecs,
  lambda, glue, sts, securityhub, guardduty basics.
- For APIs moto doesn't model (Logs Insights query lifecycle, Cost Explorer, Athena
  execution): use the fake-client pattern — a `FakeAwsClients` returning recorded
  response dicts from `tests/fixtures/aws/<service>/<case>.json`. Hand-write fixtures
  from the official response shapes; never capture from a real account.
- Botocore retry behavior: test throttling by raising `ClientError` with code
  `ThrottlingException` from the fake and asserting backoff/error_kind.
- Redaction: parametrized property test feeds secret-shaped strings through every
  tool's result path and asserts `«redacted:` replacement.

## Redaction

Patterns live in `tools/redaction.py` + `redaction.patterns` config. When adding a
data source, add a test with a planted secret of each kind in that source's shape.
