# ATC 地面管制指令语义结构化解析器

基于 LLM 的中文空中交通管制（ATC）语音识别文本语义解析工具，将自然语言指令转换为结构化 JSON，供空管仿真平台系统解析接入。

## ✨ 特性

- **LLM 驱动**：利用大语言模型理解灵活多变的中文管制用语，无需手写规则
- **双模式部署**：支持 Ollama 本地运行（零成本、数据不出本机）或远程 API（DeepSeek / OpenAI 等）
- **结构化输出**：三级 Pydantic Schema 校验，确保输出可靠
- **优雅降级**：无法解析时返回 `error_payload` + 前端友好提示，不会崩溃
- **交互式 REPL**：支持单条指令解析、批量文件解析、交互式命令行
- **复合指令支持**：自动拆解"先让行再滑行"类多步指令

## 📦 支持的指令类型

| 动作类型            | 说明       | 示例                             |
| ------------------- | ---------- | -------------------------------- |
| `PUSHBACK`        | 推出开车   | "国航1502，可以推出开车"         |
| `TAXI`            | 滑行       | "沿A滑行道滑行至36L跑道外等待点" |
| `HOLD_SHORT`      | 跑道外等待 | "海航7888，36L跑道外等待"        |
| `CROSS_RUNWAY`    | 穿越跑道   | "可以穿越22L跑道"                |
| `GIVE_WAY`        | 让行/避让  | "避让前方落地的大白鲸330"        |
| `LINE_UP`         | 进跑道等待 | "可以进跑道16L等待"              |
| `CLEARED_TAKEOFF` | 起飞许可   | （框架已预留）                   |

**触发条件**：`IMMEDIATE`（立即执行）、`AFTER_TRAFFIC`（等待前机）、`ON_ATC_SIGNAL`（等待进一步指令）

## 🚀 快速开始

### 前置条件

- Python 3.10+
- 任选其一：
  - **Ollama**（本地模式）：安装 [Ollama](https://ollama.com) 并拉取模型 `ollama pull qwen2.5:7b`
  - **API 密钥**（远程模式）：DeepSeek 或 OpenAI 兼容的 API Key

### 安装

```bash
git clone <your-repo-url>
cd ATC_Command-demo
pip install -r requirements.txt
```

### 配置

```bash
# 从模板创建配置文件
cp config.example.yaml config.yaml
```

**Ollama 本地模式**（config.yaml）：

```yaml
llm:
  provider: "ollama"
  base_url: "http://localhost:11434/v1"
  model: "qwen2.5:7b"
  temperature: 0.1
  max_tokens: 2048
```

**API 远程模式**（config.yaml）：

```yaml
llm:
  provider: "api"
  api_key: "sk-your-api-key"
  base_url: "https://api.deepseek.com/v1"
  model: "deepseek-chat"
  temperature: 0.1
  max_tokens: 2048
```

> ⚠️ `config.yaml` 包含敏感信息，已在 `.gitignore` 中排除，不会被提交。

### 运行

```bash
# 交互式 REPL 模式
python run_demo.py

# 单条指令解析
python run_demo.py "国航1502，可以推出开车，沿A滑行道滑行至36L跑道外等待点。"

# 批量解析文件
# 在 REPL 中输入: !batch examples/sample_commands.txt

# 指定配置文件
python run_demo.py --config my_config.yaml
```

## 📊 输出示例

输入：

```
东方5101，避让一下前方落地的大白鲸330，然后沿B、T3滑行至18右跑道外等待。
```

输出：

```json
{
  "msg_id": "b2c3d4e5f6a1",
  "timestamp": "2026-06-04T08:05:00.000Z",
  "raw_text": "东方5101，避让一下前方落地的大白鲸330，然后沿B、T3滑行至18右跑道外等待。",
  "parse_status": "SUCCESS",
  "confidence_score": 0.92,
  "extracted_data": {
    "callsign": "CES5101",
    "action_queue": [
      {
        "action_type": "GIVE_WAY",
        "routing": { "assigned_path": [], "end_point": "CURRENT_POSITION" },
        "trigger_condition": { "trigger_type": "AFTER_TRAFFIC", "traffic_target": "A330" }
      },
      {
        "action_type": "TAXI",
        "routing": { "assigned_path": ["B", "T3"], "end_point": "RWY_18R_HOLD" },
        "trigger_condition": { "trigger_type": "IMMEDIATE", "traffic_target": null }
      }
    ]
  },
  "error_payload": null
}
```

## 📁 项目结构

```
ATC_Command-demo/
├── run_demo.py              # 入口脚本
├── config.example.yaml      # 配置文件模板（可提交）
├── config.yaml              # 用户配置（.gitignore 排除）
├── requirements.txt         # Python 依赖
├── src/
│   ├── cli.py               # 命令行界面 & 配置加载
│   ├── parser.py            # LLM 解析引擎核心
│   ├── prompts.py           # 系统提示词 & Few-shot 示例
│   └── schema.py            # Pydantic 数据模型（3 层嵌套）
└── examples/
    └── sample_commands.txt  # 示例指令集（12 条，覆盖各种场景）
```

## 🔧 配置参考

| 字段            | 说明     | Ollama 默认值                 | API 默认值                      |
| --------------- | -------- | ----------------------------- | ------------------------------- |
| `provider`    | 运行模式 | `"ollama"`                  | `"api"`                       |
| `api_key`     | API 密钥 | 自动填`"ollama"`            | **必填**                  |
| `base_url`    | 端点地址 | `http://localhost:11434/v1` | `https://api.deepseek.com/v1` |
| `model`       | 模型名称 | `qwen2.5:7b`                | `deepseek-chat`               |
| `temperature` | 生成温度 | `0.1`                       | `0.1`                         |
| `max_tokens`  | 最大输出 | `2048`                      | `2048`                        |

## 🛠 技术栈

- **LLM 客户端**：[OpenAI Python SDK](https://github.com/openai/openai-python)（兼容 Ollama / DeepSeek / OpenAI 等所有 OpenAI 兼容 API）
- **数据校验**：[Pydantic v2](https://docs.pydantic.dev/) — 3 层嵌套 Schema + 跨字段一致性校验
- **终端美化**：[Rich](https://github.com/Textualize/rich) — 语法高亮、面板、表格
- **配置解析**：[PyYAML](https://pyyaml.org/)

## 📄 License

MIT