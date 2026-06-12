---
name: terraform-state
description: How to read Terraform state files (schema v4) from S3, extend the resource-to-graph mapping (RESOURCE_MAP), handle multi-stack vs mono-state layouts, and build state fixtures for tests. Use for any work in src/devops_agent/discovery/terraform_state.py or its tests.
---

# Terraform state parsing

## State object essentials (schema version 4)

A `terraform.tfstate` is JSON:

```json
{
  "version": 4,
  "terraform_version": "1.7.5",
  "resources": [
    {
      "module": "module.api",            // absent for root module
      "mode": "managed",                 // skip "data" mode resources
      "type": "aws_ecs_service",
      "name": "backend",
      "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
      "instances": [
        { "index_key": 0,                // present for count/for_each
          "attributes": { "...": "all resolved attributes incl. arn, tags" },
          "dependencies": ["aws_lb_target_group.backend"] }
      ]
    }
  ]
}
```

Rules:
- Iterate `resources[]`; include nested module resources (flat list, `module` field
  carries the address). Process `mode == "managed"` only.
- Each instance yields one node candidate; `attributes.arn` and `attributes.tags`
  go to node `arn` / `attrs.tags`.
- `instances[].dependencies` gives intra-state reference edges — use only for the
  cross-resource edges listed in plan C6; do not invent edge kinds.
- Unknown `type` → node kind `other` (never drop). Malformed instance → log + skip;
  the run must not abort (plan §10).
- Versions other than 4: log warning, attempt best-effort `resources[]` parse, count
  in snapshot stats as `unsupported_state_version`.

## Layouts (must both work, config-only — plan C5)

- Multi-stack: `prod/networking/terraform.tfstate`, `prod/app/terraform.tfstate` →
  stacks `networking`, `app` in env `prod`.
- Mono-state: `prod/terraform.tfstate` → stack `root` in env `prod` (stack_from regex
  simply doesn't match).
Never hardcode either; everything flows from `discovery.terraform.backends[]` config.

## Extending RESOURCE_MAP

`RESOURCE_MAP: dict[str, Mapper]` in `terraform_state.py`. A Mapper is a pure function
`(resource, instance_attrs, ctx) -> list[Node] | list[Edge]`. To add a type:
1. Add the entry + mapper (pure function, no I/O).
2. Add/extend a fixture state in `tests/fixtures/tfstate/` containing the type.
3. Extend the golden-file test asserting the exact node/edge set.
Node ids follow C2: `{env}:{kind}:{name}`; name = best human identifier
(tags.Name > resource name attr > tf resource name).

## Fixtures

Hand-write minimal-but-realistic states (never from real AWS). Keep ARNs syntactically
valid with account id `123456789012`. One fixture per scenario; golden expectations in
adjacent `.expected.json`.
