"""原纸备料（paper-stock）算法单元测试。"""

import pytest

from app.imposition import plan_paper_stock, _grid_count


# ---------------------------------------------------------------------------
# 单轴整排计数
# ---------------------------------------------------------------------------


def test_grid_count_basic():
    # 可用 100、成品 30、间隔 5：30+5+30+5+30 = 100 -> 3 个
    assert _grid_count(100, 30, 5) == 3
    # 可用 99 放不下第 3 个（需要 100）-> 2 个
    assert _grid_count(99, 30, 5) == 2


def test_grid_count_zero_gap():
    assert _grid_count(100, 30, 0) == 3
    assert _grid_count(90, 30, 0) == 3


def test_grid_count_no_fit():
    assert _grid_count(29.999, 30, 0) == 0
    assert _grid_count(0, 30, 2) == 0


def test_grid_count_exact_fit_with_gap():
    # 恰好放下 2 个：30 + 5 + 30 = 65
    assert _grid_count(65, 30, 5) == 2


# ---------------------------------------------------------------------------
# 每册印张数 / 总需求 / 成品尺寸
# ---------------------------------------------------------------------------


def _plan_one(paper, **overrides):
    params = dict(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=210.0,
        page_height_mm=297.0,
        gutter_mm=0.0,
        copies=100,
        margin_mm=10.0,
        cut_gap_mm=3.0,
        papers=[paper],
    )
    params.update(overrides)
    return plan_paper_stock(**params)


def test_sheets_per_book_and_demand():
    # 末帖补白：5 页需要 2 张印张
    r = _plan_one((880, 620, 30, "width"), total_pages=5, copies=7)
    assert r["sheets_per_book"] == 2
    assert r["demand"] == 14
    assert r["finished_sheet_width_mm"] == 420.0
    assert r["finished_sheet_height_mm"] == 297.0


def test_sheets_per_book_ceil_division():
    assert _plan_one((880, 620, 30, "width"), total_pages=1, copies=10)["sheets_per_book"] == 1
    assert _plan_one((880, 620, 30, "width"), copies=10)["sheets_per_book"] == 1
    assert _plan_one((880, 620, 30, "width"), total_pages=9, copies=10)["sheets_per_book"] == 3


def test_finished_size_includes_gutter():
    r = _plan_one((900, 640, 30, "height"), gutter_mm=10.0)
    assert r["finished_sheet_width_mm"] == 430.0
    assert r["finished_sheet_height_mm"] == 297.0


# ---------------------------------------------------------------------------
# 朝向：书脊只能与纸纹平行
# ---------------------------------------------------------------------------


def test_grain_along_height_orientation():
    # 成品 420（宽，书口方向）× 297（高，书脊方向）；纸纹沿高 -> 书脊平行原纸高
    # 可用 880-20=860 排印张宽 420（列），620-20=600 排印张高 297（行）
    r = _plan_one((880, 620, 30, "height"))
    grade = r["papers"][0]
    # 列：floor((860+3)/(420+3)) = 2；行：floor((600+3)/(297+3)) = 2
    assert grade["columns"] == 2
    assert grade["rows"] == 2
    assert grade["pieces_per_sheet"] == 4


def test_grain_along_width_orientation():
    # 纸纹沿宽 -> 书脊（印张高 297）平行原纸宽：
    # 列排印张高 297，行排印张宽 420
    r = _plan_one((880, 620, 30, "width"), copies=10)
    grade = r["papers"][0]
    # 列：floor(863/300) = 2；行：可用高 600 < 420+3+420 -> 1（600 >= 420）
    assert grade["columns"] == 2
    assert grade["rows"] == 1
    assert grade["pieces_per_sheet"] == 2
    # 需求 10：5 张 × 2 = 10，无超产
    assert grade["used_sheets"] == 5


def test_wrong_orientation_is_not_used():
    # 纸纹沿宽时本规格只能旋转摆放：900x640 可用 880x620，
    # 列排印张高 297（2 列）、行排印张宽 420（1 行）-> 2；
    # 若错误地允许另一朝向（书脊垂直纸纹）则会得到 4，必须按 2 计
    r = _plan_one((900, 640, 30, "width"), copies=10)
    assert r["papers"][0]["pieces_per_sheet"] == 2


def test_pieces_zero_when_finished_does_not_fit():
    # 留边 110：800x550、纸纹沿宽时可用 580x330，列排印张高 297（1 列）、
    # 行排印张宽 420（330 < 420，0 行）-> 出数 0；900x640 纸纹沿高可用
    # 680x420 恰好放下 1 张
    r = plan_paper_stock(
        total_pages=4, max_sheets=1, binding="left",
        page_width_mm=210.0, page_height_mm=297.0, gutter_mm=0.0,
        copies=10, margin_mm=110.0, cut_gap_mm=0.0,
        papers=[(800, 550, 5, "width"), (900, 640, 30, "height")],
    )
    assert r["papers"][0]["pieces_per_sheet"] == 0
    assert r["papers"][0]["used_sheets"] == 0
    assert r["papers"][1]["pieces_per_sheet"] == 1
    assert r["papers"][1]["used_sheets"] == 10


def test_margin_and_cut_gap_respected():
    # 留边 20：可用 840x580，纸纹沿高：列 floor(840/420)=2、行 floor(580/297)=1
    r = _plan_one((880, 620, 30, "height"), margin_mm=20.0, cut_gap_mm=0.0,
                  copies=10)
    assert r["papers"][0]["columns"] == 2
    assert r["papers"][0]["rows"] == 1
    assert r["papers"][0]["pieces_per_sheet"] == 2


# ---------------------------------------------------------------------------
# 组合选择：面积最小 -> 超产最少 -> 输入顺序用量字典序
# ---------------------------------------------------------------------------


def test_selects_minimum_total_area():
    # A: 880x620 纸纹沿宽出 2，单位面积 272800；B: 900x640 纸纹沿高出 4，
    # 单位面积 144000。需求 100：25 张 B（面积 14,400,000）优于 50 张 A
    r = plan_paper_stock(
        total_pages=4, max_sheets=1, binding="left",
        page_width_mm=210.0, page_height_mm=297.0, gutter_mm=0.0,
        copies=100, margin_mm=10.0, cut_gap_mm=3.0,
        papers=[(880, 620, 30, "width"), (900, 640, 30, "height")],
    )
    assert [p["used_sheets"] for p in r["papers"]] == [0, 25]
    assert r["total_area_mm2"] == 25 * 900 * 640
    assert r["total_produced"] == 100
    assert r["surplus"] == 0


def test_area_tie_prefers_less_surplus():
    # 1000x700、纸纹沿高、留边 10、间隔 3：列 2、行 2 -> 单张出数 4
    # 需求 10：3 张产 12，超产 2（2 张仅 8 张不满足）
    r = _plan_one((1000, 700, 30, "height"), copies=10)
    p = r["papers"][0]
    assert p["pieces_per_sheet"] == 4
    assert p["used_sheets"] == 3
    assert r["total_produced"] == 12
    assert r["surplus"] == 2


def test_area_tie_same_surplus_lexicographic_on_input_order():
    # 两个规格面积与出数完全相同：用量元组字典序最小 = 首位尽量小，
    # 即等面积等超产方案中把用量压到输入靠后的规格
    r = plan_paper_stock(
        total_pages=8, max_sheets=2, binding="left",
        page_width_mm=100.0, page_height_mm=100.0, gutter_mm=0.0,
        copies=20, margin_mm=0.0, cut_gap_mm=0.0,
        papers=[
            (1000, 700, 30, "height"),
            (1000, 700, 30, "height"),
        ],
    )
    # 成品 200x100，纸纹沿高：列 5、行 7 -> 35 出；需求 40 -> 2 张
    assert r["papers"][0]["pieces_per_sheet"] == 35
    assert r["demand"] == 40
    assert [p["used_sheets"] for p in r["papers"]] == [0, 2]
    assert r["total_produced"] == 70
    assert r["surplus"] == 30


def test_lex_order_with_larger_area_last_grade():
    # 前 5 个规格面积相同，最后一个略大；最优面积只允许使用前 5 个规格，
    # 字典序最小应尽量填满第 5 个（最后一个等面积规格）而非第 1 个
    r = plan_paper_stock(
        total_pages=8, max_sheets=2, binding="left",
        page_width_mm=100.0, page_height_mm=100.0, gutter_mm=0.0,
        copies=200, margin_mm=0.0, cut_gap_mm=0.0,
        papers=[(1000, 700, 30, "height")] * 5
        + [(1000, 701, 30, "height")],
    )
    assert [p["used_sheets"] for p in r["papers"]] == [0, 0, 0, 0, 12, 0]
    assert r["surplus"] == 20


def test_mixed_combination_when_cheapest_stock_exhausted():
    # A（单位面积 272800，出 2）比 B（单位面积 144000，出 4）贵，
    # 但 A 库存仅 2；需求 10。枚举：
    #   3 张 B：产 12，面积 1,728,000
    #   1 张 A + 2 张 B：产 10，面积 545,600 + 1,152,000 = 1,697,600（最优）
    #   2 张 A + 2 张 B：面积更大
    r = plan_paper_stock(
        total_pages=4, max_sheets=1, binding="left",
        page_width_mm=210.0, page_height_mm=297.0, gutter_mm=0.0,
        copies=10, margin_mm=10.0, cut_gap_mm=3.0,
        papers=[
            (880, 620, 2, "width"),   # 出 2，库存 2
            (900, 640, 30, "height"),  # 出 4
        ],
    )
    assert [p["used_sheets"] for p in r["papers"]] == [1, 2]
    assert r["total_area_mm2"] == 545_600 + 2 * 576_000
    assert r["total_produced"] == 10
    assert r["surplus"] == 0


def test_stock_zero_grade_returned_with_zero_usage():
    r = plan_paper_stock(
        total_pages=4, max_sheets=1, binding="left",
        page_width_mm=210.0, page_height_mm=297.0, gutter_mm=0.0,
        copies=10, margin_mm=10.0, cut_gap_mm=3.0,
        papers=[(880, 620, 0, "width"), (900, 640, 30, "height")],
    )
    assert r["papers"][0]["used_sheets"] == 0
    assert r["papers"][1]["used_sheets"] == 3
    assert r["total_produced"] == 12


def test_infeasible_raises_value_error():
    with pytest.raises(ValueError, match="无可行原纸组合"):
        plan_paper_stock(
            total_pages=4, max_sheets=1, binding="left",
            page_width_mm=210.0, page_height_mm=297.0, gutter_mm=0.0,
            copies=100, margin_mm=10.0, cut_gap_mm=3.0,
            papers=[(900, 640, 10, "height")],  # 10 张 × 4 = 40 < 100
        )


def test_all_grades_zero_pieces_infeasible():
    # 留边 110：两种沿宽原纸扣除留边后行向都放不下印张宽 420 -> 出数全为 0
    with pytest.raises(ValueError, match="无可行原纸组合"):
        plan_paper_stock(
            total_pages=4, max_sheets=1, binding="left",
            page_width_mm=210.0, page_height_mm=297.0, gutter_mm=0.0,
            copies=1, margin_mm=110.0, cut_gap_mm=0.0,
            papers=[(800, 550, 30, "width"), (810, 560, 30, "width")],
        )


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def _base_kwargs(papers=None):
    return dict(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=210.0,
        page_height_mm=297.0,
        gutter_mm=0.0,
        copies=10,
        margin_mm=10.0,
        cut_gap_mm=3.0,
        papers=papers if papers is not None else [(900, 640, 30, "height")],
    )


def test_invalid_total_pages():
    for value in (0, -1):
        with pytest.raises(ValueError):
            plan_paper_stock(**{**_base_kwargs(), "total_pages": value})


def test_invalid_binding():
    with pytest.raises(ValueError):
        plan_paper_stock(**{**_base_kwargs(), "binding": "top"})


def test_invalid_dimensions():
    for field, value in (
        ("page_width_mm", 0),
        ("page_height_mm", -1.0),
        ("gutter_mm", -0.5),
    ):
        with pytest.raises(ValueError):
            plan_paper_stock(**{**_base_kwargs(), field: value})


def test_non_finite_dimensions_rejected():
    for field, value in (
        ("page_width_mm", float("nan")),
        ("page_height_mm", float("inf")),
        ("margin_mm", float("-inf")),
        ("cut_gap_mm", float("nan")),
    ):
        with pytest.raises(ValueError):
            plan_paper_stock(**{**_base_kwargs(), field: value})


def test_invalid_copies():
    for value in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            plan_paper_stock(**{**_base_kwargs(), "copies": value})


def test_invalid_negative_margin_or_gap():
    for field in ("margin_mm", "cut_gap_mm"):
        with pytest.raises(ValueError):
            plan_paper_stock(**{**_base_kwargs(), field: -0.1})


def test_paper_count_out_of_range():
    with pytest.raises(ValueError):
        plan_paper_stock(**_base_kwargs(papers=[]))
    with pytest.raises(ValueError):
        plan_paper_stock(
            **_base_kwargs(papers=[(900, 640, 30, "height")] * 7)
        )


def test_paper_dimensions_must_be_positive_integers():
    for paper in (
        (0, 640, 30, "height"),
        (900, -1, 30, "height"),
        (900.0, 640, 30, "height"),
        (True, 640, 30, "height"),
    ):
        with pytest.raises(ValueError):
            plan_paper_stock(**_base_kwargs(papers=[paper]))


def test_paper_stock_range_and_integer():
    for paper in (
        (900, 640, -1, "height"),
        (900, 640, 31, "height"),
        (900, 640, 1.5, "height"),
        (900, 640, True, "height"),
    ):
        with pytest.raises(ValueError):
            plan_paper_stock(**_base_kwargs(papers=[paper]))


def test_invalid_grain_direction():
    with pytest.raises(ValueError):
        plan_paper_stock(**_base_kwargs(papers=[(900, 640, 30, "long")]))


def test_malformed_paper_tuple():
    with pytest.raises(ValueError):
        plan_paper_stock(**_base_kwargs(papers=[(900, 640, 30)]))
