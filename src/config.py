"""Validated configuration shared by the CLI and embedding applications."""

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator


class ConfigError(ValueError):
    """Configuration cannot be used. Messages never include credential values."""


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    provider: Literal["ollama", "api"] = "api"
    api_key: SecretStr
    base_url: str
    model: str = Field(min_length=1)
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1)
    timeout: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=1, ge=0, le=5)

    @field_validator("model")
    @classmethod
    def nonblank_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must not be blank")
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key or key in {"your-api-key-here", "your-deepseek-api-key", "sk-your-api-key"}:
            raise ValueError("API key is missing or a placeholder")
        return SecretStr(key)

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            port = url.port
        except ValueError:
            raise ValueError("invalid endpoint URL") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or any(char.isspace() for char in value)
            or port == 0
        ):
            raise ValueError("endpoint must be HTTP(S), without credentials, query or fragment")
        return value.rstrip("/")


def load_config(config_path: str | Path = "config.yaml") -> LLMConfig:
    """Load YAML, resolve mode defaults, and prefer ATC_API_KEY in API mode."""
    try:
        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        raise ConfigError("无法读取配置文件；请复制 config.example.yaml 并检查文件路径。") from None
    except yaml.YAMLError:
        raise ConfigError("配置文件不是有效的 YAML。") from None

    if not isinstance(data, dict) or set(data) != {"llm"} or not isinstance(data["llm"], dict):
        raise ConfigError("配置必须包含唯一的顶层 llm 映射。")

    llm = dict(data["llm"])
    provider = llm.setdefault("provider", "api")
    if provider == "ollama":
        llm["api_key"] = "ollama"
        llm.setdefault("base_url", "http://localhost:11434/v1")
        llm.setdefault("model", "qwen2.5:7b")
    elif provider == "api":
        llm["api_key"] = os.getenv("ATC_API_KEY") or llm.get("api_key", "")
        llm.setdefault("base_url", "https://api.deepseek.com/v1")
        llm.setdefault("model", "deepseek-chat")

    try:
        return LLMConfig.model_validate(llm)
    except ValidationError as exc:
        fields = ", ".join(sorted({str(error["loc"][0]) for error in exc.errors()}))
        raise ConfigError(f"无效的 llm 配置字段: {fields}；请参考 config.example.yaml。") from None
