import json
from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError, OpenAI
from openai.types.chat import ChatCompletion

from src.parser import MAX_INPUT_CHARS, ATCCommandParser


def completion(content, finish_reason="stop", choices=True):
    return ChatCompletion.model_validate(
        {
            "id": "test",
            "created": 0,
            "model": "test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ]
            if choices
            else [],
        }
    )


def fake_parser(content, **kwargs):
    client = MagicMock()
    client.chat.completions.create.return_value = completion(content, **kwargs)
    return ATCCommandParser(api_key="unused", client=client), client


def error_code(message):
    return message.error_payload.partially_parsed_fragments["error_code"]


def test_metadata_comes_from_program(success_data):
    success_data.update(msg_id="fake", timestamp="fake", raw_text="rewritten")
    parser, _ = fake_parser(json.dumps(success_data))
    first = parser.parse("  原始指令\n")
    second = parser.parse("  原始指令\n")
    assert first.raw_text == "  原始指令\n"
    assert first.msg_id != second.msg_id and len(first.msg_id) == 32
    assert datetime.fromisoformat(first.timestamp).utcoffset().total_seconds() == 0


def test_metadata_can_be_omitted(success_data):
    success_data.pop("raw_text")
    parser, _ = fake_parser(json.dumps(success_data))
    assert parser.parse("指令").parse_status == "SUCCESS"


@pytest.mark.parametrize(
    "wrapper", ["{}", "\x60\x60\x60json\n{}\n\x60\x60\x60", "\x60\x60\x60\n{}\n\x60\x60\x60"]
)
def test_plain_and_fenced_json(success_data, wrapper):
    parser, _ = fake_parser(wrapper.format(json.dumps(success_data)))
    assert parser.parse("指令").parse_status == "SUCCESS"


@pytest.mark.parametrize(
    "content",
    [
        "not JSON",
        "[]",
        "null",
        '{"parse_status":"SUCCESS","parse_status":"UNRECOGNIZED"}',
        '说明\n{"parse_status":"SUCCESS"}',
        "\x60\x60\x60json\n{}\n",
    ],
)
def test_invalid_json_returns_failure(content):
    parser, _ = fake_parser(content)
    message = parser.parse("指令")
    assert message.parse_status == "UNRECOGNIZED"
    assert message.extracted_data is None and error_code(message) == "INVALID_JSON"


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_output(content):
    parser, _ = fake_parser(content)
    assert error_code(parser.parse("指令")) == "EMPTY_RESPONSE"


def test_empty_choices():
    parser, _ = fake_parser(None, choices=False)
    assert error_code(parser.parse("指令")) == "EMPTY_RESPONSE"


def test_truncated_valid_json_is_rejected(success_data):
    parser, _ = fake_parser(json.dumps(success_data), finish_reason="length")
    assert error_code(parser.parse("指令")) == "TRUNCATED_RESPONSE"


def test_schema_error_does_not_expose_output():
    parser, _ = fake_parser('{"secret":"sensitive-model-output"}')
    result = parser.parse("指令")
    assert error_code(result) == "SCHEMA_VALIDATION_ERROR"
    assert "sensitive-model-output" not in result.model_dump_json()


@pytest.mark.parametrize("text", ["", "  \n ", "a" * (MAX_INPUT_CHARS + 1)])
def test_invalid_input_does_not_call_backend(text):
    parser, client = fake_parser(None)
    assert error_code(parser.parse(text)) == "INPUT_ERROR"
    client.chat.completions.create.assert_not_called()


def test_non_string_input():
    parser, client = fake_parser(None)
    with pytest.raises(TypeError):
        parser.parse(None)
    client.chat.completions.create.assert_not_called()


def test_api_error_is_redacted(caplog):
    parser, client = fake_parser(None)
    client.chat.completions.create.side_effect = APIConnectionError(
        message="credential-and-provider-body",
        request=httpx.Request("POST", "https://test.invalid"),
    )
    result = parser.parse("private-source-text")
    assert error_code(result) == "LLM_API_ERROR"
    assert "credential-and-provider-body" not in result.model_dump_json() + caplog.text
    assert "private-source-text" not in caplog.text


def test_batch_keeps_order(success_data):
    parser, client = fake_parser(json.dumps(success_data))
    messages = parser.parse_batch(["first", "second"])
    assert [message.raw_text for message in messages] == ["first", "second"]
    assert client.chat.completions.create.call_count == 2
    assert parser.parse_batch([]) == []


def test_injected_client_is_not_closed():
    parser, client = fake_parser(None)
    parser.close()
    client.close.assert_not_called()


def test_real_sdk_transport_success_and_timeout_configuration(success_data):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion(json.dumps(success_data)).model_dump())

    transport = httpx.MockTransport(handle)
    with OpenAI(
        api_key="offline-test",
        base_url="https://test.invalid/v1",
        timeout=3.0,
        max_retries=0,
        http_client=httpx.Client(transport=transport),
    ) as client:
        with ATCCommandParser(api_key="unused", model="test", client=client) as parser:
            message = parser.parse("海航7888，36L跑道外等待。")
            assert message.parse_status == "SUCCESS"
    assert requests[0]["model"] == "test"
    assert requests[0]["messages"][1]["content"].endswith(message.raw_text)


def test_real_sdk_timeout_returns_failure():
    def handle(request):
        raise httpx.ReadTimeout("sensitive-detail", request=request)

    with OpenAI(
        api_key="offline-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        parser = ATCCommandParser(api_key="unused", client=client)
        assert error_code(parser.parse("指令")) == "LLM_API_ERROR"
