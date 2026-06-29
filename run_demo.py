#!/usr/bin/env python
"""ATC 地面管制指令语义结构化解析 — 演示入口。

用法:
    python run_demo.py                          # 交互式 REPL 模式
    python run_demo.py "国航1502，可以推出..."   # 单条指令解析
    python run_demo.py --config my_config.yaml  # 指定配置文件

配置文件:
    首次使用请复制 config.example.yaml 为 config.yaml 并编辑对应配置。
    支持两种运行模式：
      • Ollama 本地模式 — 无需 API Key，数据不出本机
      • API 远程模式 — DeepSeek / OpenAI 等远程服务
"""

from src.cli import main

if __name__ == "__main__":
    main()
