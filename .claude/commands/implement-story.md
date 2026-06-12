---
description: Implement a story from docs/plan/devops-agent-plan.md end to end
---

Implement story $ARGUMENTS from docs/plan/devops-agent-plan.md.

Follow .claude/skills/story-workflow/SKILL.md exactly:
1. Read the story, its sprint goal, its deps, and the Shared Technical Context items
   it references. Read the matching domain skill(s).
2. Post your implementation plan (files, signatures, AC→test mapping). If anything is
   ambiguous, ask before coding.
3. TDD on branch story/<id>-<slug>; fixtures hand-written; scope strictly to the AC.
4. make gates until clean; complete the self-review checklist.
5. Commit with conventional message including the story ID; prepare the PR body per
   the template. Stop before push and show me the summary.
