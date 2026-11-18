"""Copertine della finestra Esporta (Higgsfield finto, nessun credito speso)."""

import base64
import io

import pytest
from PIL import Image

from autocut import covers as cov

from .test_editor_server import make_client


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 120, 80)).save(buf, "PNG")
    return buf.getvalue()


def test_prompts_carry_text_identity_and_layout():
    c = cov.Concept(kicker="ME NE VADO IN", title="THAILANDIA", scene="Krabi at golden hour")
    v = cov.cover_prompt(c, "9:16", has_face=True, has_base=True)
    assert v.startswith("IMAGE REFERENCES: image 1 = CHARACTER 1 face reference")
    assert "Spell exactly: ME NE VADO IN / THAILANDIA" in v and "IDENTITY LOCK" in v
    assert "upper third" in v and "Krabi at golden hour" in v
    h = cov.cover_prompt(c, "16:9", has_face=False, has_base=False)
    assert "LEFT half" in h and "IMAGE REFERENCES" not in h
    assert "clean open sky on the left" in cov.base_prompt(c, "16:9")


def test_generate_uses_soul_then_cover_model(tmp_path):
    calls = []

    def runner(args, prompt):
        calls.append(args)
        if args[2] == cov.SOUL_MODEL:
            return {"id": "job-soul", "result_url": "https://x/soul.png"}
        return {"jobs": [{"id": "job-cover", "result_url": "https://x/cover.png"}]}

    face = tmp_path / "face.png"
    face.write_bytes(_png())
    got = []
    job = cov.generate(
        cov.Concept(title="THAILANDIA"), "16:9", cov.Person(soul_id="soul-1"), face,
        tmp_path / "out.png", runner=runner, download=lambda u, d: got.append(u),
    )  # fmt: skip
    assert job == "job-cover" and got == ["https://x/cover.png"]
    assert calls[0][:3] == ["generate", "create", "text2image_soul_v2"] and "soul-1" in calls[0]
    assert calls[1][2] == "gpt_image_2" and "4k" in calls[1] and "job-soul" in calls[1]
    assert str(face) in calls[1]
    with pytest.raises(cov.CoverError):
        cov.generate(cov.Concept(), "16:9", cov.Person(), None, tmp_path / "x.png", runner=runner)


def test_covers_api_flow(tmp_path):
    calls = []

    def runner(args, prompt):
        calls.append((args, prompt))
        return {"id": "job-1", "result_url": "https://x/c.png"}

    def download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_png())

    c, pdir = make_client(tmp_path, cover_runner=runner, cover_download=download)
    assert c.post("/api/covers/concept", json={}).status_code == 400  # serve uno stile
    c.post("/api/style", json={"id": "premium"})
    c.fake_agent.json_reply = {"kicker": "me ne vado in", "title": "thailandia",
                               "scene": "Krabi, Thailand at golden hour", "topic": "x"}  # fmt: skip
    p = c.post("/api/covers/concept", json={"hint": "voglio vivere in Thailandia"}).json()
    k = p["covers"]["concept"]
    assert (k["kicker"], k["title"], k["topic"]) == ("ME NE VADO IN", "THAILANDIA",
                                                      "voglio vivere in Thailandia")  # fmt: skip
    assert "voglio vivere in Thailandia" in c.fake_agent.calls[-1][1]
    face = "data:image/png;base64," + base64.b64encode(_png()).decode()
    p = c.post("/api/covers/face", json={"data": face}).json()
    assert p["covers"]["person"]["face_url"] == "/media/covers/face.png"
    body = {"concept": {"title": "bangkok"}, "person": {"name": "Fede", "soul_id": "s1"}}
    p = c.post("/api/covers/save", json=body).json()
    assert p["covers"]["concept"]["title"] == "BANGKOK" and p["covers"]["person"]["soul_id"] == "s1"

    p = c.post("/api/covers/generate", json={"ratio": "9:16"}).json()
    assert p["covers"]["job"]["status"] == "done"
    c.post("/api/covers/generate", json={"ratio": "9:16"})
    v = c.get("/api/project").json()["covers"]
    files = [x["file"] for x in v["versions"]["9:16"]]
    assert files == ["premium-9x16-1.png", "premium-9x16-2.png"]
    assert v["chosen"]["9:16"] == 1 and c.get(v["versions"]["9:16"][0]["url"]).status_code == 200
    assert calls[0][0][2] == "text2image_soul_v2" and "BANGKOK" in " ".join(calls[1][0])
    p = c.post("/api/covers/choose", json={"ratio": "9:16", "index": 0}).json()
    assert p["covers"]["chosen"]["9:16"] == 0
    assert c.post("/api/covers/choose", json={"ratio": "9:16", "index": 9}).status_code == 400
    assert c.post("/api/covers/generate", json={"ratio": "4:3"}).status_code == 400
    assert c.get("/media/covers/..%2Fcovers.json").status_code == 404
    c.post("/api/style", json={"id": "viral"})
    assert c.post("/api/covers/generate", json={"ratio": "9:16"}).status_code == 400  # dopo

    def expired(args, prompt):
        raise cov.CoverError("Higgsfield: sessione scaduta. Nel terminale: higgsfield auth login")

    (tmp_path / "b").mkdir()
    c2, _ = make_client(tmp_path / "b", cover_runner=expired, cover_download=download)
    c2.post("/api/style", json={"id": "premium"})
    c2.post("/api/covers/save", json={"concept": {"title": "X"}})
    p = c2.post("/api/covers/generate", json={"ratio": "16:9"}).json()
    assert p["covers"]["job"]["status"] == "error" and "auth login" in p["covers"]["job"]["error"]


def test_viral_cover_is_local_and_vertical_only(tmp_path):
    shots = []

    def still(props, props_path, out, public, *, frame, composition):
        shots.append((props, composition))
        out.write_bytes(_png())
        return out

    def grab(src, ms, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_png())
        return dest

    c, pdir = make_client(tmp_path, cover_still=still, cover_grab=grab)
    c.post("/api/style", json={"id": "viral"})
    p = c.get("/api/project").json()["covers"]
    assert p["mode"] == "viral" and p["ratios"] == ["9:16"] and p["ready"] is True
    c.fake_agent.json_reply = {"kicker": "a sto giro l'avete", "title": "fatta grossa",
                               "sub": "arrivo al locale", "emojis": "🤬⚠️"}  # fmt: skip
    p = c.post("/api/covers/concept", json={"hint": "lite al locale"}).json()["covers"]
    assert (p["concept"]["title"], p["concept"]["sub"]) == ("FATTA GROSSA", "arrivo al locale")
    assert "FRASE D'ESORDIO" in c.fake_agent.calls[-1][1]
    body = {"concept": {"accent": "#FF3B30", "frame_ms": 3300, "emojis": "🔥"}}
    c.post("/api/covers/save", json=body)
    assert c.post("/api/covers/generate", json={"ratio": "16:9"}).status_code == 400
    p = c.post("/api/covers/generate", json={"ratio": "9:16"}).json()["covers"]
    assert p["job"]["status"] == "done", p["job"]
    assert [v["file"] for v in p["versions"]["9:16"]] == ["viral-9x16-1.png"]
    props, comp = shots[-1]
    assert comp == "ViralCover" and props["accent"] == "#FF3B30"
    assert props["frame"] == "render/cover-frame-3300.jpg"
    assert [x["role"] for x in props["lines"]] == ["kicker", "big", "sub"]
    assert props["lines"][1]["text"] == "FATTA GROSSA"
    c.post("/api/covers/save", json={"concept": {"sub": "", "frame_ms": None}})
    p = c.get("/api/project").json()["covers"]
    assert p["concept"]["sub"] == "" and p["concept"]["frame_ms"] is None  # si svuota dal pannello
    assert c.get(p["frame_url"]).status_code == 200


def test_auto_accent_skips_dark_colors():
    dark = {"captions": {"emphasis": {"color": "#794E16"}}}
    assert cov.auto_accent(dark) == "#FFB800"
    assert cov.auto_accent({"captions": {"emphasis": {"color": "#F6B25A"}}}) == "#F6B25A"
