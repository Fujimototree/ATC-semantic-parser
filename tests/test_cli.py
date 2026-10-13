import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import cli
from src.config import ConfigError
from src.schema import ATCMessage


@pytest.fixture
def offline_cli(tmp_path, monkeypatch, success_data):
    path = tmp_path / "config.yaml"
    path.write_text("llm:\n  provider: ollama\n", encoding="utf-8")
    message = ATCMessage.model_validate(success_data)
    parser = MagicMock()
    parser.parse_batch.return_value = [message]
    parser.__enter__.return_value = parser
    factory = MagicMock(return_value=parser)
    monkeypatch.setattr(cli, "ATCCommandParser", factory)
    return path, parser, factory


def test_help_does_not_require_config_or_backend():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "run_demo.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--batch" in result.stdout and "--json" in result.stdout


def test_json_stdout_is_machine_readable(offline_cli, capsys):
    path, parser, factory = offline_cli
    assert cli.main(["--config", str(path), "--json", "海航7888，36L跑道外等待。"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["parse_status"] == "SUCCESS"
    parser.__exit__.assert_called_once()
    assert factory.call_args.kwargs["timeout"] == 60.0


def test_batch_skips_comments_and_preserves_input_order(offline_cli, tmp_path, capsys):
    path, parser, _ = offline_cli
    batch = tmp_path / "commands.txt"
    batch.write_text("\ufeff# comment\n  # indented comment\n\n first \nsecond\n", encoding="utf-8")
    assert cli.main(["--config", str(path), "--batch", str(batch), "--json"]) == 0
    parser.parse_batch.assert_called_once_with(["first", "second"])
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_json_output_file(offline_cli, tmp_path, capsys):
    path, _, _ = offline_cli
    output = tmp_path / "result.json"
    assert cli.main(["--config", str(path), "--json", "--output", str(output), "指令"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["parse_status"] == "SUCCESS"
    assert capsys.readouterr().out == ""


def test_non_success_exit_code(offline_cli, capsys):
    path, parser, _ = offline_cli
    message = ATCMessage(
        raw_text="噪音",
        parse_status="UNRECOGNIZED",
        confidence_score=0.0,
        error_payload={"error_type": "FORMAT_MESS", "fallback_prompt": "核对"},
    )
    parser.parse_batch.return_value = [message]
    assert cli.main(["--config", str(path), "--json", "噪音"]) == 2
    assert json.loads(capsys.readouterr().out)["extracted_data"] is None


def test_config_error_uses_stderr_without_client(tmp_path, monkeypatch, capsys):
    factory = MagicMock()
    monkeypatch.setattr(cli, "ATCCommandParser", factory)
    assert cli.main(["--config", str(tmp_path / "missing.yaml"), "--json", "指令"]) == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err
    factory.assert_not_called()


def test_empty_batch_makes_no_client(offline_cli, tmp_path):
    path, _, factory = offline_cli
    batch = tmp_path / "empty.txt"
    batch.write_text("  # comment\n\n", encoding="utf-8")
    assert cli.main(["--config", str(path), "--batch", str(batch)]) == 1
    factory.assert_not_called()


def test_summary_uses_real_results(success_data, capsys):
    success = ATCMessage.model_validate(success_data)
    partial = success.model_copy(update={"parse_status": "PARTIAL_SUCCESS"})
    failed = ATCMessage(
        raw_text="噪音",
        parse_status="UNRECOGNIZED",
        confidence_score=0.0,
        error_payload={"error_type": "FORMAT_MESS", "fallback_prompt": "核对"},
    )
    cli.display_summary([success, success, partial, failed])
    output = capsys.readouterr().out
    assert "SUCCESS=2" in output and "PARTIAL_SUCCESS=1" in output and "UNRECOGNIZED=1" in output


def test_markup_in_input_is_literal(success_data, capsys):
    success_data["raw_text"] = "[red]literal[/red]"
    cli.display_result(ATCMessage.model_validate(success_data))
    assert "[red]literal[/red]" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [
        ["--config"],
        ["--json"],
        ["--output", "result.json", "指令"],
        ["--batch", "input.txt", "指令"],
    ],
)
def test_argument_errors(args):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


def test_missing_batch(tmp_path):
    with pytest.raises(ConfigError):
        cli.read_commands(tmp_path / "missing.txt")
