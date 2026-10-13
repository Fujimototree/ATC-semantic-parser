"""ATC message contract: envelope, payload branches, and ordered actions."""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ContractModel(BaseModel):
    # Do not silently drop hallucinated fields or coerce string/boolean values.
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Routing(ContractModel):
    assigned_path: list[NonBlank] = Field(description="滑行道序列，如 ['A', 'T3']")
    end_point: NonBlank = Field(description="终点/等待线，如 RWY_16L_HOLD")


class TriggerCondition(ContractModel):
    trigger_type: Literal["IMMEDIATE", "AFTER_TRAFFIC", "ON_ATC_SIGNAL"]
    traffic_target: NonBlank | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "TriggerCondition":
        if self.trigger_type == "AFTER_TRAFFIC" and self.traffic_target is None:
            raise ValueError("AFTER_TRAFFIC requires traffic_target")
        if self.trigger_type != "AFTER_TRAFFIC" and self.traffic_target is not None:
            raise ValueError("traffic_target is only valid for AFTER_TRAFFIC")
        return self


class ActionItem(ContractModel):
    action_type: Literal[
        "PUSHBACK",
        "TAXI",
        "HOLD_SHORT",
        "CROSS_RUNWAY",
        "GIVE_WAY",
        "LINE_UP",
        "CLEARED_TAKEOFF",
    ]
    routing: Routing
    trigger_condition: TriggerCondition


class ExtractedData(ContractModel):
    callsign: NonBlank = Field(description="标准航班号，如 CES5101；缺失时为 UNKNOWN")
    aircraft_type: NonBlank | None = None
    current_position: NonBlank | None = None
    action_queue: list[ActionItem] = Field(min_length=1, description="按指令顺序排列的动作")


class ErrorPayload(ContractModel):
    error_type: Literal["MISSING_CALLSIGN", "UNKNOWN_ROUTE_NODE", "FORMAT_MESS"]
    fallback_prompt: NonBlank
    partially_parsed_fragments: dict | None = None


class ATCMessage(ContractModel):
    msg_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw_text: str = Field(description="原始输入；由解析器保留，不由模型改写")
    parse_status: Literal["SUCCESS", "PARTIAL_SUCCESS", "UNRECOGNIZED"]
    confidence_score: float = Field(ge=0, le=1, description="模型自报值，未经过概率校准")
    extracted_data: ExtractedData | None = None
    error_payload: ErrorPayload | None = None

    @model_validator(mode="after")
    def validate_status_payload_consistency(self) -> "ATCMessage":
        if self.parse_status == "SUCCESS":
            if self.extracted_data is None or self.error_payload is not None:
                raise ValueError("SUCCESS requires extracted_data and forbids error_payload")
            if self.extracted_data.callsign.upper() == "UNKNOWN":
                raise ValueError("SUCCESS requires an identified callsign")
        elif self.parse_status == "UNRECOGNIZED":
            if self.error_payload is None or self.extracted_data is not None:
                raise ValueError("UNRECOGNIZED requires error_payload and forbids extracted_data")
        elif self.extracted_data is None and self.error_payload is None:
            raise ValueError("PARTIAL_SUCCESS requires at least one payload")
        elif (
            self.extracted_data is not None
            and self.extracted_data.callsign.upper() == "UNKNOWN"
            and self.error_payload is None
        ):
            raise ValueError("An unknown callsign requires an error_payload")
        return self
