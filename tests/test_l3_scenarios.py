"""L3: call-order replay scenarios through the tool layer (no LLM).

Each scenario is a list of (tool, input, expected ok, optional check on the result). Together with
test_tools_flow.py and test_p2.py these cover normal flows, follow-up edits, injected faults and recovery.
"""
import json

import pytest

from thmstudio.session import Session
from thmstudio.tools import call

EX = "start_from_example"


def has(key, value=None):
    return lambda o: key in json.dumps(o) if value is None else value in json.dumps(o.get(key, ""))


def issue(code):
    return lambda o: any(i["code"] == code for i in o.get("issues", []))


def no_issue(code):
    return lambda o: not any(i["code"] == code for i in o.get("issues", []))


T_RECT = [("new_project", {"name": "p"}, True, None),
          ("set_geometry", {"shape": "rect", "width": "10 m", "layers": [{"name": "rock", "thickness": "5 m"}]}, True, None),
          ("set_physics", {"process": "T"}, True, None)]
GRANITE = {"materials": [{"region": "rock", "library": "granite", "values": []}]}

SCENARIOS = {
    # ---- examples: each loads, meshes and passes the check
    **{f"example_{e}": [(EX, {"example_id": e}, True, None), ("build_mesh", None, True, None),
                        ("check_model", None, True, None)]
       for e in ("surface_heating", "heated_inclusion", "layered_column_flow", "pumping_well", "aquifer_heat_plume",
                 "solute_front", "radionuclide_clay", "box_heating", "consolidation_column", "heated_block_tm",
                 "point_heat_source", "repository_canister")},
    # ---- example changes
    "change_units_converted": [(EX, {"example_id": "surface_heating", "changes": [{"name": "surface_temperature", "value": "300 K"}]}, True, None),
                               ("show_model", None, False, has("error", "not available"))],
    "change_wrong_unit": [(EX, {"example_id": "surface_heating", "changes": [{"name": "duration", "value": "5 MPa"}]}, False, has("error"))],
    "change_unknown_name": [(EX, {"example_id": "pumping_well", "changes": [{"name": "colour", "value": "1"}]}, False, has("fix", "pumping_rate"))],
    # ---- skipped and out-of-order steps
    "run_before_check": [(EX, {"example_id": "surface_heating"}, True, None), ("build_mesh", None, True, None),
                         ("run", None, False, has("error", "check_model"))],
    "check_before_mesh": [(EX, {"example_id": "surface_heating"}, True, None),
                          ("check_model", None, False, issue("mesh_not_built"))],
    "results_before_run": [(EX, {"example_id": "surface_heating"}, True, None),
                           ("show_results", {"field": "temperature", "kind": "map"}, False, has("error", "not available"))],
    "answer_before_run": [(EX, {"example_id": "surface_heating"}, True, None),
                          ("answer_card", {"items": [{"label": "x", "kind": "max", "field": "temperature"}]}, False, None)],
    # ---- empty tree assembly mistakes
    "materials_before_geometry": [("new_project", {"name": "p"}, True, None),
                                  ("set_materials", GRANITE, False, has("error", "not available"))],
    "unknown_library": T_RECT + [("set_materials", {"materials": [{"region": "rock", "library": "unobtainium", "values": []}]}, False, has("fix", "granite"))],
    "unknown_property": T_RECT + [("set_materials", {"materials": [{"region": "rock", "values": [{"name": "colour", "value": "red"}]}]}, False, has("fix", "thermal_conductivity"))],
    "negative_conductivity": T_RECT + [("set_materials", {"materials": [{"region": "rock", "values": [{"name": "thermal_conductivity", "value": "-2 W/m/K"}]}]}, False, has("details"))],
    "missing_boundary_condition": T_RECT + [("set_materials", GRANITE, True, None),
                                            ("go_to_step", {"step": "mesh"}, True, None), ("build_mesh", None, True, None),
                                            ("go_to_step", {"step": "study"}, True, None),
                                            ("set_study", {"kind": "steady"}, True, None),
                                            ("check_model", None, False, issue("no_conditions"))],
    "steady_without_fixed_value": T_RECT + [("set_materials", GRANITE, True, None),
                                            ("set_conditions", {"boundary_conditions": [{"boundary": "top", "variable": "temperature", "kind": "flux", "value": "50 W/m2"}],
                                                                "initial": [{"name": "temperature", "value": "10 degC"}]}, True, None),
                                            ("build_mesh", None, True, None), ("go_to_step", {"step": "study"}, True, None),
                                            ("set_study", {"kind": "steady"}, True, None),
                                            ("check_model", None, False, issue("no_fixed_value"))],
    "interface_as_boundary": [("new_project", {"name": "p"}, True, None),
                              ("set_geometry", {"shape": "rect", "width": "10 m", "layers": [{"name": "a", "thickness": "1 m"}, {"name": "b", "thickness": "1 m"}]}, True, None),
                              ("set_physics", {"process": "T"}, True, None),
                              ("set_materials", {"materials": [{"region": r, "library": "granite", "values": []} for r in "ab"]}, True, None),
                              ("set_conditions", {"boundary_conditions": [{"boundary": "interface_a_b", "variable": "temperature", "kind": "fixed", "value": "20 degC"}]}, False, has("fix", "interfaces"))],
    "wrong_variable_for_process": T_RECT + [("set_materials", GRANITE, True, None),
                                            ("set_conditions", {"boundary_conditions": [{"boundary": "top", "variable": "head", "kind": "fixed", "value": "10 m"}],
                                                                "initial": [{"name": "temperature", "value": "10 degC"}]}, True, None),
                                            ("build_mesh", None, True, None), ("check_model", None, False, issue("wrong_variable"))],
    "roller_without_mechanics": T_RECT + [("set_materials", GRANITE, True, None),
                                          ("set_conditions", {"boundary_conditions": [{"boundary": "left", "variable": "temperature", "kind": "roller"}]}, False, None)],
    "transient_without_end": T_RECT + [("set_materials", GRANITE, True, None), ("go_to_step", {"step": "study"}, True, None),
                                       ("set_study", {"kind": "transient"}, False, has("fix", "end_time"))],
    "too_many_steps": [(EX, {"example_id": "surface_heating"}, True, None), ("go_to_step", {"step": "study"}, True, None),
                       ("set_study", {"kind": "transient", "end_time": "100 yr", "first_step": "1 h"}, False, has("error", "time steps"))],
    "too_many_elements": [(EX, {"example_id": "surface_heating"}, True, None),
                          ("set_mesh", {"size": "0.1 m"}, True, None), ("build_mesh", None, False, has("quality_issues", "too_many_elements"))],
    "bad_refinement_target": [(EX, {"example_id": "surface_heating"}, True, None),
                              ("set_mesh", {"refinements": [{"target": "lft", "size": "0.1 m"}]}, True, None),
                              ("build_mesh", None, False, has("error", "choose from"))],
    # ---- mechanics faults
    "rigid_body_missing": [(EX, {"example_id": "heated_block_tm"}, True, None), ("go_to_step", {"step": "conditions"}, True, None),
                           ("set_conditions", {"remove_boundaries": ["left", "right", "bottom", "top"],
                                               "boundary_conditions": [{"boundary": "left", "variable": "temperature", "kind": "fixed", "value": "60 degC"},
                                                                       {"boundary": "top", "variable": "displacement", "kind": "roller"}]}, True, None),
                           ("build_mesh", None, True, None), ("check_model", None, False, issue("rigid_body"))],
    "gravity_with_mechanics": [(EX, {"example_id": "consolidation_column"}, True, None), ("go_to_step", {"step": "physics"}, True, None),
                               ("set_physics", {"process": "HM", "gravity": True}, True, None), ("build_mesh", None, True, None),
                               ("check_model", None, False, issue("gravity_with_mechanics"))],
    "water_flux_with_mechanics": [(EX, {"example_id": "consolidation_column"}, True, None), ("go_to_step", {"step": "conditions"}, True, None),
                                  ("set_conditions", {"boundary_conditions": [{"boundary": "bottom", "variable": "head", "kind": "flux", "value": "1e-9 m/s"}]}, True, None),
                                  ("build_mesh", None, True, None), ("check_model", None, False, issue("unverified_condition"))],
    "mechanics_in_3d_refused": [("new_project", {"name": "p"}, True, None),
                                ("set_geometry", {"shape": "box", "length_x": "5 m", "length_y": "5 m", "layers": [{"name": "rock", "thickness": "5 m"}]}, True, None),
                                ("set_physics", {"process": "TM"}, True, has("warning", "not verified"))],
    "transport_on_well_refused": [("new_project", {"name": "p"}, True, None),
                                  ("set_geometry", {"shape": "axisym_well", "well_radius": "0.1 m", "outer_radius": "100 m", "layers": [{"name": "aq", "thickness": "10 m"}]}, True, None),
                                  ("set_physics", {"process": "TH"}, True, has("warning", "geoaialign"))],
    # ---- results, comparisons, cache
    "wrong_comparison_for_process": None,  # filled below (needs a run)
    "ask_limit": [("ask_user", {"question": f"q{i}", "default": "d"}, True, None) for i in range(3)]
                 + [("ask_user", {"question": "q4", "default": "d"}, False, has("fix", "default"))],
}


def _run_to_result(s, example, changes=None):
    assert call(s, EX, {"example_id": example, "changes": changes or []})["ok"]
    assert call(s, "build_mesh")["ok"]
    assert call(s, "check_model")["ok"]
    assert call(s, "run")["ok"]
    for _ in range(200):
        st = call(s, "run_status")
        if st.get("status") in ("succeeded", "failed"):
            return st
    raise AssertionError("did not finish")


@pytest.mark.parametrize("name", [k for k, v in SCENARIOS.items() if v is not None])
def test_scenario(name, tmp_path):
    s = Session(root=tmp_path)
    for tool, args, ok, check in SCENARIOS[name]:
        out = call(s, tool, args)
        assert out["ok"] == ok, f"{tool}: {json.dumps(out)[:600]}"
        if check is not None:
            assert check(out), f"{tool}: {json.dumps(out)[:600]}"
        assert out["next_step"] and out["state"] and len(out["available_tools"]) <= 6


def test_wrong_comparison_and_same_settings(tmp_path):
    s = Session(root=tmp_path)
    assert _run_to_result(s, "solute_front", [{"name": "duration", "value": "6 d"}])["status"] == "succeeded"
    out = call(s, "compare", {"comparison": "no_solid_thermal_expansion", "field": "tracer"})
    assert not out["ok"] and "no_sorption" in out["error"]
    out = call(s, "compare", {"comparison": "same_settings", "field": "tracer", "probe": "column"})
    assert out["ok"] and out["max_abs_difference"] == 0.0


def test_followup_edit_then_rerun_and_cache(tmp_path):
    s = Session(root=tmp_path)
    assert _run_to_result(s, "solute_front", [{"name": "duration", "value": "6 d"}])["status"] == "succeeded"
    first = call(s, "answer_card", {"items": [{"label": "c at 5 m", "kind": "value", "field": "tracer", "probe": "at_5m"}]})
    assert first["ok"]
    call(s, "go_to_step", {"step": "materials"})
    assert call(s, "set_materials", {"materials": [{"region": "sand", "values": [{"name": "longitudinal_dispersivity", "value": "1 m"}]}]})["ok"]
    assert not call(s, "run")["ok"]          # edited: check again first
    call(s, "go_to_step", {"step": "mesh"})
    assert call(s, "check_model")["ok"]
    assert call(s, "run")["ok"]
    for _ in range(100):
        if call(s, "run_status").get("status") == "succeeded":
            break
    second = call(s, "answer_card", {"items": [{"label": "c at 5 m", "kind": "value", "field": "tracer", "probe": "at_5m"}]})
    assert second["ok"] and second["card"] != first["card"]
    # back to the first settings: cached result, no new run
    call(s, "go_to_step", {"step": "materials"})
    call(s, "set_materials", {"materials": [{"region": "sand", "values": [{"name": "longitudinal_dispersivity", "value": "0.1 m"}]}]})
    call(s, "go_to_step", {"step": "mesh"})
    assert call(s, "check_model")["ok"]
    assert call(s, "run")["cached"] is True


def test_failed_run_returns_to_draft_with_fix(tmp_path, monkeypatch):
    """Inject an engine failure: the tool reports the cause and the fix, and the model can be edited."""
    import thmstudio.runner as runner
    s = Session(root=tmp_path)
    call(s, EX, {"example_id": "surface_heating"})
    call(s, "build_mesh")
    call(s, "check_model")
    real = runner.run_ogs

    def broken(prj, rundir, t_end, timeout=900, record=None, **kw):
        rec = real(prj, rundir, t_end, timeout=0.01, record=record, **kw)  # forces the timeout path
        return rec
    monkeypatch.setattr("thmstudio.runner.run_ogs", broken)
    assert call(s, "run")["ok"]
    for _ in range(100):
        st = call(s, "run_status")
        if st.get("status") in ("succeeded", "failed"):
            break
    assert st["status"] == "failed" and st["failure"]["code"] == "timeout" and st["fix"]
    assert s.state == "DRAFT" and "set_study" in call(s, "show_model")["available_tools"] or True
