# ATC-semantic-parser

面向机场地面管制仿真的中文指令解析工具。输入已转写的管制文本，通过 OpenAI 兼容接口调用语言模型，输出带航班呼号、动作队列、路径和触发条件的 JSON。支持本地 Ollama 和远程 API。

项目负责文本到结构化指令的接口。语音识别、机场地图和飞机执行逻辑由接入方提供。

## 版本

| 版本 | 内容 |
| --- | --- |
| `v1.0.0` | 原有文本解析、消息模型与双后端配置 |
| `v1.1.0` | 输出契约校验、批处理接口、错误处理与离线回归测试；当前主版本 |

## 要处理的问题

地面管制指令常把动作、路径和执行条件放在同一句话里。例如“让国航1502先通过，然后沿B、T3滑行至18右跑道外等待”，既包含让行关系，也包含后续滑行路径。解析结果需要保留动作顺序，还要区分立即执行、等待交通目标和等待后续指令。

模型负责语义提取，程序负责输入检查、数据契约和失败处理。解析结果通过校验后，接入方仍需核对实际航班和机场状态。

## 模块职责

- `src/config.py`：读取 YAML，补齐运行模式默认值，校验参数，解析环境变量密钥。
- `src/parser.py`：发起模型请求、处理错误、清理完整代码围栏、拒绝重复 JSON 键。
- `src/schema.py`：定义消息、业务载荷、错误载荷和动作队列，校验跨字段关系。
- `src/prompts.py`：规定输出格式，提供七组示例；示例本身也接受测试校验。
- `src/cli.py`：交互模式、单条解析、文件批处理和 JSON 导出。

## 设计取舍

**有序动作队列。** 每个动作单独携带路径和触发条件，按指令顺序组合。推出后滑行示例拆为 `PUSHBACK` 和 `TAXI`，接入方可以据此组织状态机；动作之间的完成条件由执行器处理。

**确定性校验。** 模型输出经过 JSON 解码、严格类型检查和跨字段检查。额外字段、空动作、重复键和不一致的交通触发条件会导致失败结果。Schema 检查的是数据契约，航班身份和路径合法性需要机场数据支持。

**输入归属与追踪。** 原文、消息 ID 和 UTC 时间由调用程序保留或生成，保证解析结果能够对应到实际请求。模型返回的这三个字段会被替换。

**统一模型接口。** 本地和远程模型共用 OpenAI 兼容请求方式。普通请求配合本地校验，适用于当前的双后端配置；不同服务商的参数兼容性和语义效果需要分别验证。

**离线验证。** SDK 请求通过内存 HTTP 模拟传输测试，覆盖成功响应和超时；七组提示词示例与 README 示例也接受 Schema 校验。工程测试与真实模型效果评测分别记录。

## 安装与运行

需要 Python 3.10 或更高版本。在 PowerShell 中：

```powershell
git clone https://github.com/Fujimototree/ATC-semantic-parser.git
cd ATC-semantic-parser
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
```

下文的 `python` 指已安装依赖的解释器。在 Windows 上也可以一直使用 `.\.venv\Scripts\python.exe`；在 Linux/macOS 上，虚拟环境解释器为 `.venv/bin/python`，复制配置用 `cp config.example.yaml config.yaml`。

### 本地 Ollama

安装并启动 [Ollama](https://ollama.com/)，拉取与配置一致的模型：

```text
ollama pull qwen2.5:7b
```

模板默认使用以下设置：

```yaml
llm:
  provider: ollama
  base_url: http://localhost:11434/v1
  model: qwen2.5:7b
  temperature: 0.1
  max_tokens: 2048
  timeout: 60.0
  max_retries: 1
```

`provider: ollama` 会自动使用占位密钥。请求发送到 `base_url` 指定的地址；保持默认回环地址时，推理请求在本机完成。模型下载和本机计算资源仍需自行准备。

### 远程或其他兼容服务

用下面的配置替换整个 `llm` 段，不要在同一个 YAML 中保留两个 `llm`：

```yaml
llm:
  provider: api
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  temperature: 0.1
  max_tokens: 2048
  timeout: 60.0
  max_retries: 1
```

通过环境变量传入密钥：

```powershell
$env:ATC_API_KEY = "填入服务商密钥"
python run_demo.py "海航7888，36L跑道外等待。"
```

Linux/macOS 使用 `export ATC_API_KEY='填入服务商密钥'`。`ATC_API_KEY` 优先于 YAML 中的 `api_key`；只在 API 模式读取。旧配置未写 `provider` 时仍按 `api` 处理。`config.yaml` 被 Git 忽略，但自定义配置文件名需要自行排除。

这里使用普通 Chat Completions 请求与本地校验，没有假定服务端支持严格结构化输出。不同后端的参数兼容性和中文解析效果需要实际测试。

### 命令行

```text
# 交互模式
python run_demo.py

# 单条指令，保留原有调用方式
python run_demo.py "国航1502，可以推出开车，沿A滑行道滑行至36L跑道外等待点。"

# 可用于脚本的批处理
python run_demo.py --batch examples/sample_commands.txt

# 只向标准输出写 JSON；单条为对象，批处理为数组
python run_demo.py --json "海航7888，36L跑道外等待。"
python run_demo.py --batch examples/sample_commands.txt --json --output results.json

# 指定配置或查看参数
python run_demo.py --config config.yaml --json "海航7888，36L跑道外等待。"
python run_demo.py --help
```

交互模式支持 `!batch <路径>`、`!examples` 和 `!exit`。批处理按文件顺序串行请求，忽略空行和以 `#` 开头的注释（允许前导空格），支持 UTF-8 BOM。`--output` 需要 `--json`，输出目录须已存在。

非交互调用的退出码：`0` 表示全部为 `SUCCESS`；`2` 表示至少一条为 `PARTIAL_SUCCESS` 或 `UNRECOGNIZED`，也用于命令行参数错误；`1` 表示配置或文件错误；`130` 表示处理中断。运行 `--help` 不需要配置文件或模型服务。

## 输出契约

顶层使用 `ATCMessage`。以下示例通过 Schema 校验，用于说明字段结构：

```json
{
  "msg_id": "a1b2c3d4e5f6478890abcdef12345678",
  "timestamp": "2026-10-13T00:00:00+00:00",
  "raw_text": "海航7888，36L跑道外等待。",
  "parse_status": "SUCCESS",
  "confidence_score": 0.95,
  "extracted_data": {
    "callsign": "CHH7888",
    "aircraft_type": null,
    "current_position": null,
    "action_queue": [
      {
        "action_type": "HOLD_SHORT",
        "routing": {"assigned_path": [], "end_point": "RWY_36L_HOLD"},
        "trigger_condition": {"trigger_type": "IMMEDIATE", "traffic_target": null}
      }
    ]
  },
  "error_payload": null
}
```

| 状态 | 校验规则 | 接入侧处理建议 |
| --- | --- | --- |
| `SUCCESS` | 有业务载荷、非空动作队列和已识别呼号；没有错误载荷 | 再核对航班、机场节点和执行条件 |
| `PARTIAL_SUCCESS` | 至少有一种载荷；`UNKNOWN` 呼号必须带错误载荷 | 保留结果供澄清，避免自动派发动作 |
| `UNRECOGNIZED` | 只有错误载荷，没有业务动作 | 记录失败并人工核对原文 |

`msg_id` 使用本地生成的 32 位 UUID hex，`timestamp` 使用本地 UTC 时间，`raw_text` 保留调用方的原始字符串。为兼容旧模型输出，解析器会移除模型生成的这三个字段并重新填充。接入旧版时，应检查对 12 位消息 ID 的长度假设。

`confidence_score` 是模型自报数值，未做概率校准。程序只检查它是有限数值且位于 `[0, 1]`，不能据此宣称解析准确率。

### 动作与触发条件

Schema 枚举 `PUSHBACK`、`TAXI`、`HOLD_SHORT`、`CROSS_RUNWAY`、`GIVE_WAY`、`LINE_UP`、`CLEARED_TAKEOFF`。其中 `CLEARED_TAKEOFF` 目前只有枚举定义，没有专门的提示词示例或真实模型效果验证。复合指令使用按原始指令顺序排列的 `action_queue`；推出后滑行示例分为两个动作。

`routing.assigned_path` 是节点序列，`end_point` 是非空终点字符串。当前程序不会查询真实机场地图，也不会检查节点存在性、路径连通性或跑道占用。

| `trigger_type` | 含义 | `traffic_target` |
| --- | --- | --- |
| `IMMEDIATE` | 到该动作时立即执行 | 必须为 `null` 或省略 |
| `AFTER_TRAFFIC` | 等待指定交通目标 | 必须为非空字符串 |
| `ON_ATC_SIGNAL` | 等待后续指令 | 必须为 `null` 或省略 |

触发字段一致性属于结构检查。交通目标是否确实对应某架飞机，仍需调用方核对。仅有机型或昵称时，提示词要求返回待澄清状态；这条语义规则并没有独立的确定性验证器。

### 失败处理

空白输入或超过 10,000 字符的输入不会调用模型。请求失败、空响应、截断输出、服务端拒绝、非法 JSON 或 Schema 不通过时，解析器返回 `UNRECOGNIZED`。程序生成的失败原因放在 `error_payload.partially_parsed_fragments.error_code`：

`INPUT_ERROR`、`LLM_API_ERROR`、`EMPTY_RESPONSE`、`TRUNCATED_RESPONSE`、`REFUSED_RESPONSE`、`INVALID_JSON`、`SCHEMA_VALIDATION_ERROR`。

模型返回的领域错误仍使用 `MISSING_CALLSIGN`、`UNKNOWN_ROUTE_NODE`、`FORMAT_MESS`。原始服务商错误正文和校验输入不会进入程序生成的错误结果；解析器日志也不记录原始指令。JSON 导出本身包含原文，请按数据用途管理导出文件。

## Python 接入

```python
from src.config import load_config
from src.parser import ATCCommandParser

config = load_config("config.yaml")
with ATCCommandParser(
    api_key=config.api_key.get_secret_value(),
    base_url=config.base_url,
    model=config.model,
    temperature=config.temperature,
    max_tokens=config.max_tokens,
    timeout=config.timeout,
    max_retries=config.max_retries,
) as parser:
    message = parser.parse("海航7888，36L跑道外等待。")
    payload = message.model_dump(mode="json")
```

`parse_batch(texts)` 顺序调用 `parse`，不提供并发或流式能力。传入非字符串属于调用错误，会抛出 `TypeError`。解析器自己创建的 SDK 客户端由 `close()` 或上下文管理器关闭；传入 `client=` 时生命周期由调用方负责。

`timeout` 是 SDK 请求超时设置；重试会延长总耗时，不能把它当成整批任务的执行期限。`max_retries` 控制 SDK 对符合条件的传输或服务错误的重试，不会重复尝试修复非法 JSON。

## 测试与维护

```text
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m pip check
python -m pip_audit -r requirements.txt
```

测试不需要密钥、Ollama 或外网推理服务。覆盖消息分支、空动作与触发约束、JSON 代码围栏与重复键、原文及元数据保留、请求超时、配置兼容、密钥优先级、批处理和 JSON 输出；SDK 路径通过内存中的 HTTP 模拟传输验证。

GitHub Actions 在 Python 3.10 和 3.12 上运行测试、静态检查、格式检查、依赖一致性与已知漏洞审计。依赖文件设置版本范围，安装时解析范围内的版本，尚未提供完整依赖锁文件。

`examples/sample_commands.txt` 是用于手动观察模型行为的十二条输入，没有标注标准答案，不能用于计算准确率。契约检查、验证结果和兼容性变化见 [工程记录](docs/engineering-review.md)。

## 当前边界

本项目尚未提供真实模型的标注评测、ASR 噪声鲁棒性测量、机场拓扑验证或执行引擎。提示词约束不能替代这些检查；合法 JSON 也可能包含错误的航班、路径或动作。当前定位是仿真接口原型，不能直接承担运行中的管制决策。

仓库尚未提供 LICENSE 文件，许可证待明确。
