"""Runner output contract (Codex P1 review, findings 6 and 7): every output is checked, expected fields and times
must be present, the output size is watched during the run, and the direct-solver retry stays inside the budget."""
import os
import stat
import sys
import time
from pathlib import Path

import numpy as np
import pyvista as pv

from thmstudio import runner

FAKE_COPY = """#!{py}
import shutil, sys, os
out = sys.argv[sys.argv.index("-o") + 1]
for f in os.listdir({tpl!r}):
    shutil.copy(os.path.join({tpl!r}, f), out)
"""

FAKE_WRITER = """#!{py}
import sys, time
out = sys.argv[sys.argv.index("-o") + 1]
with open(out + "/big.bin", "wb") as f:
    while True:
        f.write(b"0" * 100000)
        f.flush()
        time.sleep(0.01)
"""


def _fake(tmp_path, body, monkeypatch):
    exe = tmp_path / "fake_ogs"
    exe.write_text(body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(runner, "ogs_executable", lambda: exe)
    prj = tmp_path / "build" / "m.prj"
    prj.parent.mkdir()
    prj.write_text("<OpenGeoSysProject/>")
    return prj


def _outputs(tpl: Path, times, fields=("temperature",), nan_at=None):
    tpl.mkdir()
    rows = []
    for i, t in enumerate(times):
        m = pv.ImageData(dimensions=(3, 3, 1)).cast_to_unstructured_grid()
        for f in fields:
            v = np.full(m.n_points, 1.0)
            if nan_at is not None and i == nan_at:
                v[1] = np.nan
            m.point_data[f] = v
        fn = f"m_ts_{i}_t_{t:f}.vtu"
        m.save(tpl / fn)
        rows.append(f'<DataSet timestep="{t}" group="" part="0" file="{fn}"/>')
    (tpl / "m.pvd").write_text('<?xml version="1.0"?>\n<VTKFile type="Collection" version="0.1"><Collection>'
                               + "".join(rows) + "</Collection></VTKFile>")


def _run(tmp_path, monkeypatch, **kw):
    prj = _fake(tmp_path, FAKE_COPY.format(py=sys.executable, tpl=str(tmp_path / "tpl")), monkeypatch)
    return runner.run_ogs(prj, tmp_path / "run", 2.0, timeout=60, **kw)


def test_complete_output_succeeds(tmp_path, monkeypatch):
    _outputs(tmp_path / "tpl", [0.0, 1.0, 2.0])
    rec = _run(tmp_path, monkeypatch, expected_fields=["temperature"], output_times=[1.0, 2.0])
    assert rec.status == "succeeded" and rec.finite and rec.reached_end


def test_nan_in_intermediate_output_fails(tmp_path, monkeypatch):
    _outputs(tmp_path / "tpl", [0.0, 1.0, 2.0], nan_at=1)
    rec = _run(tmp_path, monkeypatch)
    assert rec.status == "failed" and rec.failure["code"] == "not_finite" and not rec.finite
    assert "t = 1 s" in rec.failure["message"]


def test_missing_expected_field_fails(tmp_path, monkeypatch):
    _outputs(tmp_path / "tpl", [0.0, 1.0, 2.0], fields=("pressure",))
    rec = _run(tmp_path, monkeypatch, expected_fields=["temperature"])
    assert rec.status == "failed" and rec.failure["code"] == "invalid_output"
    assert "temperature" in rec.failure["message"]


def test_missing_requested_time_fails(tmp_path, monkeypatch):
    _outputs(tmp_path / "tpl", [0.0, 2.0])
    rec = _run(tmp_path, monkeypatch, output_times=[1.0])
    assert rec.status == "failed" and rec.failure["code"] == "invalid_output"
    assert "requested time 1 s" in rec.failure["message"]


def test_output_size_is_capped_during_the_run(tmp_path, monkeypatch):
    prj = _fake(tmp_path, FAKE_WRITER.format(py=sys.executable), monkeypatch)
    monkeypatch.setattr(runner, "MAX_OUTPUT_BYTES", 500_000)
    monkeypatch.setattr(runner, "SIZE_POLL", 0.2)
    t0 = time.time()
    rec = runner.run_ogs(prj, tmp_path / "run", 1.0, timeout=60)
    assert rec.status == "failed" and rec.failure["code"] == "output_too_large"
    assert time.time() - t0 < 20  # stopped by the size watch, not by the timeout


def test_direct_retry_uses_the_remaining_budget(tmp_path, monkeypatch):
    prj = tmp_path / "m.prj"
    prj.write_text("<eigen><solver_type>BiCGSTAB</solver_type></eigen>")
    budgets = []

    def fake_once(prj_, rundir, t_end, timeout, record, **kw):
        budgets.append(timeout)
        time.sleep(0.5)
        rec = record or runner.RunRecord(run_id="x")
        rec.status, rec.failure = "failed", {"code": "linear_solver", "line": "solver failed"}
        return rec

    monkeypatch.setattr(runner, "_run_once", fake_once)
    runner.run_ogs(prj, tmp_path / "run", 1.0, timeout=10.0)
    assert len(budgets) == 2 and budgets[0] == 10.0 and budgets[1] <= 10.0 - 0.45


def test_no_retry_when_the_budget_is_spent(tmp_path, monkeypatch):
    prj = tmp_path / "m.prj"
    prj.write_text("<eigen><solver_type>BiCGSTAB</solver_type></eigen>")
    calls = []

    def fake_once(prj_, rundir, t_end, timeout, record, **kw):
        calls.append(timeout)
        time.sleep(1.2)
        rec = record or runner.RunRecord(run_id="x")
        rec.status, rec.failure = "failed", {"code": "linear_solver", "line": ""}
        return rec

    monkeypatch.setattr(runner, "_run_once", fake_once)
    rec = runner.run_ogs(prj, tmp_path / "run", 1.0, timeout=2.0)
    assert len(calls) == 1 and rec.status == "failed"


FAKE_SLOW = """#!{py}
import time
time.sleep(60)
"""


def test_cancelled_job_stops_and_is_not_retried(tmp_path, monkeypatch):  # an edit stops the run of the old model
    prj = _fake(tmp_path, FAKE_SLOW.format(py=sys.executable), monkeypatch)
    jobs = runner.Jobs()
    jid = jobs.submit(prj, tmp_path / "run", 1.0, timeout=30)
    time.sleep(0.5)
    t0 = time.time()
    jobs.cancel(jid)
    rec = jobs.wait(jid, timeout=10)
    assert rec.status == "failed" and rec.failure["code"] == "cancelled" and time.time() - t0 < 5
