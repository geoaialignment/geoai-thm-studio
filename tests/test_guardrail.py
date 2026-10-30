"""S4: the answer may quote only card values, the user's inputs (in sensible units) and numbers tools reported."""
import pytest

from thmstudio.report import check_answer
from thmstudio.schema import Model
from thmstudio.session import Session
from thmstudio.tools import call

M = Model(geometry={"kind": "rect", "width": 100, "layers": [{"name": "rock", "thickness": 50}]}, physics={"process": "T"},
          materials={"rock": {"thermal_conductivity": 3, "density": 2650, "specific_heat": 850}},
          boundary_conditions=[{"boundary": "top", "variable": "temperature", "value": "25 degC"}],
          initial={"temperature": "15 degC"}, study={"kind": "transient", "end_time": "10 yr"})
CARD = {"rows": [{"value": "23.6", "unit": "°C", "value_si": 296.75, "unit_si": "K"},
                  {"value": "-3.06", "unit": "m", "value_si": -3.06, "unit_si": "m"}],
        "verification": {"cases": [{"case": "V2a", "worst_normalised_error": 0.0021}]}}


@pytest.mark.parametrize("text,bad", [
    ("At 5 m the rock reaches 23.6 °C after 10 years (surface 25 °C, initially 15 °C).", []),
    ("The water level drops 3.06 m.", []),                      # sign-free
    ("Verification error 0.21 %.", []),                          # card verification, as percent
    ("Conductivity 3 W/m/K, density 2650 kg/m3.", []),           # inputs
    ("The rise is 8.6 K.", ["8.6"]),                             # arithmetic by the model
    ("It reaches 24.9 °C.", ["24.9"]),                           # invented
    ("Heat capacity 4.18 kJ/kg/K.", ["4.18"]),                   # no blanket unit scaling
])
def test_numbers(text, bad):
    assert check_answer(text, M, [CARD], user_text="How warm is the rock at 5 m depth?") == bad


def test_small_numbers_with_units_are_checked():
    assert check_answer("The rock warms by 7 K.", M, [CARD]) == ["7"]
    assert check_answer("Step 3 of the work is done.", M, [CARD]) == []


def test_without_model_only_user_and_tool_numbers():
    assert check_answer("A 600 m wide layer gives 42.5 kg.", None, [], user_text="a 600 m wide layer") == ["42.5"]


def test_tool_numbers_allowed():
    assert check_answer("The mesh has 10,250 elements.", M, [CARD], seen=[10250.0]) == []


def test_change_item_on_card(tmp_path):
    s = Session(root=tmp_path)
    call(s, "start_from_example", {"example_id": "surface_heating", "changes": [{"name": "duration", "value": "2 yr"}]})
    call(s, "build_mesh"); call(s, "check_model"); call(s, "run")
    for _ in range(100):
        if call(s, "run_status").get("status") == "succeeded":
            break
    out = call(s, "answer_card", {"items": [
        {"label": "temperature at 5 m", "kind": "value", "field": "temperature", "probe": "at_5m"},
        {"label": "rise at 5 m", "kind": "change", "field": "temperature", "probe": "at_5m"}]})
    rows = s.cards[-1]["rows"]
    assert out["ok"] and rows[1]["unit"] == "K"
    assert float(rows[0]["value"]) - 15.0 == pytest.approx(float(rows[1]["value"]), abs=0.06)


def test_a_unit_must_match_the_source_dimension():  # independent review, finding 10
    assert check_answer("The peak temperature is 2650 °C.", M, [CARD]) == ["2650"]      # a density, not a temperature
    assert check_answer("The peak temperature is 987.65 °C.", M, [CARD], seen=[987.65]) == ["987.65"]
    assert check_answer("The run took 13.4 s over 122 steps.", M, [CARD], seen=[13.4, 122.0]) == []
    assert check_answer("Density 2650 kg/m3 as you gave it.", M, [CARD]) == []


def test_numbers_touching_korean_text_are_read():
    from thmstudio.report import check_answer
    request = "암반 지표가 10년 동안 10도 더 따뜻해지면 땅속 5 m 깊이 온도가 얼마나 오르는지"
    assert check_answer("지표 온도를 10 K 올린 모델입니다", None, [], [], request) == []
    assert check_answer("온도가 37도 올랐습니다", None, [], [], request) == ["37"]


def test_run_check_counts_may_be_quoted_but_not_as_results():
    from thmstudio.report import check_answer
    card = {"rows": [], "verification": {"cases": []}, "run_checks": {"time_steps": 92, "rejected_steps": 0}}
    assert check_answer("시간 단계는 92개였습니다", None, [card], [], "") == []
    assert check_answer("온도는 92 K 올랐습니다", None, [card], [], "") == ["92"]
