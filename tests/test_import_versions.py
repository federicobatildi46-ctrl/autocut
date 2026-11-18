"""Importa un raw dall'editor + Annulla persistente + versioni salvate."""

import json
import os
import time

import pytest

from autocut.editor import importer as imp
from autocut.editor.history import History
from autocut.editor.server import STATE_FILE
from autocut.models.io import read_model
from autocut.models.timeline import Timeline

from .test_editor_server import make_client

VIDEO = b"\x00" * (imp.MIN_BYTES + 10)


def _history(pdir):
    return History(pdir, lambda: read_model(pdir / "timeline.json", Timeline), STATE_FILE)


def _split(c, ms):
    return c.post("/api/cuts", json={"action": "split", "ms": ms})


def test_undo_survives_an_editor_restart(tmp_path):
    c, pdir = make_client(tmp_path)
    assert _split(c, 2000).status_code == 200
    assert c.get("/api/project").json()["summary"]["can_undo"]
    # l'editor si riavvia (es. dopo una modifica di Claude): la cronologia c'è ancora
    h = _history(pdir)
    assert h.can_undo and not h.can_redo
    h.undo()
    assert not (pdir / "cuts.json").exists()  # com'era prima del taglio
    h2 = _history(pdir)
    assert not h2.can_undo and h2.can_redo  # anche «Ripeti» è rimasto
    # un file di cronologia rovinato non ferma l'editor
    (pdir / "work" / "history.json").write_text("{rotto", encoding="utf-8")
    assert not _history(pdir).can_undo


def test_saved_versions_can_be_restored_and_undone(tmp_path):
    c, pdir = make_client(tmp_path)
    _split(c, 1500)
    out = c.post("/api/versions", json={"name": "Prima del taglio"}).json()
    assert [v["name"] for v in out["versions"]] == ["Prima del taglio"]
    vid = out["versions"][0]["id"]
    _split(c, 3000)
    assert len(json.loads((pdir / "cuts.json").read_text(encoding="utf-8"))["splits"]) == 2
    c.post(f"/api/versions/{vid}/restore")
    assert json.loads((pdir / "cuts.json").read_text(encoding="utf-8"))["splits"] == [1500]
    c.post("/api/history/undo")  # il ripristino si può annullare
    assert len(json.loads((pdir / "cuts.json").read_text(encoding="utf-8"))["splits"]) == 2
    assert c.post("/api/versions/v_nonesiste/restore").status_code == 400
    assert c.post("/api/versions/..%2Fx/delete").status_code in (400, 404)
    assert c.post(f"/api/versions/{vid}/delete").json()["versions"] == []


def test_importer_helpers(tmp_path):
    root = tmp_path / "Downloads"
    (root / "sub").mkdir(parents=True)
    old = root / "vecchio.mov"
    old.write_bytes(VIDEO)
    os.utime(old, (time.time() - 500, time.time() - 500))
    (root / "sub" / "nuovo.MP4").write_bytes(VIDEO)
    (root / "icloud.mov").write_bytes(b"x")  # segnaposto
    (root / "note.txt").write_text("no")
    found = imp.candidates([root])
    assert {c["name"] for c in found} == {"vecchio.mov", "nuovo.MP4", "icloud.mov"}
    assert next(c for c in found if c["name"] == "icloud.mov")["placeholder"]
    with pytest.raises(imp.ImportError_):
        imp.check_source(tmp_path / "altro.mov", [root])
    with pytest.raises(imp.ImportError_, match="segnaposto"):
        imp.check_source(root / "icloud.mov", [root])
    assert imp.check_source(old, [root]) == old.resolve()
    (tmp_path / "IMG_0031").mkdir()
    assert imp.project_name_for("IMG 0031.MOV", tmp_path) == "IMG-0031"
    assert imp.project_name_for("IMG_0031.MOV", tmp_path) == "IMG_0031-2"
    # il supervisore cambia progetto e toglie --range
    imp.request_open(tmp_path, "nuovo")
    assert imp.take_open_request(tmp_path) == "nuovo" and imp.take_open_request(tmp_path) is None
    argv = ["py", "-c", "x", "editor", "vecchio", "--range", "1-2", "--port", "9000"]
    assert imp.swap_project(argv, "nuovo") == ["py", "-c", "x", "editor", "nuovo", "--port", "9000"]


def _import_client(tmp_path, calls, **kw):
    root = tmp_path / "Downloads"
    root.mkdir()

    def pipeline(name, video, phase):
        phase("ingest")
        calls.append((name, video))
        phase("transcribe")
        if "rotto" in video.name:
            raise RuntimeError("ELEVENLABS_API_KEY mancante")
        phase("cuts")
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / "timeline.json").write_text("{}", encoding="utf-8")

    c, pdir = make_client(
        tmp_path, import_pipeline=pipeline, import_threaded=False, import_roots=[root],
        repo_root=tmp_path / "repo", **kw,
    )  # fmt: skip
    return c, pdir, root


def test_import_upload_runs_the_premontage(tmp_path):
    calls = []
    c, pdir, _ = _import_client(tmp_path, calls)
    r = c.post("/api/import/upload", params={"name": "Il mio video.MOV"}, content=VIDEO)
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done" and job["project"] == "Il-mio-video"
    name, video = calls[0]
    assert video == tmp_path / "repo" / "raw" / "Il-mio-video" / "Il_mio_video.mov"
    assert video.read_bytes() == VIDEO
    assert c.get("/api/project").json()["import"]["status"] == "done"
    # file non video, segnaposto, errore del premontaggio
    assert c.post("/api/import/upload", params={"name": "a.txt"}, content=VIDEO).status_code == 400
    assert c.post("/api/import/upload", params={"name": "a.mov"}, content=b"x").status_code == 400
    bad = c.post("/api/import/upload", params={"name": "rotto.mov"}, content=VIDEO).json()
    assert bad["status"] == "error" and "ELEVENLABS" in bad["error"]


def test_import_from_download_folder_and_open(tmp_path):
    calls, restarted = [], []
    c, pdir, root = _import_client(tmp_path, calls, restart=lambda: restarted.append(1))
    (root / "iphone.mov").write_bytes(VIDEO)
    items = c.get("/api/import/candidates").json()["items"]
    assert [i["name"] for i in items] == ["iphone.mov"]
    outside = tmp_path / "segreto.mov"
    outside.write_bytes(VIDEO)
    assert c.post("/api/import/from-path", json={"path": str(outside)}).status_code == 400
    r = c.post("/api/import/from-path", json={"path": items[0]["path"]})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert (root / "iphone.mov").exists()  # l'originale non si tocca
    assert calls[0][1].read_bytes() == VIDEO
    assert c.post("/api/import/open", json={"project": "altro"}).status_code == 409
    o = c.post("/api/import/open", json={"project": "iphone"})
    assert o.status_code == 200 and restarted == [1]
    assert imp.take_open_request(tmp_path) == "iphone"
