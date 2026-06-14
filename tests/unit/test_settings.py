"""Tests for settings.py — proves 4-level precedence: default.yaml → local.yaml → env → init."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from devops_agent.settings import Settings  # noqa: E402 (after std-lib block)

# ---------- helper ----------


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content)


# ---------- version flag ----------


def test_version_flag_exits_zero() -> None:
    res = subprocess.run(
        [sys.executable, "-m", "devops_agent.cli", "--version"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "0.1.0" in res.stdout


# ---------- precedence layer 1: default.yaml ----------


def test_default_values_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_yaml(tmp_path / "default.yaml", "budgets:\n  max_turns: 15\n")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.budgets.max_turns == 15


def test_missing_default_yaml_uses_model_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.budgets.max_turns == 15  # pydantic field default


# ---------- precedence layer 2: local.yaml overrides default ----------


def test_local_yaml_overrides_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_yaml(tmp_path / "default.yaml", "budgets:\n  max_turns: 15\n")
    _write_yaml(tmp_path / "local.yaml", "budgets:\n  max_turns: 99\n")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.budgets.max_turns == 99


def test_missing_local_yaml_falls_back_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_yaml(tmp_path / "default.yaml", "budgets:\n  max_turns: 20\n")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.budgets.max_turns == 20


# ---------- precedence layer 3: DEVOPS_AGENT_* env overrides local.yaml ----------


def test_env_overrides_local_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_yaml(tmp_path / "default.yaml", "budgets:\n  max_turns: 15\n")
    _write_yaml(tmp_path / "local.yaml", "budgets:\n  max_turns: 99\n")
    monkeypatch.setenv("DEVOPS_AGENT_BUDGETS__MAX_TURNS", "42")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.budgets.max_turns == 42


def test_env_prefix_top_level_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_yaml(tmp_path / "default.yaml", "aws_profile: default\n")
    monkeypatch.setenv("DEVOPS_AGENT_AWS_PROFILE", "staging")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.aws_profile == "staging"


# ---------- precedence layer 4: init kwargs (CLI flags) override env ----------


def test_init_kwargs_override_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_yaml(tmp_path / "default.yaml", "budgets:\n  max_turns: 15\n")
    monkeypatch.setenv("DEVOPS_AGENT_BUDGETS__MAX_TURNS", "42")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings(budgets={"max_turns": 7})
    assert s.budgets.max_turns == 7


def test_init_kwargs_take_highest_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_yaml(tmp_path / "default.yaml", "aws_profile: default\n")
    _write_yaml(tmp_path / "local.yaml", "aws_profile: staging\n")
    monkeypatch.setenv("DEVOPS_AGENT_AWS_PROFILE", "prod")
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings(aws_profile="override")
    assert s.aws_profile == "override"


# ---------- budget defaults from C7 ----------


def test_c7_budget_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Settings, "_config_dir", tmp_path)
    s = Settings()
    assert s.budgets.max_turns == 15
    assert s.budgets.max_input_tokens == 150_000
    assert s.budgets.max_output_tokens == 8_000
    assert s.budgets.athena_bytes_scanned == 1_073_741_824
    assert s.budgets.tool_timeout_s == 60
