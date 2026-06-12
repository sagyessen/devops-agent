# Terraform state fixtures (hand-crafted — NOT from real AWS)

Fake account `123456789012`, region `eu-central-1`. These files exercise both
supported S3 layouts (plan C5) and most of the RESOURCE_MAP (plan C6).
Destination in the repo: `tests/fixtures/tfstate/` (keep this directory structure —
the key paths ARE the layout test data).

## Architecture they describe

env=prod (multi-stack layout: prod/networking + prod/app)

    internet → alb-public-prod ──listener:443──▶ tg-nginx-prod ──targets──▶ ecs backend (×3)
                   │                                                            │ logs_at
                   │ access_logs → s3://acme-alb-logs-prod                      ▼
                   └── athena: logs_prod.alb_logs (glue, partitioned by day)  /ecs/backend-prod
    backend ──▶ rds appdb-prod (postgres)
    cron nightly-reports-prod  cron(0 3 * * ? *)  ──triggers──▶ sqs report-jobs-prod
    sqs report-jobs-prod ──consumed by──▶ lambda report-worker-prod (module.report_worker)
                                              └─ logs_at /aws/lambda/report-worker-prod

    Note: the 03:00 UTC cron is the planted root cause for the "why did 4xx spike
    at 3am" eval scenario (S6-2): worker load → backend timeouts → ALB 5xx/499.

env=staging (mono-state layout: staging/terraform.tfstate, stack=root)

    alb-staging ──listener:443──▶ tg-api-staging (lambda target) ──▶ lambda api-staging
                                                                       └─ /aws/lambda/api-staging
    athena: logs_staging.alb_logs

## Parser edge cases deliberately included

- module child resources (`module.report_worker.*`) — flat list with `module` field
- `mode: "data"` resource (caller_identity) — must be skipped
- unknown-to-RESOURCE_MAP type (`aws_appautoscaling_target`) — must become kind `other`
- `container_definitions` is a JSON **string** (real ECS shape) containing the
  `awslogs-group` → logs_at edge
- lambda `logging_config` log_group → logs_at edge
- event rule + event target pair → cron node + triggers edge to the queue
- cross-stack reference: app stack's ECS service points at the networking stack's
  target group ARN (edges must connect across state files)
- different terraform_version values and schema_versions per resource

## Expected-output golden files

`.expected.json` files are intentionally NOT included: they encode the parser's
exact output and must be written together with the S1-3 implementation (story AC),
reviewed by a human against this README's architecture description.
