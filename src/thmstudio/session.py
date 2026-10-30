"""Session: one project, its model tree, the state machine and the audit log.

States: EMPTY -> DRAFT -> CHECKED -> RUNNING -> COMPUTED -> REPORTED. Any change
to the model returns to DRAFT and invalidates the check and the current result
(results stay cached by model hash). In DRAFT a focus step decides which
editing tools are visible, so a small model sees only what fits the next step.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .schema import (BoundaryCondition, Geometry, HeatSource, Initial, Material, MeshSettings, Model, Physics,
                     Probe, Study, regions_of)

STEPS = ("geometry", "physics", "materials", "conditions", "mesh", "study")
STATES = ("EMPTY", "DRAFT", "CHECKED", "RUNNING", "COMPUTED", "REPORTED")


@dataclass
class Session:
    root: Path
    name: str = "model"
    state: str = "EMPTY"
    focus: str = "geometry"
    geometry: object | None = None
    physics: Physics | None = None
    materials: dict[str, Material] = field(default_factory=dict)
    boundary_conditions: list[BoundaryCondition] = field(default_factory=list)
    heat_sources: list[HeatSource] = field(default_factory=list)
    initial: Initial = field(default_factory=Initial)
    mesh_settings: MeshSettings = field(default_factory=MeshSettings)
    study: Study | None = None
    probes: list[Probe] = field(default_factory=list)
    version: int = 0
    mesh: dict | None = None        # {'hash', 'summary', 'report', 'bundle', 'dir', 'preview'}
    check: dict | None = None       # {'hash', 'report'}
    job: dict | None = None         # {'id', 'hash'}
    results: dict = field(default_factory=dict)  # model hash -> run record dict
    compares: dict = field(default_factory=dict)   # comparison name -> result
    cards: list = field(default_factory=list)      # answer cards of this session
    seen_numbers: set = field(default_factory=set)  # numbers reported by tools (allowed in answers)
    user_texts: list = field(default_factory=list)  # the user's own messages (their numbers may be quoted)
    asks: int = 0
    example: str | None = None
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ model
    @property
    def model(self) -> Model | None:
        if self.geometry is None or self.physics is None:
            return None
        return Model(name=self.name, geometry=self.geometry, physics=self.physics, materials=self.materials,
                     boundary_conditions=self.boundary_conditions, heat_sources=self.heat_sources,
                     initial=self.initial, mesh=self.mesh_settings, study=self.study or Study(kind="steady"),
                     probes=self.probes)

    def load_model(self, model: Model):
        self.name = model.name
        self.geometry, self.physics = model.geometry, model.physics
        self.materials = dict(model.materials)
        self.boundary_conditions = list(model.boundary_conditions)
        self.heat_sources = list(model.heat_sources)
        self.initial = model.initial
        self.mesh_settings = model.mesh
        self.study = model.study
        self.probes = list(model.probes)
        self.changed()

    def changed(self):
        """Any edit: back to DRAFT, check and current result invalid."""
        self.version += 1
        self.check = None
        self.state = "DRAFT"
        self.focus = self.next_step()

    # ------------------------------------------------------------ progress
    def step_done(self, step: str) -> bool:
        if step == "geometry":
            return self.geometry is not None
        if step == "physics":
            return self.physics is not None
        if step == "materials":
            return self.geometry is not None and all(r in self.materials for r in regions_of(self.geometry))
        if step == "conditions":
            return bool(self.boundary_conditions)
        if step == "mesh":
            m = self.model
            from .check import mesh_hash
            return m is not None and self.mesh is not None and self.mesh["hash"] == mesh_hash(m)
        if step == "study":
            return self.study is not None
        raise KeyError(step)

    def next_step(self) -> str:
        for s in STEPS:
            if not self.step_done(s):
                return s
        return "check"

    # ------------------------------------------------------------ audit
    @property
    def dir(self) -> Path:
        d = self.root / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def audit(self, tool: str, args: dict, ok: bool, note: str = ""):
        rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, "ok": ok, "state": self.state,
               "version": self.version, "args": _short(args), "note": note[:300]}
        with open(self.dir / "audit.log", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def save(self):
        m = self.model
        if m is not None:
            (self.dir / "model.json").write_text(m.model_dump_json(indent=1))


def _short(x, n=400):
    s = json.dumps(x, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


def friendly_validation(e: ValidationError) -> list[dict]:
    """Turn pydantic errors into messages with a fix (e.g. porosity 6 looks like a percentage)."""
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"].replace("Value error, ", "")
        fix = ""
        inp = err.get("input")
        try:
            num = float(str(inp).split()[0])
        except (ValueError, IndexError):
            num = None
        if "porosity" in loc and num is not None and 1 < num <= 100:
            fix = f"porosity {inp} looks like a percentage; use {num / 100:g}"
        elif err["type"] == "extra_forbidden":
            fix = "remove this field; it is not part of the model"
        elif err["type"] == "missing":
            fix = "give this value"
        out.append({"field": loc, "message": msg, "fix": fix})
    return out
