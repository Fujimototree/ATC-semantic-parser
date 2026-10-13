import pytest
import yaml

from src.config import ConfigError, load_config


def config_file(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def no_inherited_key(monkeypatch):
    monkeypatch.delenv("ATC_API_KEY", raising=False)


def test_ollama_defaults(tmp_path):
    config = load_config(config_file(tmp_path, {"llm": {"provider": "ollama"}}))
    assert config.api_key.get_secret_value() == "ollama"
    assert config.model == "qwen2.5:7b"
    assert config.timeout == 60.0 and config.max_retries == 1


def test_old_config_resolves_provider(tmp_path):
    config = load_config(config_file(tmp_path, {"llm": {"api_key": "test-secret"}}))
    assert config.provider == "api" and config.model == "deepseek-chat"


def test_environment_overrides_yaml_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ATC_API_KEY", "environment-secret")
    config = load_config(
        config_file(tmp_path, {"llm": {"provider": "api", "api_key": "yaml-secret"}})
    )
    assert config.api_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(config)


@pytest.mark.parametrize(
    "data", [None, [], "llm", {"llm": None}, {"llm": []}, {"llm": {}, "extra": 1}]
)
def test_invalid_top_level_shape(tmp_path, data):
    with pytest.raises(ConfigError):
        load_config(config_file(tmp_path, data))


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "unknown"},
        {"model": ""},
        {"max_tokens": 0},
        {"max_tokens": True},
        {"temperature": -1},
        {"temperature": 3},
        {"temperature": "0.1"},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"max_retries": -1},
        {"max_retries": 6},
        {"max_retries": "1"},
        {"base_url": "ftp://localhost"},
        {"base_url": "https://user:secret@example.com/v1"},
        {"base_url": "https://example.com/v1?api_key=secret"},
        {"base_url": "https://example.com/v1#fragment"},
        {"base_url": "http://localhost:0"},
        {"base_url": "http://localhost:invalid"},
        {"base_url": "http://local host"},
        {"unknown_option": 1},
    ],
)
def test_invalid_llm_fields(tmp_path, change):
    with pytest.raises(ConfigError):
        load_config(config_file(tmp_path, {"llm": {"provider": "ollama", **change}}))


@pytest.mark.parametrize(
    "key", ["", " ", "your-api-key-here", "your-deepseek-api-key", "sk-your-api-key"]
)
def test_placeholder_api_key(tmp_path, key):
    with pytest.raises(ConfigError):
        load_config(config_file(tmp_path, {"llm": {"provider": "api", "api_key": key}}))


def test_invalid_yaml_is_redacted(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("llm:\n  api_key: [private-secret", encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "private-secret" not in str(error.value)


def test_validation_error_is_redacted(tmp_path):
    path = config_file(tmp_path, {"llm": {"api_key": "private-secret", "temperature": "invalid"}})
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "private-secret" not in str(error.value)


def test_missing_config(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")
