"""An overshoot outside the initial and fixed values is reported on the card as a warning."""
import numpy as np

from thmstudio.report import range_check
from thmstudio.schema import Model

MODEL = {"name": "r", "geometry": {"kind": "rect", "width": 10.0, "layers": [{"name": "sand", "thickness": 1.0}]},
         "physics": {"process": "HC", "components": [{"name": "salt", "pore_diffusion": 1e-9}]},
         "materials": {"sand": {"permeability": 1e-12, "porosity": 0.3}},
         "boundary_conditions": [{"boundary": "left", "variable": "concentration", "value": 1.0},
                                 {"boundary": "left", "variable": "head", "value": 1.0},
                                 {"boundary": "right", "variable": "head", "value": 0.0}],
         "initial": {"concentration": 0.0, "head": 0.0}, "mesh": {"size": 1.0},
         "study": {"kind": "transient", "end_time": 1000.0}}


class FakeResults:
    def __init__(self, lo, hi):
        self.times = np.array([0.0, 1000.0])
        self._v = np.array([lo, 0.5, hi])

    def mesh_at(self, t):
        return None

    def field(self, mesh, name):
        assert name == "salt"
        return self._v


def test_overshoot_is_reported():
    m = Model.model_validate(MODEL)
    out = range_check(m, FakeResults(-0.18, 1.0))
    assert "concentration" in out and "18 %" in out["concentration"]


def test_values_in_range_pass():
    m = Model.model_validate(MODEL)
    assert range_check(m, FakeResults(0.0, 1.005)) == {}
