"""B-roll e voice-over: caricamento, modifica, Annulla, cucitura ffmpeg e piano per Remotion."""

import json
import shutil
import subprocess

import pytest

from autocut import broll
from autocut.render.preview import Piece, to_out

from .test_editor_server import make_client

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="serve ffmpeg")


def _ff(*args):
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True)


@pytest.fixture
def media(tmp_path):
    """Una foto, un video e un audio veri (minuscoli)."""
    d = tmp_path / "media"
    d.mkdir()
    _ff("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(d / "foto.png"))
    _ff("-f", "lavfi", "-i", "testsrc=s=96x54:r=30:d=2", "-pix_fmt", "yuv420p", str(d / "clip.mp4"))
    _ff("-f", "lavfi", "-i", "sine=f=440:d=2", str(d / "voce.wav"))
    return d


def _upload(c, path, **q):
    return c.post("/api/broll/upload", params={"name": path.name, **q}, content=path.read_bytes())


@needs_ffmpeg
def test_upload_edit_undo_and_serve(tmp_path, media):
    c, pdir = make_client(tmp_path)
    out = _upload(c, media / "clip.mp4", at_ms=1200)
    assert out.status_code == 200, out.text
    b = out.json()["broll"]
    clip = b["clips"][0]
    assert clip["kind"] == "video" and clip["at_ms"] == 1200 and clip["media_ms"] >= 1900
    assert clip["duration_ms"] == 4000 or clip["duration_ms"] <= clip["media_ms"]
    assert c.get(clip["url"]).status_code == 200
    # foto + audio
    assert _upload(c, media / "foto.png", at_ms=0).json()["broll"]["clips"][1]["kind"] == "image"
    v = _upload(c, media / "voce.wav", at_ms=500, kind="voice").json()["broll"]["voices"][0]
    assert v["mute_camera"] and v["duration_ms"] >= 1900 and c.get(v["url"]).status_code == 200
    # modifica
    r = c.post(f"/api/broll/{clip['id']}", json={"fields": {"at_ms": 2000, "duration_ms": 1500}})
    assert r.json()["broll"]["clips"][0]["at_ms"] == 2000
    r = c.post(f"/api/broll/{v['id']}", json={"fields": {"gain_db": -6, "mute_camera": False}})
    assert r.json()["broll"]["voices"][0]["gain_db"] == -6
    for bad in ({"duration_ms": 10}, {"file": "x"}):
        assert c.post(f"/api/broll/{clip['id']}", json={"fields": bad}).status_code == 400
    # elimina e Annulla: il file resta, quindi torna tutto com'era
    r = c.post(f"/api/broll/{clip['id']}/delete")
    assert [x["id"] for x in r.json()["broll"]["clips"]] == ["br_0002"]
    c.post("/api/history/undo")
    ids = [x["id"] for x in c.get("/api/project").json()["broll"]["clips"]]
    assert "br_0001" in ids
    assert c.get("/media/broll/broll/..%2Fbroll.json").status_code == 404
    assert c.get("/media/broll/altro/x.png").status_code == 404


@needs_ffmpeg
def test_upload_rejects_bad_files(tmp_path, media):
    c, pdir = make_client(tmp_path)
    assert c.post("/api/broll/upload", params={"name": "x.exe"}, content=b"abc").status_code == 400
    assert c.post("/api/broll/upload", params={"name": "x.mp4"}, content=b"").status_code == 400
    fake = c.post("/api/broll/upload", params={"name": "x.mp4"}, content=b"non e' un video")
    assert fake.status_code == 400
    # audio nel B-roll e foto come voice-over: messaggi chiari
    assert _upload(c, media / "voce.wav").status_code == 400
    assert _upload(c, media / "foto.png", kind="voice").status_code == 400
    assert not list((pdir / "work" / "broll" / "_incoming").glob("*"))  # nulla lasciato a metà
    assert broll.load(pdir).clips == []


def test_safe_name_blocks_paths():
    assert broll.safe_name("../../etc/passwd.mp4") == "passwd.mp4"
    assert broll.safe_name("a b\\c d.MOV") == "c_d.mov"


@needs_ffmpeg
def test_bake_puts_broll_over_the_camera_and_keeps_audio(tmp_path, media):
    pdir = tmp_path / "p"
    (pdir / "work").mkdir(parents=True)
    src = pdir / "work" / "source.mp4"
    _ff("-f", "lavfi", "-i", "testsrc=s=108x192:r=30:d=3", "-f", "lavfi", "-i", "sine=f=300:d=3",
        "-pix_fmt", "yuv420p", "-shortest", str(src))  # fmt: skip
    clip = broll.add_clip(pdir, _copy(media / "foto.png", tmp_path), "foto.png", 1000)
    broll.edit(pdir, clip.id, {"duration_ms": 1000})
    assert broll.bake(pdir, src, 0, 3000) != src
    out = broll.bake(pdir, src, 0, 3000)
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
         "-of", "json", str(out)], capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    streams = json.loads(info)["streams"]
    assert {"codec_type": "video", "width": 108, "height": 192} in streams  # stesse misure
    assert any(s["codec_type"] == "audio" for s in streams)  # la voce della ripresa resta
    # il pixel nel punto del B-roll è rosso, fuori no
    def pixel(t):
        from PIL import Image

        png = tmp_path / f"px{t}.png"
        _ff("-ss", str(t), "-i", str(out), "-frames:v", "1", str(png))
        return Image.open(png).convert("RGB").getpixel((54, 96))

    r, g, b = pixel(1.5)
    assert r > 200 and g < 60 and b < 60
    assert pixel(0.3) != (r, g, b)
    # senza B-roll nella finestra l'estratto resta quello originale
    assert broll.bake(pdir, src, 2500, 3000) == src
    broll.edit(pdir, clip.id, {"enabled": False})
    assert broll.bake(pdir, src, 0, 3000) == src


def _copy(path, tmp_path):
    dest = tmp_path / ("in_" + path.name)
    shutil.copy(path, dest)
    return dest


@needs_ffmpeg
def test_render_voices_maps_to_the_edited_timeline(tmp_path, media):
    pdir = tmp_path / "p"
    (pdir / "work").mkdir(parents=True)
    v = broll.add_voice(pdir, _copy(media / "voce.wav", tmp_path), "voce.wav", 3000)
    pieces = [Piece(0, 2000, 0), Piece(4000, 6000, 2000)]  # 2-4 s tolti
    out = broll.render_voices(pdir, pdir / "work", to_out, pieces)
    assert out[0]["from_ms"] == 2000 and out[0]["mute_camera"] and out[0]["volume"] == 1.0
    assert (pdir / "work" / out[0]["src"]).is_file()
    # col guadagno positivo l'aumento lo fa ffmpeg (Remotion non supera 1)
    broll.edit(pdir, v.id, {"gain_db": 6})
    boosted = broll.render_voices(pdir, pdir / "work", to_out, pieces)[0]
    assert boosted["volume"] == 1.0 and "+6.0dB" in boosted["src"]
    assert (pdir / "work" / boosted["src"]).is_file()
    broll.edit(pdir, v.id, {"gain_db": -6, "enabled": True})
    quiet = broll.render_voices(pdir, pdir / "work", to_out, pieces)[0]
    assert quiet["volume"] == pytest.approx(0.501, abs=0.01)
    broll.edit(pdir, v.id, {"enabled": False})
    assert broll.render_voices(pdir, pdir / "work", to_out, pieces) == []
