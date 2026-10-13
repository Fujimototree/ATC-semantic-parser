"""离线回归测试共用的数据。"""

import pytest


@pytest.fixture
def success_data():
    return {
        "raw_text": "海航7888，36L跑道外等待。",
        "parse_status": "SUCCESS",
        "confidence_score": 0.95,
        "extracted_data": {
            "callsign": "CHH7888",
            "action_queue": [
                {
                    "action_type": "HOLD_SHORT",
                    "routing": {"assigned_path": [], "end_point": "RWY_36L_HOLD"},
                    "trigger_condition": {"trigger_type": "IMMEDIATE", "traffic_target": None},
                }
            ],
        },
        "error_payload": None,
    }
