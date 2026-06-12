---
name: story-workflow
description: Mandatory workflow for implementing any story (S*-*) from docs/plan/devops-agent-plan.md. Use whenever the human asks to implement, continue, or fix a story, epic, or sprint item. Covers reading order, branching, TDD sequence, quality gates, self-review, and PR format.
---

# Story implementation workflow

## 1. Orient (always, even if the session feels warm)

1. Read the story verbatim in `docs/plan/devops-agent-plan.md` (search for its ID,
   e.g. `S1-3`). Read its sprint goal line and every dependency story's title.
2. Re-read the plan's **Shared Technical Context** items the story references
   (C1–C8). They are authoritative over your intuition.
3. Read the domain skill that matches the code area (`terraform-state`,
   `aws-read-only`, `graph-schema`).
4. Check dependencies: if a `deps:` story is not merged (`git log --oneline | grep
   <ID>` or missing module), STOP and report which dependency is missing.

## 2. Plan before code

Write a short implementation plan as your first message: files to create/modify
(must match the C1 layout), public function signatures, test list mapped 1:1 to the
story's acceptance criteria checkboxes. If any acceptance criterion is ambiguous,
ask the human now — never guess on schema, IAM, config keys, or tool contracts.

## 3. Implement (TDD order)

1. Branch: `git checkout -b story/<id>-<slug>` (e.g. `story/s1-3-state-parser`).
2. For each acceptance criterion: write the failing test first
   (`tests/unit/...` or `tests/integration/...` per the aws-read-only skill's
   testing rules), then the minimal implementation, then refactor.
3. Fixtures go in `tests/fixtures/` and are committed; never generate fixtures by
   calling real AWS (forbidden) — hand-craft them from the shapes documented in the
   domain skills.
4. Keep the diff scoped to the story. Improvement ideas → PR description "Proposals"
   section, not the diff.

## 4. Gates

Run `make gates` (= lint + typecheck + test). Fix until clean. If a gate failure is
pre-existing on main, report it; do not silence it (no `# type: ignore`,
`# noqa`, or test skips without a linked story ID in a comment).

## 5. Self-review checklist (answer each in the PR body)

- [ ] Every acceptance criterion has a passing test (name them) or is marked [manual].
- [ ] No new dependencies, or each one justified and human-approved.
- [ ] No guardrail files touched; no `aws`/`terraform`/network calls anywhere in
      tests or code paths exercised by tests.
- [ ] Public functions typed; pydantic models at I/O boundaries; no module-level
      boto3 clients.
- [ ] Docs updated if behavior/config changed (README, docs/, config example files).

## 6. Commit & PR

- Conventional commits with story ID: `feat(discovery): parse tfstate modules (S1-3)`.
- PR title: `[S1-3] Terraform state parser & resource mapping`.
- PR body template:

```
## Story
S1-3 — link/quote the acceptance criteria.

## AC → evidence
| Acceptance criterion | Test |
|---|---|
| ... | tests/unit/test_x.py::test_y |

## Self-review
(checklist from step 5)

## Proposals (out of scope, not implemented)
- ...
```

- Push only with human approval (settings will prompt). Never force-push.

## 7. Done

Done = the plan's Definition of Done. If CI fails on the other OS (macos vs ubuntu),
fix forward on the same branch; platform-specific behavior must be eliminated, not
special-cased, unless the story's Platform notes say otherwise.
