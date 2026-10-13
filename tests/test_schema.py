import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.prompts import SYSTEM_PROMPT
from src.schema import ATCMessage, TriggerCondition


def test_success_contract(success_data):
    message = ATCMessage.model_validate(success_data)
    assert message.extracted_data.callsign == "CHH7888"
    assert len(message.msg_id) == 32


@pytest.mark.parametrize(
    "change",
    [
        {"extracted_data": None},
        {"confidence_score": "0.9"},
        {"confidence_score": True},
        {"confidence_score": float("nan")},
        {"confidence_score": float("inf")},
        {"confidence_score": 1.1},
        {"unexpected_field": "must not be silently dropped"},
    ],
)
def test_invalid_success_envelope(success_data, change):
    success_data.update(change)
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)


@pytest.mark.parametrize("callsign", ["", "   ", "UNKNOWN", "unknown"])
def test_success_requires_callsign(success_data, callsign):
    success_data["extracted_data"]["callsign"] = callsign
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)


def test_success_cannot_have_error(success_data):
    success_data["error_payload"] = {"error_type": "FORMAT_MESS", "fallback_prompt": "核对"}
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)


def test_empty_action_queue(success_data):
    success_data["extracted_data"]["action_queue"] = []
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)


@pytest.mark.parametrize("end_point", ["", " \n "])
def test_blank_route(success_data, end_point):
    success_data["extracted_data"]["action_queue"][0]["routing"]["end_point"] = end_point
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)


@pytest.mark.parametrize(
    "trigger",
    [
        {"trigger_type": "AFTER_TRAFFIC"},
        {"trigger_type": "AFTER_TRAFFIC", "traffic_target": " "},
        {"trigger_type": "IMMEDIATE", "traffic_target": "CCA1502"},
        {"trigger_type": "ON_ATC_SIGNAL", "traffic_target": "CCA1502"},
    ],
)
def test_inconsistent_trigger(trigger):
    with pytest.raises(ValidationError):
        TriggerCondition.model_validate(trigger)


def test_unrecognized_has_no_actions(success_data):
    success_data["parse_status"] = "UNRECOGNIZED"
    success_data["error_payload"] = {"error_type": "FORMAT_MESS", "fallback_prompt": "核对"}
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)


def test_partial_unknown_callsign_needs_clarification(success_data):
    success_data["parse_status"] = "PARTIAL_SUCCESS"
    success_data["extracted_data"]["callsign"] = "UNKNOWN"
    with pytest.raises(ValidationError):
        ATCMessage.model_validate(success_data)
    success_data["error_payload"] = {
        "error_type": "MISSING_CALLSIGN",
        "fallback_prompt": "确认呼号",
    }
    assert ATCMessage.model_validate(success_data).parse_status == "PARTIAL_SUCCESS"


def test_all_prompt_examples_follow_contract():
    examples = re.findall(r"\n(\{\n.*?\n\})", SYSTEM_PROMPT, re.DOTALL)
    assert len(examples) == 7
    messages = [
        ATCMessage.model_validate({**json.loads(example), "raw_text": "示例"})
        for example in examples
    ]
    assert [item.action_type for item in messages[0].extracted_data.action_queue] == [
        "PUSHBACK",
        "TAXI",
    ]
    assert messages[1].extracted_data.action_queue[0].trigger_condition.traffic_target == "CCA1502"


def test_readme_json_example_follows_contract():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    example = readme.split("\x60\x60\x60json\n", 1)[1].split("\x60\x60\x60", 1)[0]
    assert ATCMessage.model_validate(json.loads(example)).parse_status == "SUCCESS"
