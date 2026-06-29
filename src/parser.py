"""ATC 指令语义解析器 — 基于 LLM 的结构化解析引擎。"""

import json
import logging
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from .schema import ATCMessage, ErrorPayload
from .prompts import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE

logger = logging.getLogger(__name__)


class ATCCommandParser:
    """基于 LLM 的 ATC 指令语义解析器。

    使用 OpenAI 兼容 API 将中文 ATC 语音识别文本解析为结构化的 ATCMessage。
    支持多种后端：Ollama（本地）、DeepSeek、OpenAI 及其他兼容服务商。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        """
        Args:
            api_key: API 密钥（Ollama 本地模式可传占位符 "ollama"）
            base_url: API 端点地址（Ollama 默认 http://localhost:11434/v1）
            model: 模型名称
            temperature: 生成温度（低温度提高一致性）
            max_tokens: 最大输出 token 数
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def parse(self, raw_text: str) -> ATCMessage:
        """解析单条 ATC 指令。

        Args:
            raw_text: 原始语音识别文本

        Returns:
            结构化的 ATCMessage，即使解析失败也返回带 error_payload 的结果
        """
        logger.info("Parsing: %s", raw_text[:80])

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_MESSAGE_TEMPLATE.format(raw_text=raw_text)},
                ],
            )

            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM returned empty response")

            # 清理可能的 Markdown 代码块标记
            content = self._clean_json_response(content)

            # 解析 JSON 并校验 Schema
            data = json.loads(content)
            msg = ATCMessage.model_validate(data)

            logger.info(
                "Parse result: status=%s, confidence=%.2f",
                msg.parse_status,
                msg.confidence_score,
            )
            return msg

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Parse/validation error: %s", e)
            return self._build_fallback(raw_text, str(e))

        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return self._build_fallback(raw_text, f"LLM_API_ERROR: {e}")

    def parse_batch(self, texts: list[str]) -> list[ATCMessage]:
        """批量解析多条 ATC 指令。

        Args:
            texts: 原始语音识别文本列表

        Returns:
            ATCMessage 列表，顺序与输入一致
        """
        return [self.parse(t) for t in texts]

    def _clean_json_response(self, content: str) -> str:
        """清理 LLM 响应中可能包含的 Markdown 代码块标记。"""
        content = content.strip()
        if content.startswith("```"):
            # 去掉开头的 ```json 或 ```
            first_newline = content.find("\n")
            if first_newline != -1:
                content = content[first_newline + 1:]
            # 去掉结尾的 ```
            if content.endswith("```"):
                content = content[:-3]
        return content.strip()

    def _build_fallback(self, raw_text: str, error_detail: str) -> ATCMessage:
        """构建解析失败时的降级响应。"""
        return ATCMessage(
            raw_text=raw_text,
            parse_status="UNRECOGNIZED",
            confidence_score=0.0,
            extracted_data=None,
            error_payload=ErrorPayload(
                error_type="FORMAT_MESS",
                fallback_prompt="系统解析异常，请管制员重新发布指令或启用备用通信流程。",
                partially_parsed_fragments={"error_detail": error_detail},
            ),
        )
