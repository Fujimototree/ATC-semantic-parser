#!/usr/bin/env python
"""中文地面管制指令的命令行入口。

运行示例：
    python run_demo.py
    python run_demo.py "海航7888，36L跑道外等待。"
    python run_demo.py --config config.yaml

首次运行前，将 config.example.yaml 复制为 config.yaml。
根据配置选择本地 Ollama 服务或兼容的远程模型接口。
"""

from src.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
