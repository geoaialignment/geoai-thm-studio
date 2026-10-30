"""Regression tests for the independent P1 review (reviews/p1_review_astra.md)."""
import json
from pathlib import Path

import pytest

from thmstudio.check import check_model
from thmstudio.schema import Model
from thmstudio.session import Session
from thmstudio.tools import call
from thmstudio.translator import time_steps, translate

CASES = Path(__file__).resolve().parents[1] / "src" / "thmstudio" / "cases"


def case_model(cid):
    return json.loads((CASES / f"{cid}.json").read_text())["model"]


def checked(d, tmp_path):
    s = Session(root=tmp_path)
    s.load_model(Model.model_validate(d))
    call(s, "build_mesh")
    return call(s, "check_model")


def codes(rep):
    return {i["code"] for i in rep["issues"] if i["level"] == "error"}


def test_concentration_flux_is_refused(tmp_path):  # finding 1
    d = case_model("V6a")
    d["boundary_conditions"] = [b for b in d["boundary_conditions"] if b["variable"] != "concentration"] + [
        {"boundary": "left", "variable": "concentration", "kind": "flux", "value": 1e-6}]
    assert "unverified_condition" in codes(checked(d, tmp_path))


def test_overlapping_inflows_are_refused(tmp_path):  # finding 3
    d = case_model("V1a")
    d["boundary_conditions"] += [{"boundary": "left", "variable": "head", "kind": "flux", "value": 1e-6},
                                 {"boundary": "left_lower", "variable": "head", "kind": "flux", "value": 1e-6}]
    d["boundary_conditions"] = [b for b in d["boundary_conditions"]
                                if not (b["boundary"] == "left" and b.get("kind", "fixed") == "fixed")]
    assert "overlapping_conditions" in codes(checked(d, tmp_path))


def test_neighbouring_sides_do_not_overlap(tmp_path):
    assert "overlapping_conditions" not in codes(checked(case_model("V1a"), tmp_path))


def test_duplicate_layer_names_are_refused(tmp_path):  # finding 4
    d = case_model("V1a")
    d["geometry"]["layers"][1]["name"] = d["geometry"]["layers"][0]["name"]
    d["materials"] = {d["geometry"]["layers"][0]["name"]: list(d["materials"].values())[0]}
    assert "duplicate_name" in codes(checked(d, tmp_path))


def test_misspelled_retardation_region_is_refused(tmp_path):  # finding 4
    d = case_model("V6b")
    region = next(iter(d["materials"]))
    d["physics"]["components"][0]["retardation"] = {region + "y": 5.0}
    assert "unknown_region" in codes(checked(d, tmp_path))


def test_capped_time_steps_do_not_overflow():  # finding 8
    d = case_model("V2a")
    d["study"] = {"kind": "transient", "end_time": 2000.0, "first_step": 1.0, "max_step": 1.0, "growth": 2.0}
    dts, _ = time_steps(Model.model_validate(d))
    assert len(dts) == 2000 and set(dts) == {1.0}


def test_failed_edit_leaves_the_model_unchanged(tmp_path):  # finding 15
    s = Session(root=tmp_path)
    s.load_model(Model.model_validate(case_model("V1a")))
    before, version = s.model.model_dump(), s.version
    region = next(iter(s.materials))
    out = call(s, "set_materials", {"materials": [
        {"region": region, "values": [{"name": "hydraulic_conductivity", "value": "1e-4 m/s"}]},
        {"region": "no_such_region", "values": [{"name": "porosity", "value": "0.2"}]}]})
    assert not out["ok"] and s.model.model_dump() == before and s.version == version


def test_steady_heat_needs_no_heat_capacity(tmp_path):  # finding 12
    d = case_model("V2b")
    for m in d["materials"].values():
        m.pop("density", None), m.pop("specific_heat", None)
    rep = checked(d, tmp_path)
    assert rep["ok"], rep["issues"]
    from thmstudio.mesh import build_mesh
    model = Model.model_validate(d)
    bundle, _ = build_mesh(model, tmp_path / "b")
    translate(model, bundle, tmp_path / "b")


def test_heat_flux_summary_is_not_a_temperature():  # finding 14
    from thmstudio.check import tree_summary
    d = case_model("V2a")
    d["boundary_conditions"].append({"boundary": "right", "variable": "temperature", "kind": "flux", "value": 10.0})
    text = tree_summary(Model.model_validate(d))
    assert "10 W/m2" in text and "-263" not in text


def test_missing_output_time_is_an_error():  # finding 11
    from thmstudio.tools import output_time
    assert output_time([0.0, 10.0, 20.0], 10.0) == 10.0
    with pytest.raises(ValueError):
        output_time([0.0, 10.0, 20.0], 1e15)


def _computed(tmp_path, example, changes=()):
    s = Session(root=tmp_path)
    call(s, "start_from_example", {"example_id": example, "changes": list(changes)})
    call(s, "build_mesh"); assert call(s, "check_model")["ok"]; call(s, "run")
    for _ in range(100):
        if call(s, "run_status").get("status") == "succeeded":
            return s
    raise AssertionError("run did not finish")


def test_old_comparison_is_not_put_on_a_new_card(tmp_path):  # finding 9
    s = _computed(tmp_path, "surface_heating", [{"name": "duration", "value": "1 yr"}])
    s.compares["half_element_size"] = {"base_run_id": "an_earlier_run", "field": "temperature", "probe": "at_5m",
                                       "time_s": 1.0, "max_abs_difference": 99.0}
    out = call(s, "answer_card", {"items": [{"label": "mesh effect", "kind": "comparison",
                                             "comparison": "half_element_size"}]})
    assert not out["ok"] and "half_element_size" in out["error"]


def test_figures_belong_to_their_run(tmp_path):  # finding 9
    s = _computed(tmp_path, "surface_heating", [{"name": "duration", "value": "1 yr"}])
    call(s, "show_results", {"field": "temperature", "kind": "map"})
    run_id = s.results[s.model.content_hash()]["run_id"]
    assert list((s.dir / "figures" / run_id).glob("*.png"))
    assert not list((s.dir / "figures").glob("*.png"))


def test_coarse_point_source_is_refused(tmp_path):  # found in the final API check (s11)
    s = Session(root=tmp_path)
    call(s, "start_from_example", {"example_id": "point_heat_source", "changes": [{"name": "source_power", "value": "300 W"}]})
    call(s, "set_mesh", {"size": "1 m", "element": "auto", "refinements": [{"target": "source", "size": "0.2 m", "growth": 1.2}]})
    call(s, "build_mesh")
    rep = call(s, "check_model")
    assert "source_resolution" in codes(rep)
    call(s, "set_mesh", {"size": "0.5 m", "element": "quad", "refinements": [{"target": "source", "size": "0.05 m", "growth": 1.1}]})
    call(s, "build_mesh")
    assert "source_resolution" in codes(call(s, "check_model"))  # gave 0.887 MPa against 0.967 (8 % low)
    call(s, "set_mesh", {"size": "0.5 m", "element": "quad", "refinements": [{"target": "source", "size": "0.0289 m", "growth": 1.1}]})
    call(s, "build_mesh")
    assert "source_resolution" in codes(call(s, "check_model"))  # ell/4: 6 % low in the sweep
    call(s, "set_mesh", {"size": "1 m", "element": "auto", "refinements": [{"target": "source", "size": "0.01 m", "growth": 1.1}]})
    call(s, "build_mesh")
    assert call(s, "check_model")["ok"]


def test_v5_model_passes_the_source_check(tmp_path):
    assert "source_resolution" not in codes(checked(case_model("V5"), tmp_path))
