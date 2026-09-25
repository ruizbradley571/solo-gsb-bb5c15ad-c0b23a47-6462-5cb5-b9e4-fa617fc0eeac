"""API 层测试：正常请求与非法参数（4xx）。"""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from reportlab.lib.units import mm

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_impose_basic_left():
    response = client.post(
        "/api/v1/impose",
        json={
            "total_pages": 16,
            "max_sheets_per_signature": 4,
            "binding": "left",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["signature_count"] == 1
    assert data["signatures"][0]["signature_index"] == 1
    assert data["signatures"][0]["sheet_count"] == 4
    first = data["signatures"][0]["sheets"][0]
    assert first["sheet_index"] == 1
    assert first["front"] == {"left": 16, "right": 1}
    assert first["back"] == {"left": 2, "right": 15}


def test_impose_right_binding():
    response = client.post(
        "/api/v1/impose",
        json={
            "total_pages": 16,
            "max_sheets_per_signature": 4,
            "binding": "right",
        },
    )
    assert response.status_code == 200
    first = response.json()["signatures"][0]["sheets"][0]
    assert first["front"] == {"left": 1, "right": 16}
    assert first["back"] == {"left": 15, "right": 2}


def test_impose_null_blank_pages():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": 1, "max_sheets_per_signature": 1, "binding": "left"},
    )
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    # 1 页补 3 空白：最外张正面 空白/1
    assert sheet["front"] == {"left": None, "right": 1}
    assert sheet["back"] == {"left": None, "right": None}


def test_invalid_total_pages_zero():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": 0, "max_sheets_per_signature": 4, "binding": "left"},
    )
    assert 400 <= response.status_code < 500
    assert response.status_code == 422


def test_invalid_total_pages_negative():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": -5, "max_sheets_per_signature": 4, "binding": "left"},
    )
    assert response.status_code == 422


def test_invalid_total_pages_not_integer():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": 1.5, "max_sheets_per_signature": 4, "binding": "left"},
    )
    assert response.status_code == 422


def test_invalid_max_sheets_zero():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": 10, "max_sheets_per_signature": 0, "binding": "left"},
    )
    assert response.status_code == 422


def test_invalid_binding_value():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": 10, "max_sheets_per_signature": 4, "binding": "top"},
    )
    assert response.status_code == 422


def test_missing_required_field():
    response = client.post(
        "/api/v1/impose",
        json={"total_pages": 10, "max_sheets_per_signature": 4},
    )
    assert response.status_code == 422


def test_unknown_field_rejected():
    response = client.post(
        "/api/v1/impose",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 4,
            "binding": "left",
            "extra": 1,
        },
    )
    assert response.status_code == 422


def test_empty_body_returns_422():
    response = client.post("/api/v1/impose", json={})
    assert response.status_code == 422


def test_impose_chapters_basic():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 20,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "chapter_starts": [1, 5, 9, 13],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["signature_count"] == 3
    ranges = [
        (s["page_start"], s["page_end"], s["blank_count"])
        for s in data["signatures"]
    ]
    assert ranges == [(1, 4, 0), (5, 12, 0), (13, 20, 0)]
    # 沿用 sheets 页位结构：首帖最外张正面 = 末页/首页
    first = data["signatures"][0]["sheets"][0]
    assert first["front"] == {"left": 4, "right": 1}
    assert first["back"] == {"left": 2, "right": 3}


def test_impose_chapters_right_binding_and_blanks():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "right",
            "chapter_starts": [1, 6, 9],
        },
    )
    assert response.status_code == 200
    sigs = response.json()["signatures"]
    assert [(s["page_start"], s["page_end"]) for s in sigs] == [(1, 8), (9, 10)]
    # 右装订镜像：最外张正面 = 首页/末页
    assert sigs[0]["sheets"][0]["front"] == {"left": 1, "right": 8}
    # 末帖 2 页补 2 空白
    assert sigs[1]["blank_count"] == 2
    assert sigs[1]["sheets"][0]["front"] == {"left": 9, "right": None}


def test_chapters_first_start_not_one():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "chapter_starts": [2, 5],
        },
    )
    assert response.status_code == 422


def test_chapters_not_strictly_increasing():
    for starts in ([1, 3, 3], [1, 5, 4]):
        response = client.post(
            "/api/v1/impose/chapters",
            json={
                "total_pages": 10,
                "max_sheets_per_signature": 2,
                "binding": "left",
                "chapter_starts": starts,
            },
        )
        assert response.status_code == 422


def test_chapters_empty_list():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "chapter_starts": [],
        },
    )
    assert response.status_code == 422


def test_chapters_start_beyond_total_pages():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "chapter_starts": [1, 11],
        },
    )
    assert response.status_code == 422


def test_chapters_single_chapter_too_long():
    # 单章 10 页 > 容量 8（2 张 × 4）-> 422
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "chapter_starts": [1],
        },
    )
    assert response.status_code == 422


def test_chapters_missing_field():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "left",
        },
    )
    assert response.status_code == 422


def test_chapters_unknown_field_rejected():
    response = client.post(
        "/api/v1/impose/chapters",
        json={
            "total_pages": 10,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "chapter_starts": [1],
            "extra": 1,
        },
    )
    assert response.status_code == 422


def test_reprint_unchanged_reuses_all():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["p1", "p2", "p3", "p4"],
            "new_page_ids": ["p1", "p2", "p3", "p4"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["signature_count"] == 1
    assert data["reprint_sheet_count"] == 0
    sheet = data["signatures"][0]["sheets"][0]
    assert sheet["front"] == {"left": "p4", "right": "p1"}
    assert sheet["back"] == {"left": "p2", "right": "p3"}
    assert sheet["reused"] is True
    assert sheet["old_signature_index"] == 1
    assert sheet["old_sheet_index"] == 1


def test_reprint_changed_page_marks_sheet():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["p1", "p2", "p3", "p4"],
            "new_page_ids": ["p1", "p2X", "p3", "p4"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": ["p2X"],
        },
    )
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert sheet["reused"] is False
    assert sheet["old_signature_index"] is None
    assert sheet["old_sheet_index"] is None
    # 新版四页位照常返回
    assert sheet["back"] == {"left": "p2X", "right": "p3"}
    assert response.json()["reprint_sheet_count"] == 1


def test_reprint_cross_signature():
    old_ids = [f"p{i:02d}" for i in range(1, 25)]
    new_ids = [f"p{i:02d}" for i in list(range(17, 25)) + list(range(9, 17)) + list(range(1, 9))]
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": old_ids,
            "new_page_ids": new_ids,
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["reprint_sheet_count"] == 0
    first_sheet = data["signatures"][0]["sheets"][0]
    assert first_sheet["reused"] is True
    # 新帖 1 的 8 页块来自旧帖 3
    assert first_sheet["old_signature_index"] == 3
    assert first_sheet["old_sheet_index"] == 1


def test_reprint_right_binding():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a", "b", "c", "d"],
            "new_page_ids": ["a", "b", "c", "d"],
            "max_sheets_per_signature": 2,
            "binding": "right",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert sheet["front"] == {"left": "a", "right": "d"}
    assert sheet["reused"] is True


def test_reprint_blank_positions_null():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a"],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 1,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert sheet["front"] == {"left": None, "right": "a"}
    assert sheet["back"] == {"left": None, "right": None}
    assert sheet["reused"] is True


def test_reprint_empty_old_page_ids():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": [],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 422


def test_reprint_blank_page_id_string():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a", "  "],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 422


def test_reprint_duplicate_page_id_within_version():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a", "b"],
            "new_page_ids": ["a", "a"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 422


def test_reprint_changed_id_not_in_new_version():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a", "b"],
            "new_page_ids": ["a", "b"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": ["c"],
        },
    )
    assert response.status_code == 422


def test_reprint_changed_id_may_repeat():
    # changed_page_ids 不要求去重
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a", "b"],
            "new_page_ids": ["a", "b"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": ["a", "a"],
        },
    )
    assert response.status_code == 200
    assert response.json()["reprint_sheet_count"] == 1


def test_reprint_invalid_max_sheets():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a"],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 0,
            "binding": "left",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 422


def test_reprint_invalid_binding():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a"],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 2,
            "binding": "top",
            "changed_page_ids": [],
        },
    )
    assert response.status_code == 422


def test_reprint_unknown_field_rejected():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a"],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "changed_page_ids": [],
            "extra": 1,
        },
    )
    assert response.status_code == 422


def test_reprint_missing_field():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a"],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 2,
            "binding": "left",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 印张抽检 /api/v1/impose/inspect
# ---------------------------------------------------------------------------

INSPECT_BASE = {
    "page_ids": [f"p{i}" for i in range(1, 13)],
    "max_sheets_per_signature": 2,
    "binding": "left",
}


def test_inspect_perfect_and_unseen_and_unmatched():
    # 12 页、每帖 2 张：帖1 p1..p8 两张，帖2 p9..p12（补 4 空白）一张
    # obs1 原样=帖1最外张；obs2 正反互换=帖1内张；obs3 全 "?" -> 无法配对；
    # 未见：帖2 的唯一印张
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "observed_sheets": [
                {"front": {"left": "p8", "right": "p1"},
                 "back": {"left": "p2", "right": "p7"}},
                {"front": {"left": "p4", "right": "p5"},
                 "back": {"left": "p6", "right": "p3"}},
                {"front": {"left": "?", "right": "?"},
                 "back": {"left": "?", "right": "?"}},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["matched_observation_count"] == 2
    assert data["unmatched_observation_count"] == 1
    assert data["unseen_sheet_count"] == 1

    o1, o2, o3 = data["observations"]
    assert o1["matched"] is True
    assert (o1["signature_index"], o1["sheet_index"]) == (1, 1)
    assert o1["transform"] == "none"
    assert o1["matched_slot_count"] == 4
    assert o1["errors"] == []

    assert o2["matched"] is True
    assert (o2["signature_index"], o2["sheet_index"]) == (1, 2)
    assert o2["transform"] == "flip_fb"
    assert o2["matched_slot_count"] == 4

    assert o3["matched"] is False
    assert o3["signature_index"] is None
    assert o3["sheet_index"] is None
    assert o3["transform"] is None
    assert o3["matched_slot_count"] == 0

    assert [o["observation_index"] for o in data["unmatched_observations"]] == [3]
    unseen = data["unseen_signatures"]
    assert len(unseen) == 1
    assert (unseen[0]["signature_index"], unseen[0]["sheet_index"]) == (2, 1)


def test_inspect_mirror_and_both_transforms():
    # 8 页单帖两张：最外张 (p8,p1)/(p2,p7)，内张 (p6,p3)/(p4,p5)
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            "page_ids": [f"p{i}" for i in range(1, 9)],
            "max_sheets_per_signature": 2,
            "binding": "left",
            "observed_sheets": [
                {"front": {"left": "p1", "right": "p8"},
                 "back": {"left": "p7", "right": "p2"}},  # 最外张的 mirror_lr
                {"front": {"left": "p5", "right": "p4"},
                 "back": {"left": "p3", "right": "p6"}},  # 内张的 mirror_lr_flip_fb
            ],
        },
    )
    assert response.status_code == 200
    observations = response.json()["observations"]
    assert observations[0]["transform"] == "mirror_lr"
    assert observations[0]["matched_slot_count"] == 4
    assert (observations[0]["signature_index"], observations[0]["sheet_index"]) == (1, 1)
    assert observations[1]["transform"] == "mirror_lr_flip_fb"
    assert observations[1]["matched_slot_count"] == 4
    assert (observations[1]["signature_index"], observations[1]["sheet_index"]) == (1, 2)


def test_inspect_errors_listed_and_question_mark_ignored():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            "page_ids": ["a", "b", "c", "d"],
            "max_sheets_per_signature": 1,
            "binding": "left",
            "observed_sheets": [
                {"front": {"left": "d", "right": "?"},
                 "back": {"left": "X", "right": "c"}}
            ],
        },
    )
    assert response.status_code == 200
    obs = response.json()["observations"][0]
    assert obs["matched"] is True
    assert obs["matched_slot_count"] == 2  # d 与 c 吻合；"?" 不计
    assert obs["errors"] == [
        {"position": "back_left", "observed": "X", "expected": "b"}
    ]


def test_inspect_null_blank_mismatch_error():
    # 单页补 3 空白：预期 (null,a)/(null,null)
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            "page_ids": ["a"],
            "max_sheets_per_signature": 1,
            "binding": "left",
            "observed_sheets": [
                {"front": {"left": "a", "right": "a"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 200
    obs = response.json()["observations"][0]
    assert obs["matched_slot_count"] == 3
    assert obs["errors"] == [
        {"position": "front_left", "observed": "a", "expected": None}
    ]


def test_inspect_foreign_only_observation_unpaired():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            "page_ids": ["a", "b", "c", "d"],
            "max_sheets_per_signature": 1,
            "binding": "left",
            "observed_sheets": [
                {"front": {"left": "x", "right": "y"},
                 "back": {"left": None, "right": "?"}}
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["matched_observation_count"] == 0
    assert data["unmatched_observation_count"] == 1
    assert data["observations"][0]["matched"] is False
    assert data["unseen_sheet_count"] == 1


def test_inspect_right_binding():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            "page_ids": ["a", "b", "c", "d"],
            "max_sheets_per_signature": 1,
            "binding": "right",
            "observed_sheets": [
                {"front": {"left": "a", "right": "d"},
                 "back": {"left": "c", "right": "b"}}
            ],
        },
    )
    assert response.status_code == 200
    obs = response.json()["observations"][0]
    assert obs["transform"] == "none"
    assert obs["matched_slot_count"] == 4


def test_inspect_pair_count_takes_priority_over_matches():
    # 两张观测都只能配帖1最外张（p8 只出现在该张）：
    # 高吻合的 obs1 先取该张，obs2 落单；反之总配对数相同（1 对），
    # 但 obs1 配对吻合更多，字典序也优先 obs1。
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "observed_sheets": [
                {"front": {"left": "p8", "right": "p1"},
                 "back": {"left": "p2", "right": "p7"}},
                {"front": {"left": "p8", "right": None},
                 "back": {"left": None, "right": None}},
            ],
        },
    )
    data = response.json()
    assert data["matched_observation_count"] == 1
    assert data["observations"][0]["matched"] is True
    assert data["observations"][0]["matched_slot_count"] == 4
    assert data["observations"][1]["matched"] is False
    # 未见另外两张
    assert data["unseen_sheet_count"] == 2


def test_inspect_invalid_page_id_question_mark():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "page_ids": ["p1", "?", "p3"],
            "observed_sheets": [
                {"front": {"left": "p1", "right": "p2"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_duplicate_page_ids():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "page_ids": ["p1", "p1", "p2"],
            "observed_sheets": [
                {"front": {"left": "p1", "right": "p2"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_empty_page_ids():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "page_ids": [],
            "observed_sheets": [
                {"front": {"left": "p1", "right": "p2"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_empty_observed_sheets():
    response = client.post(
        "/api/v1/impose/inspect",
        json={**INSPECT_BASE, "observed_sheets": []},
    )
    assert response.status_code == 422


def test_inspect_blank_slot_string_rejected():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "observed_sheets": [
                {"front": {"left": "  ", "right": "p1"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_invalid_max_sheets():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "max_sheets_per_signature": 0,
            "observed_sheets": [
                {"front": {"left": "p1", "right": "p2"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_invalid_binding():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "binding": "top",
            "observed_sheets": [
                {"front": {"left": "p1", "right": "p2"},
                 "back": {"left": None, "right": None}}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_unknown_field_rejected():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            **INSPECT_BASE,
            "observed_sheets": [
                {"front": {"left": "p8", "right": "p1"},
                 "back": {"left": "p2", "right": "p7"},
                 "extra": 1}
            ],
        },
    )
    assert response.status_code == 422


def test_inspect_missing_field():
    response = client.post(
        "/api/v1/impose/inspect",
        json={
            "page_ids": INSPECT_BASE["page_ids"],
            "max_sheets_per_signature": 2,
            "binding": "left",
        },
    )
    assert response.status_code == 422


def test_reprint_missing_field_legacy():
    response = client.post(
        "/api/v1/impose/reprint",
        json={
            "old_page_ids": ["a"],
            "new_page_ids": ["a"],
            "max_sheets_per_signature": 2,
            "binding": "left",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 机台版面 /api/v1/impose/press-layout
# ---------------------------------------------------------------------------

PRESS_LAYOUT_BASE = {
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210.0,
    "page_height_mm": 297.0,
    "gutter_mm": 10.0,
    "duplex_flip": "long",
}


def test_press_layout_long_flip_paper_and_placements():
    response = client.post("/api/v1/impose/press-layout", json=PRESS_LAYOUT_BASE)
    assert response.status_code == 200
    data = response.json()
    assert data["paper_width_mm"] == 430.0
    assert data["paper_height_mm"] == 297.0
    assert data["duplex_flip"] == "long"
    assert data["signature_count"] == 1
    sig = data["signatures"][0]
    assert sig["paper_width_mm"] == 430.0
    assert sig["paper_height_mm"] == 297.0
    sheet = sig["sheets"][0]
    # 左装订：正面 (4, 1)；左槽 x=0，右槽 x=页宽+中缝
    assert sheet["front"]["left"] == {
        "page": 4, "x_mm": 0.0, "y_mm": 0.0, "rotation_deg": 0
    }
    assert sheet["front"]["right"] == {
        "page": 1, "x_mm": 220.0, "y_mm": 0.0, "rotation_deg": 0
    }
    # long：背面原 (2, 3) 交换槽位、旋转 0
    assert sheet["back"]["left"] == {
        "page": 3, "x_mm": 0.0, "y_mm": 0.0, "rotation_deg": 0
    }
    assert sheet["back"]["right"] == {
        "page": 2, "x_mm": 220.0, "y_mm": 0.0, "rotation_deg": 0
    }


def test_press_layout_short_flip_rotates_back_180():
    body = {**PRESS_LAYOUT_BASE, "duplex_flip": "short", "gutter_mm": 0}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert sheet["front"]["left"]["rotation_deg"] == 0
    assert sheet["front"]["right"] == {
        "page": 1, "x_mm": 210.0, "y_mm": 0.0, "rotation_deg": 0
    }
    # short：槽位保持（背左=2、背右=3），各旋转 180°
    assert sheet["back"]["left"] == {
        "page": 2, "x_mm": 0.0, "y_mm": 0.0, "rotation_deg": 180
    }
    assert sheet["back"]["right"] == {
        "page": 3, "x_mm": 210.0, "y_mm": 0.0, "rotation_deg": 180
    }


def test_press_layout_right_binding():
    body = {**PRESS_LAYOUT_BASE, "binding": "right"}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert sheet["front"]["left"]["page"] == 1
    assert sheet["front"]["right"]["page"] == 4


def test_press_layout_blank_slots_null():
    body = {**PRESS_LAYOUT_BASE, "total_pages": 1}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert sheet["front"]["left"] is None
    assert sheet["front"]["right"]["page"] == 1
    assert sheet["back"]["left"] is None
    assert sheet["back"]["right"] is None


def test_press_layout_zero_gutter_allowed():
    body = {**PRESS_LAYOUT_BASE, "gutter_mm": 0}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["paper_width_mm"] == 420.0
    assert data["signatures"][0]["sheets"][0]["front"]["right"]["x_mm"] == 210.0


def test_press_layout_multi_signature():
    body = {**PRESS_LAYOUT_BASE, "total_pages": 6, "max_sheets_per_signature": 1}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 200
    sigs = response.json()["signatures"]
    assert len(sigs) == 2
    assert [(s["signature_index"], s["sheet_count"]) for s in sigs] == [(1, 1), (2, 1)]
    assert sigs[1]["page_count_padded"] == 4


def test_press_layout_invalid_page_width_zero():
    body = {**PRESS_LAYOUT_BASE, "page_width_mm": 0}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_invalid_page_height_negative():
    body = {**PRESS_LAYOUT_BASE, "page_height_mm": -1}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_invalid_gutter_negative():
    body = {**PRESS_LAYOUT_BASE, "gutter_mm": -0.5}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_non_finite_dimensions_return_422():
    # NaN / Infinity 必须返回 422 而不是 500（默认错误回显无法 JSON 序列化）
    for payload in (
        '{"total_pages": 4, "max_sheets_per_signature": 1, "binding": "left", '
        '"page_width_mm": NaN, "page_height_mm": 297, "gutter_mm": 0, '
        '"duplex_flip": "long"}',
        '{"total_pages": 4, "max_sheets_per_signature": 1, "binding": "left", '
        '"page_width_mm": 210, "page_height_mm": Infinity, "gutter_mm": 0, '
        '"duplex_flip": "long"}',
        '{"total_pages": 4, "max_sheets_per_signature": 1, "binding": "left", '
        '"page_width_mm": 210, "page_height_mm": 297, "gutter_mm": -Infinity, '
        '"duplex_flip": "long"}',
    ):
        response = client.post(
            "/api/v1/impose/press-layout",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


def test_press_layout_invalid_duplex_flip():
    body = {**PRESS_LAYOUT_BASE, "duplex_flip": "side"}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_invalid_binding():
    body = {**PRESS_LAYOUT_BASE, "binding": "top"}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_invalid_total_pages():
    body = {**PRESS_LAYOUT_BASE, "total_pages": 0}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_unknown_field_rejected():
    body = {**PRESS_LAYOUT_BASE, "extra": 1}
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


def test_press_layout_missing_field():
    body = dict(PRESS_LAYOUT_BASE)
    del body["gutter_mm"]
    response = client.post("/api/v1/impose/press-layout", json=body)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 双面拼版校样 PDF /api/v1/impose/proof.pdf
# ---------------------------------------------------------------------------

PROOF_BASE = {
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210.0,
    "page_height_mm": 297.0,
    "gutter_mm": 10.0,
    "duplex_flip": "long",
}


def _proof_reader(body) -> tuple:
    response = client.post("/api/v1/impose/proof.pdf", json=body)
    assert response.status_code == 200
    return response, PdfReader(BytesIO(response.content))


def test_proof_returns_downloadable_pdf():
    response, reader = _proof_reader(PROOF_BASE)
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="proof.pdf"'
    assert response.content.startswith(b"%PDF-")
    # 1 张印张 -> 正面、背面两页
    assert len(reader.pages) == 2


def test_proof_mediabox_matches_press_layout_paper():
    _, reader = _proof_reader(PROOF_BASE)
    for page in reader.pages:
        assert float(page.mediabox.width) == pytest.approx(430.0 * mm, rel=1e-6)
        assert float(page.mediabox.height) == pytest.approx(297.0 * mm, rel=1e-6)


def test_proof_pages_are_front_then_back_with_labels():
    _, reader = _proof_reader({**PROOF_BASE, "total_pages": 6,
                               "max_sheets_per_signature": 1})
    assert len(reader.pages) == 4  # 2 张 × 正反面
    assert "正面" in reader.pages[0].extract_text()
    assert "背面" in reader.pages[1].extract_text()
    # 末帖补白：第 2 帖正面左槽为“空白”
    assert "空白" in reader.pages[2].extract_text()
    assert "第2帖" in reader.pages[2].extract_text()


def test_proof_short_flip_back_rotated_180():
    body = {**PROOF_BASE, "duplex_flip": "short", "gutter_mm": 0}
    _, reader = _proof_reader(body)
    front = reader.pages[0].get_contents().get_data().decode("latin-1")
    back = reader.pages[1].get_contents().get_data().decode("latin-1")
    assert "-1 0 0 -1" not in front
    assert "-1 0 0 -1" in back


def test_proof_right_binding_page_order():
    _, reader = _proof_reader({**PROOF_BASE, "binding": "right"})
    front = [line for line in reader.pages[0].extract_text().splitlines()
             if line.isdigit()]
    assert front == ["1", "4"]


def test_proof_100_sheet_limit_boundary():
    # 每张 4 页：400 页 = 100 张，允许；401 页 = 101 张，422
    response = client.post("/api/v1/impose/proof.pdf", json={
        **PROOF_BASE, "total_pages": 400, "max_sheets_per_signature": 200,
        "page_width_mm": 50.0, "page_height_mm": 80.0,
    })
    assert response.status_code == 200
    assert len(PdfReader(BytesIO(response.content)).pages) == 200

    response = client.post("/api/v1/impose/proof.pdf", json={
        **PROOF_BASE, "total_pages": 401, "max_sheets_per_signature": 200,
        "page_width_mm": 50.0, "page_height_mm": 80.0,
    })
    assert response.status_code == 422
    assert "100" in response.json()["detail"][0]["msg"]


def test_proof_invalid_dimensions_return_422():
    for field, value in (
        ("page_width_mm", 0),
        ("page_height_mm", -2),
        ("gutter_mm", -1),
    ):
        response = client.post("/api/v1/impose/proof.pdf",
                               json={**PROOF_BASE, field: value})
        assert response.status_code == 422


def test_proof_invalid_flip_and_binding_return_422():
    response = client.post("/api/v1/impose/proof.pdf",
                           json={**PROOF_BASE, "duplex_flip": "side"})
    assert response.status_code == 422
    response = client.post("/api/v1/impose/proof.pdf",
                           json={**PROOF_BASE, "binding": "top"})
    assert response.status_code == 422


def test_proof_non_finite_dimensions_return_422():
    payload = (
        '{"total_pages": 4, "max_sheets_per_signature": 1, "binding": "left", '
        '"page_width_mm": NaN, "page_height_mm": 297, "gutter_mm": 0, '
        '"duplex_flip": "long"}'
    )
    response = client.post(
        "/api/v1/impose/proof.pdf",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_proof_unknown_field_rejected():
    response = client.post("/api/v1/impose/proof.pdf",
                           json={**PROOF_BASE, "extra": 1})
    assert response.status_code == 422


def test_proof_missing_field():
    body = dict(PROOF_BASE)
    del body["duplex_flip"]
    response = client.post("/api/v1/impose/proof.pdf", json=body)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 瑕疵定位 /api/v1/impose/locate-defects
# ---------------------------------------------------------------------------

LOCATE_DEFECTS_BASE = {
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 210.0,
    "page_height_mm": 297.0,
    "gutter_mm": 10.0,
    "duplex_flip": "long",
}


def test_locate_defects_front_and_long_back():
    body = {
        **LOCATE_DEFECTS_BASE,
        "defects": [
            {"signature_index": 1, "sheet_index": 1, "side": "front",
             "x_mm": 100.0, "y_mm": 50.0},
            {"signature_index": 1, "sheet_index": 1, "side": "back",
             "x_mm": 250.0, "y_mm": 40.0},
        ],
    }
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["paper_width_mm"] == 430.0
    assert data["defect_count"] == 2
    front, back = data["defects"]
    # 左装订正面左槽 = 第 4 页，页内坐标即槽内坐标
    assert front == {
        "defect_index": 1,
        "location": "page",
        "page": 4,
        "page_x_mm": 100.0,
        "page_y_mm": 50.0,
    }
    # long 背面交换槽位：右槽 = 第 2 页（x=220 -> 页内 x=30）
    assert back == {
        "defect_index": 2,
        "location": "page",
        "page": 2,
        "page_x_mm": 30.0,
        "page_y_mm": 40.0,
    }


def test_locate_defects_short_flip_back_reverses_180():
    body = {
        **LOCATE_DEFECTS_BASE,
        "gutter_mm": 0,
        "duplex_flip": "short",
        "defects": [
            {"signature_index": 1, "sheet_index": 1, "side": "back",
             "x_mm": 100.0, "y_mm": 50.0},
        ],
    }
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 200
    item = response.json()["defects"][0]
    # short 背面保持槽位（背左 = 2），页内坐标逆转 180°
    assert item["location"] == "page"
    assert item["page"] == 2
    assert item["page_x_mm"] == pytest.approx(110.0)
    assert item["page_y_mm"] == pytest.approx(247.0)


def test_locate_defects_gutter_and_blank_marked_without_page():
    body = {
        **LOCATE_DEFECTS_BASE,
        "total_pages": 1,
        "defects": [
            {"signature_index": 1, "sheet_index": 1, "side": "front",
             "x_mm": 215.0, "y_mm": 100.0},   # 中缝 [210, 220)
            {"signature_index": 1, "sheet_index": 1, "side": "front",
             "x_mm": 100.0, "y_mm": 100.0},   # 1 页补 3 空白：正面左槽空白
            {"signature_index": 1, "sheet_index": 1, "side": "front",
             "x_mm": 300.0, "y_mm": 100.0},   # 正面右槽 = 第 1 页
        ],
    }
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 200
    gutter, blank, page = response.json()["defects"]
    assert gutter == {
        "defect_index": 1, "location": "gutter",
        "page": None, "page_x_mm": None, "page_y_mm": None,
    }
    assert blank == {
        "defect_index": 2, "location": "blank",
        "page": None, "page_x_mm": None, "page_y_mm": None,
    }
    assert page["location"] == "page"
    assert page["page"] == 1
    assert page["page_x_mm"] == 80.0


def test_locate_defects_out_of_paper_returns_422():
    for x_mm, y_mm in ((-1.0, 10.0), (430.1, 10.0), (10.0, -1.0), (10.0, 297.1)):
        body = {
            **LOCATE_DEFECTS_BASE,
            "defects": [
                {"signature_index": 1, "sheet_index": 1, "side": "front",
                 "x_mm": x_mm, "y_mm": y_mm},
            ],
        }
        response = client.post("/api/v1/impose/locate-defects", json=body)
        assert response.status_code == 422


def test_locate_defects_invalid_signature_or_sheet_returns_422():
    for signature_index, sheet_index in ((2, 1), (1, 2), (0, 1), (1, 0), (-1, 1)):
        body = {
            **LOCATE_DEFECTS_BASE,
            "defects": [
                {"signature_index": signature_index, "sheet_index": sheet_index,
                 "side": "front", "x_mm": 10.0, "y_mm": 10.0},
            ],
        }
        response = client.post("/api/v1/impose/locate-defects", json=body)
        assert response.status_code == 422


def test_locate_defects_multi_signature():
    body = {
        **LOCATE_DEFECTS_BASE,
        "total_pages": 6,
        "defects": [
            {"signature_index": 2, "sheet_index": 1, "side": "front",
             "x_mm": 320.0, "y_mm": 10.0},
        ],
    }
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 200
    item = response.json()["defects"][0]
    # 帖 2 正面右槽 = 第 5 页（x=220 -> 页内 x=100）
    assert item["location"] == "page"
    assert item["page"] == 5
    assert item["page_x_mm"] == 100.0


def test_locate_defects_non_finite_coordinates_return_422():
    payload = (
        '{"total_pages": 4, "max_sheets_per_signature": 1, "binding": "left", '
        '"page_width_mm": 210, "page_height_mm": 297, "gutter_mm": 10, '
        '"duplex_flip": "long", "defects": [{"signature_index": 1, '
        '"sheet_index": 1, "side": "front", "x_mm": NaN, "y_mm": 10}]}'
    )
    response = client.post(
        "/api/v1/impose/locate-defects",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_locate_defects_invalid_side_returns_422():
    body = {
        **LOCATE_DEFECTS_BASE,
        "defects": [
            {"signature_index": 1, "sheet_index": 1, "side": "top",
             "x_mm": 10.0, "y_mm": 10.0},
        ],
    }
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 422


def test_locate_defects_empty_defects_returns_422():
    response = client.post(
        "/api/v1/impose/locate-defects",
        json={**LOCATE_DEFECTS_BASE, "defects": []},
    )
    assert response.status_code == 422


def test_locate_defects_layout_validation_reused():
    # 机台版面参数校验沿用：尺寸非正数、翻转模式非法、未定义字段
    defect = {"signature_index": 1, "sheet_index": 1, "side": "front",
              "x_mm": 10.0, "y_mm": 10.0}
    for override in (
        {"page_width_mm": 0},
        {"page_height_mm": -1},
        {"gutter_mm": -0.5},
        {"duplex_flip": "side"},
        {"binding": "top"},
        {"total_pages": 0},
    ):
        response = client.post(
            "/api/v1/impose/locate-defects",
            json={**LOCATE_DEFECTS_BASE, **override, "defects": [defect]},
        )
        assert response.status_code == 422
    response = client.post(
        "/api/v1/impose/locate-defects",
        json={**LOCATE_DEFECTS_BASE, "defects": [defect], "extra": 1},
    )
    assert response.status_code == 422


def test_locate_defects_missing_field_returns_422():
    body = {**LOCATE_DEFECTS_BASE}
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 422
    body = {
        **LOCATE_DEFECTS_BASE,
        "defects": [{"signature_index": 1, "sheet_index": 1, "side": "front"}],
    }
    response = client.post("/api/v1/impose/locate-defects", json=body)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 墨区着墨面积 /api/v1/impose/ink-zones
# ---------------------------------------------------------------------------

INK_ZONES_BASE = {
    "total_pages": 4,
    "max_sheets_per_signature": 1,
    "binding": "left",
    "page_width_mm": 100.0,
    "page_height_mm": 100.0,
    "gutter_mm": 0.0,
    "duplex_flip": "long",
    "zone_count": 4,
    "copies": 1,
    "page_inks": [],
}


def test_ink_zones_front_and_back_placements():
    body = {
        **INK_ZONES_BASE,
        "copies": 1000,
        "page_inks": [
            # 第 1 页：正面右槽 x=100；页内 (50,10,25,40) C=.5
            # -> 纸面 150..175 落区 4，1000×.5×1000 = 500000
            {"page": 1, "rectangles": [
                {"x_mm": 50, "y_mm": 10, "width_mm": 25, "height_mm": 40,
                 "cyan": 0.5, "magenta": 0, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["paper_width_mm"] == 200.0
    assert data["zone_count"] == 4
    assert data["zone_width_mm"] == 50.0
    assert data["copies"] == 1000
    sheet = data["signatures"][0]["sheets"][0]
    assert sheet["front"] == [
        {"zone_index": 4, "cyan_mm2": 500000.0, "magenta_mm2": 0.0,
         "yellow_mm2": 0.0, "black_mm2": 0.0},
    ]
    # 无着墨的背面整面缺省
    assert "back" not in sheet


def test_ink_zones_split_across_boundaries():
    # 纸面 220（中缝 20）、4 墨区每区 55；第 4 页正面左槽 x=0
    body = {
        **INK_ZONES_BASE,
        "gutter_mm": 20.0,
        "copies": 4,
        "page_inks": [
            {"page": 4, "rectangles": [
                {"x_mm": 40, "y_mm": 0, "width_mm": 40, "height_mm": 100,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0.25},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 200
    front = response.json()["signatures"][0]["sheets"][0]["front"]
    assert front == [
        {"zone_index": 1, "cyan_mm2": 0.0, "magenta_mm2": 0.0,
         "yellow_mm2": 0.0, "black_mm2": 1500.0},
        {"zone_index": 2, "cyan_mm2": 0.0, "magenta_mm2": 0.0,
         "yellow_mm2": 0.0, "black_mm2": 2500.0},
    ]


def test_ink_zones_short_flip_back_rotated_180():
    body = {
        **INK_ZONES_BASE,
        "duplex_flip": "short",
        "zone_count": 2,
        "copies": 2,
        "page_inks": [
            # short 背面背左 = 第 2 页（x=0）旋转 180：
            # 页内 (40,10,20,20) -> 纸面 40..60 落区 1，400×1×2 = 800
            {"page": 2, "rectangles": [
                {"x_mm": 40, "y_mm": 10, "width_mm": 20, "height_mm": 20,
                 "cyan": 0, "magenta": 1, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 200
    back = response.json()["signatures"][0]["sheets"][0]["back"]
    assert back == [
        {"zone_index": 1, "cyan_mm2": 0.0, "magenta_mm2": 800.0,
         "yellow_mm2": 0.0, "black_mm2": 0.0},
    ]


def test_ink_zones_blank_pages_not_counted():
    # 1 页补 3 空白：正面 (null,1)、背面 (null,null)
    body = {
        **INK_ZONES_BASE,
        "total_pages": 1,
        "page_inks": [
            {"page": 1, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 50, "height_mm": 50,
                 "cyan": 0.5, "magenta": 0, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 200
    sheet = response.json()["signatures"][0]["sheets"][0]
    assert "back" not in sheet
    assert sheet["front"][0]["zone_index"] == 3
    assert sheet["front"][0]["cyan_mm2"] == 1250.0


def test_ink_zones_empty_page_inks_ok():
    response = client.post("/api/v1/impose/ink-zones", json=INK_ZONES_BASE)
    assert response.status_code == 200
    data = response.json()
    assert data["signatures"][0]["sheets"][0] == {"sheet_index": 1}


def test_ink_zones_touching_rectangles_allowed():
    body = {
        **INK_ZONES_BASE,
        "page_inks": [
            {"page": 4, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 50, "height_mm": 50,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0.5},
                {"x_mm": 50, "y_mm": 0, "width_mm": 50, "height_mm": 50,
                 "cyan": 0, "magenta": 0.3, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 200


def test_ink_zones_invalid_zone_count():
    for zone_count in (0, 17):
        response = client.post(
            "/api/v1/impose/ink-zones",
            json={**INK_ZONES_BASE, "zone_count": zone_count},
        )
        assert response.status_code == 422


def test_ink_zones_integer_fields_reject_bool_and_float():
    for override in (
        {"zone_count": True},
        {"zone_count": 1.5},
        {"copies": True},
        {"copies": 2.0},
    ):
        response = client.post(
            "/api/v1/impose/ink-zones",
            json={**INK_ZONES_BASE, **override},
        )
        assert response.status_code == 422
    response = client.post(
        "/api/v1/impose/ink-zones",
        json={**INK_ZONES_BASE, "page_inks": [
            {"page": True, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 1, "height_mm": 1,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0}]}]},
    )
    assert response.status_code == 422


def test_ink_zones_invalid_copies():
    for copies in (0, -1):
        response = client.post(
            "/api/v1/impose/ink-zones",
            json={**INK_ZONES_BASE, "copies": copies},
        )
        assert response.status_code == 422


def test_ink_zones_invalid_page_number():
    body = {
        **INK_ZONES_BASE,
        "page_inks": [
            {"page": 5, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 10, "height_mm": 10,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422


def test_ink_zones_duplicate_page_returns_422():
    rect = {"x_mm": 0, "y_mm": 0, "width_mm": 10, "height_mm": 10,
            "cyan": 0, "magenta": 0, "yellow": 0, "black": 0}
    body = {
        **INK_ZONES_BASE,
        "page_inks": [{"page": 1, "rectangles": [rect]},
                      {"page": 1, "rectangles": [rect]}],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422


def test_ink_zones_rect_out_of_page_returns_422():
    for rect in (
        {"x_mm": -1, "y_mm": 0, "width_mm": 10, "height_mm": 10},
        {"x_mm": 0, "y_mm": 0, "width_mm": 101, "height_mm": 10},
        {"x_mm": 95, "y_mm": 0, "width_mm": 10, "height_mm": 10},
        {"x_mm": 0, "y_mm": 0, "width_mm": 0, "height_mm": 10},
    ):
        rect = {**rect, "cyan": 0, "magenta": 0, "yellow": 0, "black": 0}
        body = {
            **INK_ZONES_BASE,
            "page_inks": [{"page": 1, "rectangles": [rect]}],
        }
        response = client.post("/api/v1/impose/ink-zones", json=body)
        assert response.status_code == 422


def test_ink_zones_overlapping_rectangles_return_422():
    body = {
        **INK_ZONES_BASE,
        "page_inks": [
            {"page": 1, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 50, "height_mm": 50,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0},
                {"x_mm": 40, "y_mm": 40, "width_mm": 20, "height_mm": 20,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422


def test_ink_zones_coverage_out_of_range_returns_422():
    body = {
        **INK_ZONES_BASE,
        "page_inks": [
            {"page": 1, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 10, "height_mm": 10,
                 "cyan": 1.01, "magenta": 0, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422
    body["page_inks"][0]["rectangles"][0]["cyan"] = -0.1
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422


def test_ink_zones_non_finite_rect_returns_422():
    payload = (
        '{"total_pages": 4, "max_sheets_per_signature": 1, "binding": "left", '
        '"page_width_mm": 100, "page_height_mm": 100, "gutter_mm": 0, '
        '"duplex_flip": "long", "zone_count": 4, "copies": 1, "page_inks": '
        '[{"page": 1, "rectangles": [{"x_mm": NaN, "y_mm": 0, '
        '"width_mm": 10, "height_mm": 10, "cyan": 0, "magenta": 0, '
        '"yellow": 0, "black": 0}]}]}'
    )
    response = client.post(
        "/api/v1/impose/ink-zones",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_ink_zones_layout_validation_reused():
    rect = {"x_mm": 0, "y_mm": 0, "width_mm": 10, "height_mm": 10,
            "cyan": 0, "magenta": 0, "yellow": 0, "black": 0}
    for override in (
        {"page_width_mm": 0},
        {"page_height_mm": -1},
        {"gutter_mm": -0.5},
        {"duplex_flip": "side"},
        {"binding": "top"},
        {"total_pages": 0},
    ):
        response = client.post(
            "/api/v1/impose/ink-zones",
            json={**INK_ZONES_BASE, **override,
                  "page_inks": [{"page": 1, "rectangles": [rect]}]},
        )
        assert response.status_code == 422
    response = client.post(
        "/api/v1/impose/ink-zones",
        json={**INK_ZONES_BASE, "extra": 1},
    )
    assert response.status_code == 422


def test_ink_zones_missing_field_returns_422():
    body = dict(INK_ZONES_BASE)
    del body["zone_count"]
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422
    body = {
        **INK_ZONES_BASE,
        "page_inks": [
            {"page": 1, "rectangles": [
                {"x_mm": 0, "y_mm": 0, "width_mm": 10,
                 "cyan": 0, "magenta": 0, "yellow": 0, "black": 0},
            ]},
        ],
    }
    response = client.post("/api/v1/impose/ink-zones", json=body)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 订针计划 /api/v1/impose/staple-plan
# ---------------------------------------------------------------------------

STAPLE_PLAN_BASE = {
    "total_pages": 8,
    "max_sheets_per_signature": 4,
    "binding": "left",
    "page_height_mm": 100.0,
    "staple_count": 3,
    "top_margin_mm": 14.0,
    "bottom_margin_mm": 14.0,
    "min_spacing_mm": 10.0,
}


def test_staple_plan_exact_ideals():
    response = client.post("/api/v1/impose/staple-plan", json=STAPLE_PLAN_BASE)
    assert response.status_code == 200
    data = response.json()
    # 8 页、每帖最多 4 张 -> 1 帖 2 张
    assert data["signature_count"] == 1
    sig = data["signatures"][0]
    assert sig["signature_index"] == 1
    assert sig["sheet_count"] == 2
    assert sig["page_count_padded"] == 8
    # 可用高 72，订 3 针：32/50/68 恰为整数毫米理想针位
    assert sig["staple_positions_mm"] == [32, 50, 68]
    assert sig["max_deviation_mm"] == 0.0


def test_staple_plan_forbidden_zones_only_affect_named_signature():
    body = {
        **STAPLE_PLAN_BASE,
        "total_pages": 6,
        "max_sheets_per_signature": 1,
        "staple_count": 2,
        "top_margin_mm": 10.0,
        "bottom_margin_mm": 10.0,
        "forbidden_zones": [
            {"signature_index": 2, "intervals": [{"start_mm": 30, "end_mm": 30}]},
        ],
    }
    response = client.post("/api/v1/impose/staple-plan", json=body)
    assert response.status_code == 200
    sigs = response.json()["signatures"]
    assert len(sigs) == 2
    # 第 1 帖无禁区：理想针位 36.67/63.33 -> 37/63
    assert sigs[0]["staple_positions_mm"] == [37, 63]
    # 第 2 帖刻度 30 为闭区间端点，同样禁针
    assert 30 not in sigs[1]["staple_positions_mm"]
    assert all(len(s["staple_positions_mm"]) == 2 for s in sigs)


def test_staple_plan_min_spacing_tiebreak_example():
    # 禁区 [20,30] + 最小针距 50：[19,69] 与 [31,81] 最大偏差、偏差总和相同，
    # 取针位序列字典序最小者
    body = {
        **STAPLE_PLAN_BASE,
        "staple_count": 2,
        "top_margin_mm": 10.0,
        "bottom_margin_mm": 10.0,
        "min_spacing_mm": 50.0,
        "forbidden_zones": [
            {"signature_index": 1, "intervals": [{"start_mm": 20, "end_mm": 30}]},
        ],
    }
    response = client.post("/api/v1/impose/staple-plan", json=body)
    assert response.status_code == 200
    sig = response.json()["signatures"][0]
    assert sig["staple_positions_mm"] == [19, 69]
    assert sig["max_deviation_mm"] == pytest.approx(53 / 3, abs=1e-9)


def test_staple_plan_infeasible_signature_returns_422_with_index():
    body = {
        **STAPLE_PLAN_BASE,
        "total_pages": 6,
        "max_sheets_per_signature": 1,
        "staple_count": 2,
        "top_margin_mm": 10.0,
        "bottom_margin_mm": 10.0,
        "min_spacing_mm": 50.0,
        "forbidden_zones": [
            {"signature_index": 2, "intervals": [{"start_mm": 20, "end_mm": 89}]},
        ],
    }
    response = client.post("/api/v1/impose/staple-plan", json=body)
    assert response.status_code == 422
    assert "第 2 帖" in response.json()["detail"][0]["msg"]


def test_staple_plan_infeasible_by_spacing_returns_422():
    # 可用高 80 mm 却要求最小针距 80
    body = {
        **STAPLE_PLAN_BASE,
        "staple_count": 2,
        "top_margin_mm": 10.0,
        "bottom_margin_mm": 10.0,
        "min_spacing_mm": 80.0,
    }
    response = client.post("/api/v1/impose/staple-plan", json=body)
    assert response.status_code == 422
    assert "第 1 帖" in response.json()["detail"][0]["msg"]


def test_staple_plan_page_height_boundaries():
    for height in (50, 1000):
        body = {**STAPLE_PLAN_BASE, "page_height_mm": height,
                "top_margin_mm": 5.0, "bottom_margin_mm": 5.0,
                "min_spacing_mm": 5.0}
        response = client.post("/api/v1/impose/staple-plan", json=body)
        assert response.status_code == 200
    for height in (49, 1001):
        body = {**STAPLE_PLAN_BASE, "page_height_mm": height}
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422


def test_staple_plan_count_boundaries_and_integer_only():
    for count in (2, 3, 4):
        body = {**STAPLE_PLAN_BASE, "staple_count": count}
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 200
    for count in (1, 5, 2.0, 3.5, True):
        body = {**STAPLE_PLAN_BASE, "staple_count": count}
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422


def test_staple_plan_margin_and_spacing_validation():
    for override in (
        {"top_margin_mm": -0.1},
        {"bottom_margin_mm": -1},
        {"min_spacing_mm": -1},
        {"top_margin_mm": 87, "bottom_margin_mm": 13},  # 留边之和 >= 页高
    ):
        body = {**STAPLE_PLAN_BASE, **override}
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422


def test_staple_plan_forbidden_zone_validation():
    for intervals in (
        [{"start_mm": -1, "end_mm": 5}],
        [{"start_mm": 80, "end_mm": 50}],
        [{"start_mm": 1, "end_mm": 101}],
    ):
        body = {
            **STAPLE_PLAN_BASE,
            "forbidden_zones": [{"signature_index": 1, "intervals": intervals}],
        }
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422
    # intervals 不能为空
    body = {
        **STAPLE_PLAN_BASE,
        "forbidden_zones": [{"signature_index": 1, "intervals": []}],
    }
    assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422
    # 帖号超出实际帖数、同帖重复给出
    for zones in (
        [{"signature_index": 2, "intervals": [{"start_mm": 1, "end_mm": 2}]}],
        [
            {"signature_index": 1, "intervals": [{"start_mm": 1, "end_mm": 2}]},
            {"signature_index": 1, "intervals": [{"start_mm": 3, "end_mm": 4}]},
        ],
    ):
        body = {**STAPLE_PLAN_BASE, "forbidden_zones": zones}
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422


def test_staple_plan_non_finite_dimensions_return_422():
    payload = (
        '{"total_pages": 8, "max_sheets_per_signature": 4, "binding": "left", '
        '"page_height_mm": 100, "staple_count": 2, "top_margin_mm": 10, '
        '"bottom_margin_mm": 10, "min_spacing_mm": 10, '
        '"forbidden_zones": [{"signature_index": 1, '
        '"intervals": [{"start_mm": NaN, "end_mm": 20}]}]}'
    )
    response = client.post(
        "/api/v1/impose/staple-plan",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_staple_plan_forbidden_zones_optional_and_extra_field_rejected():
    response = client.post("/api/v1/impose/staple-plan", json=STAPLE_PLAN_BASE)
    assert response.status_code == 200
    response = client.post(
        "/api/v1/impose/staple-plan", json={**STAPLE_PLAN_BASE, "extra": 1}
    )
    assert response.status_code == 422


def test_staple_plan_impose_inputs_reused_for_validation():
    for override in (
        {"total_pages": 0},
        {"max_sheets_per_signature": 0},
        {"binding": "top"},
    ):
        body = {**STAPLE_PLAN_BASE, **override}
        assert client.post("/api/v1/impose/staple-plan", json=body).status_code == 422
