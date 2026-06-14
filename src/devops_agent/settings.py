from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class BudgetSettings(BaseModel):
    max_turns: int = 15
    max_input_tokens: int = 150_000
    max_output_tokens: int = 8_000
    athena_bytes_scanned: int = 1_073_741_824
    tool_timeout_s: int = 60


class YamlSettingsSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], yaml_path: Path) -> None:
        super().__init__(settings_cls)
        self._path = yaml_path

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        data = self.__call__()
        value = data.get(field_name)
        return value, field_name, False

    def field_is_complex(self, field: FieldInfo) -> bool:
        return self.field_is_complex(field)

    def __call__(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        raw = yaml.safe_load(self._path.read_text())
        return raw if isinstance(raw, dict) else {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DEVOPS_AGENT_",
        env_nested_delimiter="__",
    )

    _config_dir: ClassVar[Path] = Path("config")

    anthropic_api_key: str = ""
    aws_profile: str = "default"
    budgets: BudgetSettings = BudgetSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            YamlSettingsSource(settings_cls, cls._config_dir / "local.yaml"),
            YamlSettingsSource(settings_cls, cls._config_dir / "default.yaml"),
        )
