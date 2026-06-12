# DevOps Agent — bootstrap pack

Drop these files into a fresh git repo. They make the repository AI-developable:
the human only ever prompts story IDs; everything else is in-repo.

## One-time human setup (10 minutes)
1. `git init devops-agent && cd devops-agent` → copy this pack's contents in.
2. Edit `CODEOWNERS`: replace `@OWNER` with your GitHub handle.
3. `./scripts/guardrails.sh generate` after ANY reviewed guardrail change
   (the committed manifest is already valid for this pack as-is).
4. Commit everything. Enable branch protection on `main` with required checks:
   `guardrails`, plus `quality`/`test` once S0-3 lands. CODEOWNERS review required.
5. Open Claude Code in the repo. First prompt: `/implement-story S0-1`.
   Then S0-2, S0-3, S0-6, S0-7 ... in plan order (S0-4/S0-5 are already satisfied
   by this pack — tell the AI to mark them done after verifying `make guardrails-verify`
   and `pytest tests/unit/test_guardrails.py` pass).

## What's in here
- `CLAUDE.md` — master AI instructions (project, workflow, hard guardrails).
- `docs/plan/devops-agent-plan.md` — full architecture + epics/sprints/stories;
  the single source of truth every story references.
- `.claude/settings.json` — deny-first permissions (no aws/terraform/sudo/network,
  guardrail paths unwritable; pip/docker/git-push require human approval).
- `.claude/hooks/pre_tool_guard.py` — fail-closed PreToolUse guard (blocks path
  traversal, symlinks, redirection, env-var indirection, fetch-and-execute, etc.);
  tested by `tests/unit/test_guardrails.py` (45 cases incl. bypass attempts).
- `.claude/skills/` — story-workflow (the dev loop), terraform-state,
  aws-read-only, graph-schema.
- `.claude/commands/implement-story.md` — `/implement-story <ID>`.
- `scripts/guardrails.sh` + `.claude/hooks/manifest.sha256` +
  `.github/workflows/guardrails.yml` + `CODEOWNERS` — tamper detection & human gate.
- `Makefile` — gates the AI runs (`make gates`), guardrail verify targets.

## Security model (4 layers, in order)
settings deny → hook (fail-closed) → checksum CI on every PR → CODEOWNERS human
review of guardrail paths. Runtime AWS safety is separate and IAM-enforced
(see plan §8 + Sprint 0 story S0-6).
