"""L3: call-order replay through the tool layer (no LLM)."""
import json

import pytest

from thmstudio.session import Session
from thmstudio.tools import call, visible_tools


@pytest.fixture
def s(tmp_path):
    return Session(root=tmp_path)


def ok(out):
    assert out["ok"], json.dumps({k: out.get(k) for k in ("error", "fix", "details")})
    return out


def wait(s):
    for _ in range(200):
        out = call(s, "run_status")
        if out.get("status") in ("succeeded", "failed"):
            return out
    raise AssertionError("run did not finish")


def test_visible_tools_stay_small(s):
    assert len(visible_tools(s)) <= 6
    ok(call(s, "start_from_example", {"example_id": "surface_heating"}))
    for step in ("geometry", "physics", "materials", "conditions", "mesh", "study"):
        ok(call(s, "go_to_step", {"step": step}))
        assert 4 <= len(visible_tools(s)) <= 6


def test_example_fast_path_and_cache(s):
    ok(call(s, "start_from_example", {"example_id": "surface_heating",
                                      "changes": [{"name": "duration", "value": "2 yr"}]}))
    ok(call(s, "build_mesh"))
    ok(call(s, "check_model"))
    ok(call(s, "run"))
    out = ok(wait(s))
    assert out["status"] == "succeeded" and out["checks"]["reached_end_time"]
    ok(call(s, "show_results", {"field": "temperature", "kind": "profile", "probe": "depth_profile"}))
    # same model again: cached, no new computation
    ok(call(s, "go_to_step", {"step": "study"}))
    assert ok(call(s, "check_model"))["ok"]
    assert ok(call(s, "run"))["cached"] is True


def test_hidden_tool_gives_next_step(s):
    out = call(s, "run")
    assert not out["ok"] and "start_from_example" in out["error"] and "Available now" in out["error"]


def test_skipping_check_is_refused(s):
    ok(call(s, "start_from_example", {"example_id": "surface_heating"}))
    ok(call(s, "build_mesh"))
    out = call(s, "run")
    assert not out["ok"] and "check_model" in out["error"]


def test_edit_invalidates_check(s):
    ok(call(s, "start_from_example", {"example_id": "surface_heating"}))
    ok(call(s, "build_mesh"))
    ok(call(s, "check_model"))
    assert s.state == "CHECKED"
    ok(call(s, "go_to_step", {"step": "materials"}))
    ok(call(s, "set_materials", {"materials": [{"region": "rock", "values": [{"name": "thermal_conductivity", "value": "2.5 W/m/K"}]}]}))
    assert s.state == "DRAFT"
    assert not call(s, "run")["ok"]


def test_mesh_change_requires_rebuild(s):
    ok(call(s, "start_from_example", {"example_id": "surface_heating"}))
    ok(call(s, "build_mesh"))
    ok(call(s, "set_mesh", {"size": "2 m"}))
    out = call(s, "check_model")
    assert not out["ok"] and any(i["code"] == "mesh_outdated" for i in out["issues"])
    assert s.focus == "mesh"


def test_empty_tree_assembly_with_mistakes(s):
    ok(call(s, "new_project", {"name": "my_block"}))
    ok(call(s, "set_geometry", {"shape": "rect", "width": "40 m", "layers": [{"name": "rock", "thickness": "20 m"}]}))
    ok(call(s, "set_physics", {"process": "T"}))
    out = call(s, "set_materials", {"materials": [{"region": "rock", "values": [
        {"name": "thermal_conductivity", "value": "2.5 W/m/K"}, {"name": "porosity", "value": "20"}]}]})
    assert not out["ok"] and "percentage" in json.dumps(out["details"])
    out = call(s, "set_materials", {"materials": [{"region": "rok", "values": []}]})
    assert not out["ok"] and "rock" in out["fix"]
    ok(call(s, "set_materials", {"materials": [{"region": "rock", "values": [
        {"name": "thermal_conductivity", "value": "2.5 W/m/K"}, {"name": "density", "value": "2600 kg/m3"},
        {"name": "specific_heat", "value": "900 J/kg/K"}]}]}))
    out = call(s, "set_conditions", {"boundary_conditions": [{"boundary": "lft", "variable": "temperature", "kind": "fixed", "value": "30 degC"}]})
    assert not out["ok"] and "left" in out["fix"]
    out = call(s, "set_conditions", {"boundary_conditions": [{"boundary": "left", "variable": "temperature", "kind": "fixed", "value": "30 MPa"}]})
    assert not out["ok"]
    ok(call(s, "set_conditions", {"boundary_conditions": [{"boundary": "left", "variable": "temperature", "kind": "fixed", "value": "30 degC"}],
                                  "initial": [{"name": "temperature", "value": "10 degC"}]}))
    ok(call(s, "set_mesh", {"size": "1 m", "refinements": [{"target": "left", "size": "0.1 m", "growth": 1.2}]}))
    ok(call(s, "build_mesh"))
    out = call(s, "check_model")
    assert not out["ok"]  # study not set yet
    ok(call(s, "go_to_step", {"step": "study"}))
    ok(call(s, "set_study", {"kind": "transient", "end_time": "1 yr", "first_step": "1 d", "growth": 1.2, "max_step": "20 d",
                             "output_times": ["0.25 yr"]}))
    ok(call(s, "check_model"))
    ok(call(s, "run"))
    assert wait(s)["status"] == "succeeded"
    out = ok(call(s, "show_results", {"field": "temperature", "kind": "map"}))
    assert out["max"] == pytest.approx(303.15, abs=1e-6)


def test_unsupported_configuration_refused_with_contact(s):
    ok(call(s, "new_project", {"name": "x"}))
    ok(call(s, "set_geometry", {"shape": "axisym_well", "well_radius": "0.1 m", "outer_radius": "100 m",
                                "layers": [{"name": "aq", "thickness": "10 m"}]}))
    out = ok(call(s, "set_physics", {"process": "HC", "component": {"name": "tr", "pore_diffusion": "1e-9 m2/s"}}))
    assert "not verified" in out["warning"]


def test_steady_transport_refused(s):
    ok(call(s, "start_from_example", {"example_id": "solute_front"}))
    ok(call(s, "build_mesh"))
    ok(call(s, "go_to_step", {"step": "study"}))
    ok(call(s, "set_study", {"kind": "steady"}))
    out = call(s, "check_model")
    assert not out["ok"] and any(i["code"] == "steady_not_supported" for i in out["issues"])


def test_ask_user_limit(s):
    for i in range(3):
        ok(call(s, "ask_user", {"question": f"q{i}", "default": "x"}))
    assert not call(s, "ask_user", {"question": "q4", "default": "x"})["ok"]


def test_unknown_example_lists_ids(s):
    out = call(s, "start_from_example", {"example_id": "nope"})
    assert not out["ok"] and "heated_inclusion" in out["fix"]


def test_bad_example_change_name(s):
    out = call(s, "start_from_example", {"example_id": "surface_heating", "changes": [{"name": "colour", "value": "red"}]})
    assert not out["ok"] and "duration" in out["fix"]


def test_audit_log_written(s):
    ok(call(s, "start_from_example", {"example_id": "surface_heating"}))
    lines = (s.dir / "audit.log").read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["tool"] == "start_from_example" and rec["ok"] is True and "time" in rec


def test_change_row_names_its_component(s):
    ok(call(s, "start_from_example", {"example_id": "consolidation_column"}))
    ok(call(s, "build_mesh"))
    ok(call(s, "check_model"))
    ok(call(s, "run"))
    assert wait(s)["status"] == "succeeded"
    ok(call(s, "answer_card", {"items": [{"label": "settlement", "kind": "change", "field": "displacement",
                                          "component": "y", "probe": "surface"}]}))
    row = s.cards[-1]["rows"][0]
    assert row["quantity"] == "displacement (y)" and float(row["value"]) < 0
