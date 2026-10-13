"""Command-line interface for interactive, single and batch parsing."""

import argparse
import json
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .config import ConfigError, load_config
from .parser import ATCCommandParser
from .schema import ATCMessage

console = Console()
error_console = Console(stderr=True)
STATUS_COLORS = {"SUCCESS": "green", "PARTIAL_SUCCESS": "yellow", "UNRECOGNIZED": "red"}


def display_result(msg: ATCMessage, index: int | None = None) -> None:
    """Render untrusted input as literal text, never as Rich markup."""
    header = f"解析状态: {msg.parse_status} | 模型置信度: {msg.confidence_score:.2f}"
    if index is not None:
        header = f"#{index} | {header}"
    lines = [f"原始指令: {msg.raw_text}", f"消息 ID: {msg.msg_id}", f"时间戳: {msg.timestamp}"]
    if msg.extracted_data:
        data = msg.extracted_data
        lines.append(f"航班呼号: {data.callsign}")
        for action_index, action in enumerate(data.action_queue, 1):
            route = " → ".join([*action.routing.assigned_path, action.routing.end_point])
            trigger = action.trigger_condition
            target = f" ({trigger.traffic_target})" if trigger.traffic_target else ""
            lines.append(
                f"  {action_index}. {action.action_type} | {route} | {trigger.trigger_type}{target}"
            )
    if msg.error_payload:
        lines.append(f"错误: {msg.error_payload.error_type} | {msg.error_payload.fallback_prompt}")
    console.print(
        Panel(
            Text("\n".join(lines)),
            title=Text(header),
            border_style=STATUS_COLORS[msg.parse_status],
        )
    )
    console.print(Syntax(msg.model_dump_json(indent=2), "json", word_wrap=True))


def read_commands(file_path: str | Path) -> list[str]:
    """UTF-8/BOM input, ignoring blanks and comments including indented comments."""
    try:
        lines = Path(file_path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise ConfigError("无法读取批处理文件；请检查路径和 UTF-8 编码。") from None
    commands = [
        line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")
    ]
    if not commands:
        raise ConfigError("批处理文件没有有效指令。")
    return commands


def display_summary(results: list[ATCMessage]) -> None:
    counts = Counter(message.parse_status for message in results)
    console.print(
        Text(
            f"批量完成: {len(results)} 条 | SUCCESS={counts['SUCCESS']} | "
            f"PARTIAL_SUCCESS={counts['PARTIAL_SUCCESS']} | UNRECOGNIZED={counts['UNRECOGNIZED']}"
        )
    )


def _run_batch_file(parser: ATCCommandParser, file_path: str | Path) -> list[ATCMessage]:
    commands = read_commands(file_path)
    results = []
    for index, command in enumerate(commands, 1):
        with console.status(f"解析 {index}/{len(commands)} ..."):
            message = parser.parse(command)
        results.append(message)
        display_result(message, index)
    display_summary(results)
    return results


def run_single(parser: ATCCommandParser, text: str) -> ATCMessage:
    with console.status("解析中 ..."):
        result = parser.parse(text)
    display_result(result)
    return result


def run_interactive(parser: ATCCommandParser) -> None:
    console.print(
        Text(
            "ATC 地面管制指令解析\n"
            "输入指令；!batch <路径> 批量解析；!examples 运行示例；!exit 退出。"
        )
    )
    while True:
        try:
            text = console.input("\nATC > ").strip()
            if not text:
                continue
            if text == "!exit":
                break
            if text == "!examples":
                _run_batch_file(
                    parser, Path(__file__).resolve().parents[1] / "examples/sample_commands.txt"
                )
            elif text == "!batch" or text.startswith("!batch "):
                parts = text.split(maxsplit=1)
                if len(parts) != 2:
                    error_console.print("用法: !batch <文件路径>", style="red")
                    continue
                _run_batch_file(parser, parts[1])
            else:
                run_single(parser, text)
        except ConfigError as exc:
            error_console.print(Text(str(exc), style="red"))
        except (KeyboardInterrupt, EOFError):
            break
    console.print("已退出")


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description="将中文 ATC 地面管制文本解析为结构化 JSON。")
    arguments.add_argument("text", nargs="*", help="单条指令（建议用引号包裹）")
    arguments.add_argument("--config", default="config.yaml", help="YAML 配置路径")
    arguments.add_argument("--batch", type=Path, help="批处理 UTF-8 文件，一行一条指令")
    arguments.add_argument("--json", action="store_true", help="只输出 JSON；批处理输出 JSON 数组")
    arguments.add_argument("--output", type=Path, help="将 --json 结果写入文件")
    args = arguments.parse_args(argv)
    if args.batch and args.text:
        arguments.error("--batch 与单条指令不能同时使用")
    if args.output and not args.json:
        arguments.error("--output 需要 --json")
    if args.json and not (args.batch or args.text):
        arguments.error("--json 需要单条指令或 --batch")

    try:
        config = load_config(args.config)
        commands = read_commands(args.batch) if args.batch else None
        with ATCCommandParser(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
            max_retries=config.max_retries,
        ) as parser:
            if not args.json:
                console.print(Text(f"Provider: {config.provider} | Model: {config.model}"))
            if not args.text and commands is None:
                run_interactive(parser)
                return 0
            texts = commands if commands is not None else [" ".join(args.text)]
            results = parser.parse_batch(texts)
            if args.json:
                data = [result.model_dump(mode="json") for result in results]
                payload = json.dumps(
                    data if commands is not None else data[0], ensure_ascii=False, indent=2
                )
                if args.output:
                    args.output.write_text(payload + "\n", encoding="utf-8")
                else:
                    # Bypass Rich wrapping and markup so stdout remains valid JSON.
                    print(payload)
            else:
                for index, result in enumerate(results, 1):
                    display_result(result, index)
                if commands is not None:
                    display_summary(results)
            return 0 if all(result.parse_status == "SUCCESS" for result in results) else 2
    except ConfigError as exc:
        error_console.print(Text(str(exc), style="red"))
        return 1
    except OSError:
        error_console.print("无法写入输出文件；请检查目标目录和权限。", style="red")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
