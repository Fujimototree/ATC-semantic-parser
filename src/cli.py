"""ATC 指令解析 — 交互式命令行工具。"""

import json
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .parser import ATCCommandParser

console = Console()

STATUS_STYLES = {
    "SUCCESS": "bold green",
    "PARTIAL_SUCCESS": "bold yellow",
    "UNRECOGNIZED": "bold red",
}


def load_config(config_path: str = "config.yaml") -> dict:
    """从 YAML 文件加载配置，支持 Ollama 本地 / API 远程双模式。"""
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]配置文件不存在: {config_path}[/red]")
        console.print("请复制 config.example.yaml 为 config.yaml 并编辑对应配置：")
        console.print("  [dim]cp config.example.yaml config.yaml[/dim]")
        console.print()
        console.print("支持两种运行模式：")
        console.print("  • [bold]Ollama 本地模式[/bold] — 无需 API Key，数据不出本机")
        console.print("  • [bold]API 远程模式[/bold] — DeepSeek / OpenAI 等远程服务")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if config is None or "llm" not in config:
        console.print("[red]配置文件格式错误：缺少顶层 'llm' 段[/red]")
        console.print("请参考 config.example.yaml 的格式重新编辑")
        sys.exit(1)

    llm = config["llm"]

    # ── 读取 provider，默认 "api"（向后兼容旧配置） ──
    provider = llm.get("provider", "api")
    if provider not in ("ollama", "api"):
        console.print(
            f"[red]无效的 provider 值: '{provider}'，"
            f"只支持 'ollama' 或 'api'[/red]"
        )
        sys.exit(1)

    if provider == "ollama":
        # Ollama 本地模式：无需 API key
        llm.setdefault("base_url", "http://localhost:11434/v1")
        llm.setdefault("model", "qwen2.5:7b")
        llm["api_key"] = "ollama"  # Ollama 忽略 Authorization 头
    else:  # provider == "api"
        # API 远程模式：必须提供真实 API key
        api_key = llm.get("api_key", "")
        if not api_key or api_key in ("your-api-key-here", "your-deepseek-api-key"):
            console.print("[red]API 模式下 api_key 不能为空或占位符[/red]")
            console.print("请在 config.yaml 中填入真实的 API 密钥")
            sys.exit(1)
        llm.setdefault("base_url", "https://api.deepseek.com/v1")
        llm.setdefault("model", "deepseek-chat")

    # 全局默认值（两种模式共用）
    llm.setdefault("temperature", 0.1)
    llm.setdefault("max_tokens", 2048)

    return config


def display_result(msg, index: int | None = None):
    """使用 Rich 美化展示解析结果。"""
    status = msg.parse_status
    style = STATUS_STYLES.get(status, "white")

    # 头部状态栏
    header_text = f"解析状态: {status}  |  置信度: {msg.confidence_score:.2f}"
    if index is not None:
        header_text = f"[#{index}] {header_text}"

    color_map = {"SUCCESS": "green", "PARTIAL_SUCCESS": "yellow", "UNRECOGNIZED": "red"}
    panel_color = color_map.get(status, "white")

    # 构造可读摘要
    lines = []
    lines.append(f"[bold]原始指令:[/bold] {msg.raw_text}")
    lines.append(f"[bold]消息ID:[/bold] {msg.msg_id}")
    lines.append(f"[bold]时间戳:[/bold] {msg.timestamp}")

    if msg.extracted_data:
        ed = msg.extracted_data
        lines.append(f"[bold]航班呼号:[/bold] {ed.callsign}")
        if ed.aircraft_type:
            lines.append(f"[bold]机型:[/bold] {ed.aircraft_type}")
        if ed.current_position:
            lines.append(f"[bold]当前位置:[/bold] {ed.current_position}")
        lines.append(f"[bold]动作队列 ({len(ed.action_queue)} 项):[/bold]")
        for i, action in enumerate(ed.action_queue):
            lines.append(f"  ┌─ 动作 {i+1}: [cyan]{action.action_type}[/cyan]")
            lines.append(
                f"  ├─ 路径: {' → '.join(action.routing.assigned_path) if action.routing.assigned_path else '(直连)'} → {action.routing.end_point}"
            )
            trig = action.trigger_condition
            trig_label = {
                "IMMEDIATE": "⚡ 立即执行",
                "AFTER_TRAFFIC": "🕐 等待前机",
                "ON_ATC_SIGNAL": "📻 等待指令",
            }.get(trig.trigger_type, trig.trigger_type)
            lines.append(f"  ├─ 触发: {trig_label}")
            if trig.traffic_target:
                lines.append(f"  └─ 目标: [magenta]{trig.traffic_target}[/magenta]")
            else:
                lines.append(f"  └─")

    if msg.error_payload:
        ep = msg.error_payload
        lines.append(f"[bold red]错误类型:[/bold red] {ep.error_type}")
        lines.append(f"[bold red]前端提示:[/bold red] {ep.fallback_prompt}")
        if ep.partially_parsed_fragments:
            lines.append(
                f"[bold yellow]部分提取:[/bold yellow] {json.dumps(ep.partially_parsed_fragments, ensure_ascii=False)}"
            )

    body = "\n".join(lines)

    # 全量 JSON
    json_str = msg.model_dump_json(indent=2, exclude_none=True)

    console.print()
    console.print(Panel(body, title=header_text, border_style=panel_color))
    console.print(
        Syntax(json_str, "json", theme="monokai", line_numbers=False, word_wrap=True)
    )
    console.print("─" * 60)


def run_interactive(parser: ATCCommandParser):
    """交互式 REPL 模式。"""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]ATC 地面管制指令语义解析器[/bold cyan]\n\n"
            "输入中文 ATC 指令，实时查看结构化解析结果\n"
            "输入 [bold]!batch <文件路径>[/bold] 批量运行文件中的指令\n"
            "输入 [bold]!examples[/bold] 运行内置示例\n"
            "输入 [bold]!exit[/bold] 或 Ctrl+C 退出",
            border_style="cyan",
        )
    )

    cmd_index = 0
    while True:
        try:
            user_input = console.input("\n[bold green]ATC > [/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]已退出[/yellow]")
            break

        if not user_input:
            continue

        if user_input == "!exit":
            console.print("[yellow]已退出[/yellow]")
            break

        if user_input == "!examples":
            examples_dir = Path(__file__).parent.parent / "examples"
            default_path = examples_dir / "sample_commands.txt"
            if default_path.exists():
                _run_batch_file(parser, str(default_path))
            else:
                console.print("[red]示例文件不存在[/red]")
            continue

        if user_input.startswith("!batch"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[red]用法: !batch <文件路径>[/red]")
                continue
            _run_batch_file(parser, parts[1])
            continue

        cmd_index += 1
        with console.status("[cyan]解析中...[/cyan]"):
            result = parser.parse(user_input)
        display_result(result, index=cmd_index)


def _run_batch_file(parser: ATCCommandParser, file_path: str):
    """从文件批量读取并解析指令。"""
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]文件不存在: {file_path}[/red]")
        return

    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    console.print(f"\n[cyan]批量解析 {len(lines)} 条指令...[/cyan]\n")

    for i, line in enumerate(lines):
        with console.status(f"[cyan]解析 [{i+1}/{len(lines)}]...[/cyan]"):
            result = parser.parse(line)
        display_result(result, index=i + 1)

    # 汇总统计
    success_count = sum(1 for r in [None] if r and r.parse_status == "SUCCESS")
    console.print(
        f"\n[bold]批量完成: {len(lines)} 条指令已处理[/bold]"
    )


def run_single(parser: ATCCommandParser, text: str):
    """单次解析模式。"""
    with console.status("[cyan]解析中...[/cyan]"):
        result = parser.parse(text)
    display_result(result)


def main():
    # ---- 命令行参数处理 ----
    args = sys.argv[1:]
    config_path = "config.yaml"

    # 支持 --config 参数
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1

    config = load_config(config_path)
    llm_cfg = config["llm"]

    # 启动信息
    console.print(
        f"[cyan]🚀 Provider: {llm_cfg['provider']} | "
        f"Model: {llm_cfg['model']} | "
        f"Endpoint: {llm_cfg['base_url']}[/cyan]"
    )

    parser = ATCCommandParser(
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=llm_cfg.get("model", "deepseek-chat"),
        temperature=llm_cfg.get("temperature", 0.1),
        max_tokens=llm_cfg.get("max_tokens", 2048),
    )

    if filtered_args:
        # 命令行直接解析模式
        text = " ".join(filtered_args)
        run_single(parser, text)
    else:
        # 交互模式
        run_interactive(parser)


if __name__ == "__main__":
    main()
