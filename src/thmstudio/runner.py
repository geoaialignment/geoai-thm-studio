"""Executor: run OGS in its own process group with limits, classify failures.

A run succeeds only if OGS exits 0, the last output reaches the end time, every
output file holds finite values, and (when the caller says what to expect) every
requested output time and solution field is present. The output size is watched
while OGS runs.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

DEFAULT_TIMEOUT = 900.0  # seconds
MAX_OUTPUT_BYTES = 2_000_000_000
SIZE_POLL = 1.0          # seconds between output-size checks while OGS runs

FAILURES = [  # (code, pattern, message, fix)
    ("mesh_missing", r"[Cc]ould not (open|read)|[Ff]ile .* (not found|does not exist)",
     "OGS could not read an input file", "report this; the translator wrote an incomplete build"),
    ("material_mismatch", r"MaterialID|[Mm]edium (with|for) (id|material)|no medium",
     "a region has no matching medium", "report this; materials and regions are out of sync"),
    ("jacobian", r"[Jj]acobian|negative determinant",
     "an element is degenerate", "rebuild the mesh with a smaller growth or size"),
    ("nonconvergence", r"[Nn]onlinear solver (did not converge|failed)|[Nn]ot converged|reached maximum",
     "the solver did not converge", "use smaller time steps (first_step, max_step)"),
    ("linear_solver", r"[Ll]inear solver failed|[Ss]olver failed|SparseLU.*fail|singular",
     "the linear system could not be solved", "check that every variable has at least one fixed boundary value"),
    ("bad_input", r"ConfigTree|Could not construct OGSSimulation|error: .*(not found|missing|invalid|unknown)|Wrong|Exception",
     "OGS rejected the input", "report this; the translator wrote an input OGS does not accept"),
]


@dataclass
class RunRecord:
    run_id: str
    status: str = "queued"          # queued | running | succeeded | failed
    returncode: int | None = None
    seconds: float = 0.0
    failure: dict | None = None
    outputs: list[tuple[float, str]] = field(default_factory=list)
    reached_end: bool = False
    finite: bool = False
    log: str = "ogs.log"
    rundir: str = ""
    progress: float = 0.0           # simulated time / end time
    notes: list[str] = field(default_factory=list)
    cancelled: bool = False         # set by Jobs.cancel; the run stops at the next poll

    def as_dict(self):
        return asdict(self)


def ogs_executable() -> Path:
    return Path(sys.executable).parent / "ogs"


def read_pvd(pvd: Path) -> list[tuple[float, str]]:
    root = ET.parse(pvd).getroot()
    return [(float(d.get("timestep")), d.get("file")) for d in root.iter("DataSet")]


def classify(text: str) -> dict:
    for code, pat, msg, fix in FAILURES:
        if re.search(pat, text):
            line = next((l for l in text.splitlines() if re.search(pat, l)), "")
            return {"code": code, "message": msg, "fix": fix, "line": line.strip()[:300]}
    return {"code": "unknown", "message": "OGS stopped with an unrecognised error", "fix": "report this run",
            "line": text.strip().splitlines()[-1][:300] if text.strip() else ""}


def _progress(text: str, t_end: float) -> float:
    m = re.findall(r"Time step #\d+ started\. Time: (\S+?)\.? Step size", text)
    if not m or t_end <= 0:
        return 0.0
    return min(1.0, float(m[-1]) / t_end)


def run_ogs(prj: Path, rundir: Path, t_end: float, timeout: float = DEFAULT_TIMEOUT,
            record: RunRecord | None = None, expected_fields: list[str] | None = None,
            output_times: list[float] | None = None) -> RunRecord:
    """Run OGS; if an iterative linear solver fails, run once more with the direct solver within the time left.

    expected_fields: solution fields every output file must hold (point data names).
    output_times: times that must be among the outputs.
    """
    deadline = time.time() + timeout
    expect = {"expected_fields": expected_fields, "output_times": output_times}
    rec = _run_once(prj, rundir, t_end, timeout, record, **expect)
    if rec.status == "failed" and (rec.failure or {}).get("code") in ("nonconvergence", "linear_solver", "unknown"):
        text = Path(prj).read_text(encoding="ISO-8859-1")
        left = deadline - time.time()
        if "<solver_type>BiCGSTAB</solver_type>" in text and left > 1.0:
            direct = Path(prj).with_name(Path(prj).stem + "_direct.prj")
            direct.write_text(re.sub(r"<eigen>.*?</eigen>", "<eigen><solver_type>SparseLU</solver_type>"
                                     "<scaling>true</scaling></eigen>", text, flags=re.S), encoding="ISO-8859-1")
            for f in Path(rundir).glob("*"):
                if f.is_file():
                    f.unlink()
            first = rec.failure
            rec.failure, rec.outputs, rec.reached_end, rec.finite = None, [], False, False
            rec = _run_once(direct, rundir, t_end, left, rec, **expect)
            rec.notes.append(f"the iterative linear solver failed ({first.get('line', '')[:120]}); "
                             "the run was repeated with the direct solver")
    return rec


def _kill(proc: subprocess.Popen):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # it ended just now (macOS: zombie leader)
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _dir_size(path: Path) -> int:
    with os.scandir(path) as it:
        return sum(e.stat().st_size for e in it if e.is_file())


def _run_once(prj: Path, rundir: Path, t_end: float, timeout: float, record: RunRecord | None,
              expected_fields: list[str] | None = None, output_times: list[float] | None = None) -> RunRecord:
    rec = record or RunRecord(run_id=uuid.uuid4().hex[:12])
    prj, rundir = Path(prj).resolve(), Path(rundir).resolve()  # OGS runs in the build folder
    rundir.mkdir(parents=True, exist_ok=True)
    rec.rundir, rec.status = str(rundir), "running"
    logf = rundir / rec.log
    t0 = time.time()
    with open(logf, "w") as lf:
        proc = subprocess.Popen([str(ogs_executable()), "-o", str(rundir), prj.name], cwd=prj.parent,
                                stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        timed_out = too_large = cancelled = False
        next_size = t0 + SIZE_POLL
        while proc.poll() is None:
            time.sleep(0.2)
            now = time.time()
            rec.seconds = now - t0
            if rec.cancelled:
                _kill(proc)
                cancelled = True
                break
            if rec.seconds > timeout:
                _kill(proc)
                timed_out = True
                break
            if now >= next_size:  # output folder (with ogs.log) watched while OGS writes
                next_size = now + SIZE_POLL
                if _dir_size(rundir) > MAX_OUTPUT_BYTES:
                    _kill(proc)
                    too_large = True
                    break
            if int(rec.seconds * 5) % 10 == 0:
                rec.progress = _progress(logf.read_text(errors="replace"), t_end)
        proc.wait()
    rec.seconds = round(time.time() - t0, 2)
    rec.returncode = proc.returncode
    text = logf.read_text(errors="replace")
    rec.progress = _progress(text, t_end)
    if cancelled:
        rec.status = "failed"
        rec.failure = {"code": "cancelled", "message": "the model was changed while this run was going, so it was stopped",
                       "fix": "call run for the current model", "line": ""}
        return rec
    if timed_out:
        rec.status = "failed"
        rec.failure = {"code": "timeout", "message": f"the run took longer than {timeout:.0f} s",
                       "fix": "use a coarser mesh or fewer time steps", "line": ""}
        return rec
    if too_large or _dir_size(rundir) > MAX_OUTPUT_BYTES:
        rec.status, rec.failure = "failed", {"code": "output_too_large", "message": "the output grew larger than "
                                             f"{MAX_OUTPUT_BYTES / 1e9:g} GB" + (" and the run was stopped" if too_large else ""),
                                             "fix": "write fewer output times or use a coarser mesh", "line": ""}
        return rec
    pvds = sorted(rundir.glob("*.pvd"))
    if pvds:
        rec.outputs = read_pvd(pvds[0])
    if proc.returncode != 0:
        rec.status, rec.failure = "failed", classify(text)
        return rec
    rec.reached_end = bool(rec.outputs) and rec.outputs[-1][0] >= t_end * (1 - 1e-9)
    rec.finite, problem = _check_outputs(rundir, rec.outputs, expected_fields, output_times)
    if not rec.reached_end:
        rec.status, rec.failure = "failed", {"code": "end_not_reached", "message": "the last output is before the end time",
                                             "fix": "report this run", "line": ""}
    elif not rec.finite:
        rec.status, rec.failure = "failed", {"code": "not_finite", "message": f"results contain NaN or infinity ({problem})",
                                             "fix": "check material values and time steps", "line": ""}
    elif problem:
        rec.status, rec.failure = "failed", {"code": "invalid_output", "message": f"the output is incomplete: {problem}",
                                             "fix": "report this run", "line": ""}
    else:
        rec.status = "succeeded"
    return rec


def _check_outputs(rundir: Path, outputs, expected_fields=None, output_times=None) -> tuple[bool, str | None]:
    """Every output file: values finite, expected fields present; every requested time written.

    Returns (finite, first problem or None). finite is False only for NaN or infinity."""
    import pyvista as pv
    missing_field = None
    for t, fn in outputs:
        try:
            m = pv.read(rundir / fn)
        except Exception as e:  # unreadable file
            return True, f"output file {fn} at t = {t:g} s cannot be read ({type(e).__name__})"
        for data in (m.point_data, m.cell_data):
            for k in data:
                a = np.asarray(data[k])
                if np.issubdtype(a.dtype, np.number) and not np.all(np.isfinite(a)):
                    return False, f"'{k}' at t = {t:g} s"
        if missing_field is None:
            for f in expected_fields or []:
                if f not in m.point_data:
                    missing_field = f"field '{f}' is missing at t = {t:g} s"
                    break
    if missing_field:
        return True, missing_field
    written = [t for t, _ in outputs]
    for want in output_times or []:
        if not any(abs(t - want) <= 1e-9 * max(1.0, abs(want)) for t in written):
            return True, f"no output at the requested time {want:g} s"
    return True, None


class Jobs:
    """Background runs addressed by job id (run returns at once; run_status reports progress)."""

    def __init__(self):
        self._jobs: dict[str, tuple[threading.Thread, RunRecord]] = {}

    def submit(self, prj: Path, rundir: Path, t_end: float, timeout: float = DEFAULT_TIMEOUT,
               on_done=None, expected_fields: list[str] | None = None,
               output_times: list[float] | None = None) -> str:
        rec = RunRecord(run_id=uuid.uuid4().hex[:12])

        def work():
            try:
                expect = {k: v for k, v in (("expected_fields", expected_fields), ("output_times", output_times)) if v}
                run_ogs(prj, rundir, t_end, timeout, rec, **expect)
            except Exception as e:  # never lose a job silently
                rec.status, rec.failure = "failed", {"code": "harness_error", "message": repr(e)[:300],
                                                     "fix": "report this run", "line": ""}
            if on_done:
                on_done(rec)

        th = threading.Thread(target=work, daemon=True)
        self._jobs[rec.run_id] = (th, rec)
        th.start()
        return rec.run_id

    def cancel(self, job_id: str):
        """Stop a queued or running job (its process group is killed at the next poll)."""
        if job_id in self._jobs:
            self._jobs[job_id][1].cancelled = True

    def status(self, job_id: str) -> RunRecord:
        return self._jobs[job_id][1]

    def wait(self, job_id: str, timeout: float | None = None) -> RunRecord:
        th, rec = self._jobs[job_id]
        th.join(timeout)
        return rec
