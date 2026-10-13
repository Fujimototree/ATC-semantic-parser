# 解析器契约与工程验证记录

检查日期：2026-10-13。基线版本：`v1.0.0`，当前版本：`v1.1.0`。

## 检查范围

检查仓库全部源码、提示词、Schema、配置模板、示例文件、依赖和 README。以基线提交为检查对象，使用独立环境复现问题、运行回归测试和核对依赖。

项目采用单进程、同步请求的命令行解析结构。核心调用链为 CLI → OpenAI 兼容 Chat Completions → JSON → Pydantic。当前规模保留这一调用方式，重点处理失败边界和接口契约。

## 发现与处理

| 问题 | 原始行为及证据 | 修改后的行为 |
| --- | --- | --- |
| 旧配置的默认模式未写回 | `llm` 仅含密钥时，启动输出触发 `KeyError('provider')`；已在基线复现 | `LLMConfig` 显式解析默认 `api` 模式，CLI 使用完整配置 |
| 输出约束不足 | 空动作、`UNKNOWN` 呼号和额外字段同时出现时，基线仍接受 `SUCCESS`；已复现 | 非空动作、非空路径字段、严格类型、拒绝额外字段；成功状态不能使用 `UNKNOWN` |
| 模型负责原文和元数据 | 基线输入 `original`，模拟模型返回 `rewritten`，最终原文随之改变；已复现 | 原文保留调用输入；UUID 和 UTC 时间由本地生成；兼容并替换旧输出中的元数据 |
| 请求错误暴露内部内容 | 模拟私有服务商异常正文进入 `error_detail`；已在基线复现 | 结果使用稳定错误码，解析器日志只记录异常类名，配置校验不展示字段值 |
| 批处理缺少可用统计 | 基线统计遍历 `[None]`，没有根据实际结果计算状态 | 按真实结果计数，增加非交互 `--batch`、纯 JSON 输出、文件导出及退出码 |
| 请求缺少项目层面的耗时配置 | 原始构造只提供密钥与端点 | 增加 `timeout` 和 `max_retries`，由 SDK 执行重试，避免额外叠加重试循环 |
| 提示词与动作拆分规则不一致 | 推出后滑行示例只生成一个动作；让行示例把机型写成交通目标 | 推出与滑行分开；明确呼号让行示例；模糊目标要求澄清，并说明该要求尚非独立语义校验 |
| 文档与仓库不一致 | 安装路径为旧项目名，远端地址占位；没有 LICENSE 却声明 MIT；本地运行和校验效果有过度保证 | 使用真实仓库地址和当前命令，写清实现范围、输出契约、验证方法和许可证待确认状态 |

## 实现过程

1. 确认基线提交与源码范围，检查从配置加载到模型响应解码的调用链。
2. 从基线建立独立工作副本，复现启动、输出契约、原文保留和错误信息处理问题。
3. 将配置解析从展示逻辑分离，使用 Pydantic 校验数值、模式、模型和端点；密钥支持 `ATC_API_KEY` 优先，配置表示使用 `SecretStr`。
4. 保留 `ATCCommandParser.parse` / `parse_batch` 和原有位置参数，增加可注入 SDK 客户端、上下文管理器及客户端关闭。
5. 增加确定性的输入、JSON 和 Schema 校验。只清理完整代码围栏；拒绝重复键、非对象结果、截断和空响应，失败结果不携带动作。
6. 用 `argparse` 替代手工参数遍历。批处理顺序不变；Rich 展示将输入视作普通文本，JSON 模式绕过终端格式化。
7. 增加离线测试、开发依赖和 CI。重写 README 后，对其 JSON 示例也运行 Schema 校验。

## 验证结果

| 检查 | 结果与范围 |
| --- | --- |
| 回归测试 | Windows / Python 3.10.20：101 passed |
| 静态检查 | `ruff check .` 通过 |
| 格式检查 | `ruff format --check .` 通过 |
| 依赖一致性 | `pip check`：No broken requirements found |
| 已知漏洞审计 | 对当前解析出的 23 个运行依赖的精确版本执行 pip-audit，0 个已知漏洞 |
| 提示词和文档 | 七个提示词 JSON 示例及 README JSON 示例通过契约校验 |
| SDK 集成路径 | 使用真实 OpenAI SDK 与内存 HTTP MockTransport 验证请求成功和超时失败，无外网推理 |
| Git 差异 | `git diff --check` 通过 |

本地验证的主要版本：OpenAI SDK 2.54.0、Pydantic 2.14.1、Rich 14.3.4、PyYAML 6.0.3。运行依赖设置兼容范围；开发检查依赖单列到 `requirements-dev.txt`。已知漏洞结果是检查时的数据库状态，不是永久保证。

CI 配置覆盖 Python 3.10 / 3.12，并运行回归、静态检查、格式检查、依赖一致性与运行依赖审计。工作流仅有 `contents: read`，所用 Actions 固定到提交 SHA。本记录中的 101 passed 指本地验证，持续集成结果见仓库 Actions 页面。

## 兼容性变化

- 消息 ID 从模型生成的 12 位示例改为本地 32 位 UUID hex；依赖长度的前端需要相应调整。
- 模型输出中的未知字段、字符串形式的数字、空动作或无目标的 `AFTER_TRAFFIC` 将被拒绝，返回 `UNRECOGNIZED`。
- 非交互调用遇到部分成功或无法识别会退出 `2`，批处理脚本应读取 JSON 并检查退出码。
- 配置不再接受未知字段，缺少 `provider` 的旧 API 配置仍兼容；内部 `load_config` 返回类型改为 `LLMConfig`。
- 基线宽泛捕获所有异常；现在 SDK 请求错误和模型输出错误有明确降级路径，非法 Python 参数抛出 `TypeError`，程序缺陷不作为模型失败静默吞掉。

## 尚未验证的内容

模型调用通过模拟传输验证，尚未测量 Qwen、DeepSeek 或其他后端的语义准确率、延迟或 ASR 鲁棒性。十二条示例没有标准答案，不能计算准确率。`confidence_score` 仍是未经校准的模型自报数值。

Schema 不核验呼号是否存在、机场路径是否连通、交通目标身份、跑道占用或多动作执行时序。提示词要求澄清模糊目标，但尚无独立的确定性语义检查。后续应先建立带人工标注的评测样本和机场节点校验，再讨论自动派发动作。

配置支持 HTTP 以接入本机服务；远端携带密钥时应配置 HTTPS。仓库尚未提供 LICENSE 文件，许可证待明确。

## 参考

- [Pydantic 模型与字段校验](https://docs.pydantic.dev/latest/concepts/models/)
- [OpenAI SDK 错误类型](https://developers.openai.com/api/docs/guides/error-codes)
- [SDK 重试与请求期限说明](https://developers.openai.com/api/docs/guides/rate-limits)
- [Ollama 的 OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)
