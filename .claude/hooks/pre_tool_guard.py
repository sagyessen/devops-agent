#!/usr/bin/env python3
"""PreToolUse guard for the DevOps Agent repository.

Defense-in-depth layer behind .claude/settings.json permission rules. Blocks any
attempt — direct or indirect — to (a) modify guardrail files, (b) touch real AWS or
infrastructure tooling, or (c) escalate privileges. Fail-closed: any internal error
blocks the action.

Protocol: receives the tool-call JSON on stdin; exit 0 allows, exit 2 blocks (stderr is
shown to the model as the reason). This file is itself protected by settings.json deny
rules, the guardrails checksum CI job, and CODEOWNERS — do not edit without human
review.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROTECTED = (
    ".claude",
    "iam",
    "CODEOWNERS",
    "scripts/guardrails.sh",
    ".github/workflows/guardrails.yml",
)

# Substrings that may never appear in any Bash command, regardless of context.
# Catches direct use, redirection targets, and variable-assignment indirection
# (e.g. `P=.claude; rm -rf $P`).
FORBIDDEN_SUBSTRINGS = (
    ".claude",
    "CODEOWNERS",
    "guardrails.sh",
    "guardrails.yml",
    "iam/",
    "~/.aws",
    "/.aws",
)

# Command start: line/segment start, optionally prefixed by `env` and/or any number
# of VAR=value assignments (catches `AWS_PROFILE=prod aws ...`, `env X=1 sudo ...`).
_CMD = r"(^|[;&|(]\s*)(env\s+)?([a-z_][a-z0-9_]*=\S*\s+)*"

FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (_CMD + r"aws\s", "real AWS CLI is forbidden in development; use moto/fixtures"),
    (_CMD + r"terraform(\s|$)", "terraform is forbidden in development"),
    (_CMD + r"(sudo|doas)(\s|$)", "privilege escalation is forbidden"),
    (_CMD + r"su(\s|$)", "privilege escalation is forbidden"),
    (r"--privileged", "privileged containers are forbidden"),
    (_CMD + r"(curl|wget)\b", "network fetch tools are forbidden in development"),
    (r"\|\s*(ba|z|da)?sh\b", "piping into a shell is forbidden"),
    (_CMD + r"(ba|z|da)?sh\s+-c\b", "nested shell -c invocations are forbidden"),
    (_CMD + r"eval\b", "eval is forbidden"),
    (_CMD + r"git\s+apply\b", "git apply is forbidden; use the Edit tool"),
    (_CMD + r"patch\b", "patch is forbidden; use the Edit tool"),
    (r"core\.hookspath", "modifying git hook paths is forbidden"),
    (_CMD + r"chmod\b.*\+s", "setuid is forbidden"),
    (_CMD + r"(ssh|scp|sftp)\b", "remote shell access is forbidden"),
    (_CMD + r"ln\s+-s", "creating symlinks is forbidden (guardrail bypass vector)"),
)

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def deny(reason: str) -> None:
    print(f"BLOCKED by .claude/hooks/pre_tool_guard.py: {reason}", file=sys.stderr)
    sys.exit(2)


def is_protected_path(raw: str, cwd: Path) -> bool:
    p = Path(raw)
    if not p.is_absolute():
        p = cwd / p
    try:
        resolved = p.resolve()  # collapses ../ and follows symlinks
    except OSError:
        return True  # unresolvable path: fail closed
    repo = cwd.resolve()
    for prot in PROTECTED:
        target = (repo / prot).resolve()
        if resolved == target or str(resolved).startswith(str(target) + "/"):
            return True
    # A path escaping the repo entirely is also suspicious for write tools.
    if not str(resolved).startswith(str(repo) + "/") and resolved != repo:
        return True
    return False


def check_file_tool(tool_input: dict, cwd: Path) -> None:
    for key in ("file_path", "notebook_path", "path"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw:
            if is_protected_path(raw, cwd):
                deny(f"writes to protected or out-of-repo path are forbidden: {raw}")
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            raw = e.get("file_path") if isinstance(e, dict) else None
            if isinstance(raw, str) and raw and is_protected_path(raw, cwd):
                deny(f"writes to protected path are forbidden: {raw}")


def check_bash(command: str) -> None:
    lowered = command.lower()
    for frag in FORBIDDEN_SUBSTRINGS:
        if frag.lower() in lowered:
            deny(f"command references protected target '{frag}'")
    for pattern, reason in FORBIDDEN_PATTERNS:
        if re.search(pattern, lowered):
            deny(reason)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "")
        tool_input = payload.get("tool_input") or {}
        cwd = Path(payload.get("cwd") or ".")
        if tool == "Bash":
            check_bash(str(tool_input.get("command", "")))
        elif tool in FILE_TOOLS:
            check_file_tool(tool_input, cwd)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:  # fail closed
        deny(f"guard internal error, action blocked: {exc}")


if __name__ == "__main__":
    main()
