"""LLM-backed ATC parsing with a validated, locally stamped result."""

import json
import logging
import re
from typing import Any

from openai import APIError, OpenAI
from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, USER_MESSAGE_TEMPLATE
from .schema import ATCMessage, ErrorPayload

logger = logging.getLogger(__name__)
MAX_INPUT_CHARS = 10_000


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class ATCCommandParser:
    """Parse text via an OpenAI-compatible backend. Batch calls are sequential."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_retries: int = 1,
        *,
        client: OpenAI | None = None,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = (
            client
            if client is not None
            else OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "ATCCommandParser":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def parse(self, raw_text: str) -> ATCMessage:
        """Return a validated message or a non-executable failure envelope.

        Invalid Python argument types raise TypeError; blank/oversized text,
        API errors and invalid model output return UNRECOGNIZED.
        """
        if not isinstance(raw_text, str):
            raise TypeError("raw_text must be a string")
        if not raw_text.strip() or len(raw_text) > MAX_INPUT_CHARS:
            return self._build_fallback(raw_text, "INPUT_ERROR")

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
        except APIError as exc:
            # Never expose provider bodies, credentials or source text in diagnostics.
            logger.warning("LLM request failed (%s)", type(exc).__name__)
            return self._build_fallback(raw_text, "LLM_API_ERROR")

        if not response.choices:
            return self._build_fallback(raw_text, "EMPTY_RESPONSE")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            return self._build_fallback(raw_text, "TRUNCATED_RESPONSE")
        if choice.finish_reason == "content_filter" or choice.message.refusal:
            return self._build_fallback(raw_text, "REFUSED_RESPONSE")
        content = choice.message.content
        if not content or not content.strip():
            return self._build_fallback(raw_text, "EMPTY_RESPONSE")

        try:
            data = json.loads(
                self._clean_json_response(content),
                object_pairs_hook=_unique_object,
            )
            if not isinstance(data, dict):
                raise ValueError("JSON response must be an object")
        except (ValueError, RecursionError):
            return self._build_fallback(raw_text, "INVALID_JSON")

        # Keep compatibility with older prompts, but never trust model metadata.
        for field in ("msg_id", "timestamp", "raw_text"):
            data.pop(field, None)
        data["raw_text"] = raw_text
        try:
            message = ATCMessage.model_validate(data)
        except ValidationError:
            return self._build_fallback(raw_text, "SCHEMA_VALIDATION_ERROR")

        logger.debug("Parse status: %s", message.parse_status)
        return message

    def parse_batch(self, texts: list[str]) -> list[ATCMessage]:
        return [self.parse(text) for text in texts]

    @staticmethod
    def _clean_json_response(content: str) -> str:
        content = content.strip()
        fenced = re.fullmatch(
            r"\x60{3}(?:json)?\s*\n(.*?)\n?\x60{3}", content, re.DOTALL | re.IGNORECASE
        )
        return fenced.group(1).strip() if fenced else content

    @staticmethod
    def _build_fallback(raw_text: str, error_code: str) -> ATCMessage:
        return ATCMessage(
            raw_text=raw_text,
            parse_status="UNRECOGNIZED",
            confidence_score=0.0,
            error_payload=ErrorPayload(
                error_type="FORMAT_MESS",
                fallback_prompt="未得到有效解析结果，请人工核对原始指令。",
                partially_parsed_fragments={"error_code": error_code},
            ),
        )
