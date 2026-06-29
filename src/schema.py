"""ATC 地面管制指令语义结构 Schema — 3 层 Pydantic 模型定义。

层级 1: ATCMessage — 消息外壳，决定执行/报错
层级 2: ExtractedData / ErrorPayload — 业务 vs 异常分支载荷
层级 3: ActionItem — 动作队列单元，驱动 Unity 飞机状态机
"""

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ── 层级 3: 动作队列单元 ──────────────────────────────────────────────

class Routing(BaseModel):
    """滑行路径信息"""
    assigned_path: list[str] = Field(description="滑行道序列，如 ['A', 'T3']")
    end_point: str = Field(description="终点/等待线，如 RWY_16L_HOLD")


class TriggerCondition(BaseModel):
    """执行触发条件"""
    trigger_type: Literal["IMMEDIATE", "AFTER_TRAFFIC", "ON_ATC_SIGNAL"] = Field(
        description="触发类型: IMMEDIATE=立刻执行, AFTER_TRAFFIC=等待前机, ON_ATC_SIGNAL=等指令"
    )
    traffic_target: Optional[str] = Field(
        default=None, description="需等待的冲突航班号，如 CCA1502"
    )


class ActionItem(BaseModel):
    """原子动作，每条指令可能包含多个动作"""
    action_type: Literal[
        "PUSHBACK", "TAXI", "HOLD_SHORT", "CROSS_RUNWAY",
        "GIVE_WAY", "LINE_UP", "CLEARED_TAKEOFF",
    ] = Field(description="动作类型")
    routing: Routing = Field(description="滑行路径")
    trigger_condition: TriggerCondition = Field(description="触发条件")


# ── 层级 2: 分支载荷 ──────────────────────────────────────────────────

class ExtractedData(BaseModel):
    """正常执行流载荷"""
    callsign: str = Field(description="标准航班号，如 CES5101")
    aircraft_type: Optional[str] = Field(default=None, description="机型，如 A330")
    current_position: Optional[str] = Field(default=None, description="当前已知位置，如 GATE_212")
    action_queue: list[ActionItem] = Field(description="原子动作队列，按管制员说话顺序排列")


class ErrorPayload(BaseModel):
    """异常处理流载荷"""
    error_type: Literal["MISSING_CALLSIGN", "UNKNOWN_ROUTE_NODE", "FORMAT_MESS"] = Field(
        description="错误类型"
    )
    fallback_prompt: str = Field(
        description="给 Unity/VR 前端显示的无感澄清提示语"
    )
    partially_parsed_fragments: Optional[dict] = Field(
        default=None, description="抢救出来的部分有效片段，供人工核对"
    )


# ── 层级 1: 消息外壳 ──────────────────────────────────────────────────

class ATCMessage(BaseModel):
    """ATC 指令消息顶层结构"""
    msg_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:12],
        description="消息唯一标识",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 时间戳",
    )
    raw_text: str = Field(description="原始语音识别文本")
    parse_status: Literal["SUCCESS", "PARTIAL_SUCCESS", "UNRECOGNIZED"] = Field(
        description="解析状态闸口"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="模型置信度"
    )
    extracted_data: Optional[ExtractedData] = Field(
        default=None, description="结构化业务载荷"
    )
    error_payload: Optional[ErrorPayload] = Field(
        default=None, description="异常处理载荷"
    )

    @model_validator(mode="after")
    def validate_status_payload_consistency(self) -> "ATCMessage":
        """跨字段校验：parse_status 与载荷分支必须一致"""
        status = self.parse_status
        extracted = self.extracted_data
        error = self.error_payload

        if status == "SUCCESS":
            if extracted is None:
                raise ValueError("parse_status=SUCCESS 时 extracted_data 不能为空")
            if error is not None:
                raise ValueError("parse_status=SUCCESS 时 error_payload 必须为空")

        elif status == "UNRECOGNIZED":
            if error is None:
                raise ValueError("parse_status=UNRECOGNIZED 时 error_payload 不能为空")
            if extracted is not None:
                raise ValueError("parse_status=UNRECOGNIZED 时 extracted_data 必须为空")

        elif status == "PARTIAL_SUCCESS":
            # PARTIAL 时 extracted_data 和 error_payload 都可能存在
            if extracted is None and error is None:
                raise ValueError(
                    "parse_status=PARTIAL_SUCCESS 时 extracted_data 和 error_payload 至少需要一个"
                )

        return self
