"""Genera con Higgsfield: colpi AI dentro la ripresa vera (Higgsfield e Claude finti)."""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from autocut import vfx

from .test_editor_server import make_client

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="serve ffmpeg")


def _clip(path, size="1080x1920", dur=4, color="testsrc2"):
    sep = "" if color.endswith(":") else "="
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"{color}{sep}s={size}:r=30:d={dur}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )  # fmt: skip
    return path


def _masks(folder, n=40):
    from PIL import Image, ImageDraw

    folder.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):  # persona = rettangolo nero al centro (metà risoluzione)
        im = Image.new("L", (540, 960), 255)
        ImageDraw.Draw(im).rectangle((170, 300, 370, 900), fill=0)
        im.save(folder / f"{i:05d}.jpg")
    (folder / "done.txt").write_text(str(n))
    return folder, n


class FakeAgent:
    def __init__(self, plan=None, review=None):
        self.calls = []
        self.plan = plan or {
            "prompt": "Real footage. Add a small dragon behind the man. Keep him identical. "
            "No speech, no music.",
            "protect_person": True,
            "reference_image": {"prompt": "a dragon head, grey background", "why": "aspetto"},
            "risk": "poco spazio",
            "title": "Dragone",
        }
        self.review = review or {"verdict": "ok", "issues": [], "fix_prompt": ""}

    def ask_skill(self, prompt):
        self.calls.append(prompt)
        return self.plan if "Job: plan" in prompt else self.review


def _tl(src):
    cam = SimpleNamespace(
        path_hint=str(src), duration_ms=10000,
        video=SimpleNamespace(display_width=1080, display_height=1920),
    )  # fmt: skip
    words = [SimpleNamespace(kind="word", text="ciao", start_ms=200)]
    return SimpleNamespace(sources=SimpleNamespace(camera=cam), words=words)


def test_add_validates_and_numbers(tmp_path):
    s = vfx.add(tmp_path, start_ms=1000, dur_ms=9000, request=" drago ", camera_ms=10000)
    assert s.id == "vfx_001" and s.dur_ms == vfx.MAX_EFFECT_MS and s.request == "drago"
    assert vfx.add(tmp_path, start_ms=0, dur_ms=1000, request="x", camera_ms=10000).id == "vfx_002"
    with pytest.raises(vfx.VfxError):
        vfx.add(
            tmp_path, start_ms=7000, dur_ms=1000, request="x", camera_ms=10000
        )  # < 4 s alla fine
    with pytest.raises(vfx.VfxError):
        vfx.add(tmp_path, start_ms=0, dur_ms=1000, request="  ", camera_ms=10000)


def test_video_args_keep_audio_off_and_use_the_real_clip(tmp_path):
    args = vfx.video_args("draft", "p", tmp_path / "c.mp4", None, "9:16")
    assert args[0] == "seedance_2_0" and "480p" in args
    assert args[args.index("--generate_audio") + 1] == "false"
    assert args[args.index("--duration") + 1] == "4"
    assert args[args.index("--video-references") + 1].endswith("c.mp4")
    assert vfx.result_url({"jobs": [{"results": {"url": "https://x/y.mp4"}}]}) == "https://x/y.mp4"


@needs_ffmpeg
def test_run_shot_end_to_end_with_fakes(tmp_path):
    raw = _clip(tmp_path / "raw.mp4")
    source = _clip(tmp_path / "source.mp4")
    gen_src = _clip(tmp_path / "gen.mp4", size="480x854", color="smptebars")
    calls = []

    def hf(args):
        calls.append(args)
        if args[:2] == ["generate", "cost"]:
            return {"credits": 4}
        if vfx.REF_MODEL in args:
            return {"result_url": "https://cdn/ref.png"}
        return {"jobs": [{"result_url": "https://cdn/gen.mp4"}]}

    def fetch(url, dest):
        shutil.copy(gen_src if url.endswith(".mp4") else _png(tmp_path / "r.png"), dest)

    s = vfx.add(
        tmp_path, start_ms=100, dur_ms=1000, request="drago dietro di me", quality="draft",
        camera_ms=10000,
    )  # fmt: skip
    agent = FakeAgent()
    out = vfx.run_shot(
        tmp_path, s.id, tl=_tl(raw), agent=agent, hf=hf, fetch=fetch,
        masks_fn=lambda src: _masks(tmp_path / "m"), source_fn=lambda *a, **k: source,
    )  # fmt: skip
    assert out.status == "done", out.error
    assert out.review["verdict"] == "ok" and out.title == "Dragone"
    assert out.credits == pytest.approx(4.12)
    d = vfx.shot_dir(tmp_path, s.id)
    assert (d / out.final).is_file() and (d / out.sheet).is_file() and (d / "input.mp4").is_file()
    create = next(a for a in calls if a[:2] == ["generate", "create"] and "seedance_2_0" in a)
    assert create[create.index("--generate_audio") + 1] == "false"
    assert "--image-references" in create  # il riferimento del drago va a Seedance
    assert "ciao" in agent.calls[0]  # il parlato di quei secondi arriva alla skill
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_frames,width,height", "-of", "csv=p=0", str(d / out.final)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert frames == "1080,1920,30"


def _png(path):
    from PIL import Image

    Image.new("RGB", (8, 8), "green").save(path)
    return path


@needs_ffmpeg
def test_cost_over_the_cap_stops_before_generating(tmp_path):
    raw = _clip(tmp_path / "raw.mp4", dur=4)
    s = vfx.add(tmp_path, start_ms=0, dur_ms=1000, request="drago", camera_ms=10000)
    created = []

    def hf(args):
        if args[:2] == ["generate", "cost"]:
            return {"credits": 50}
        created.append(args)
        return {}

    agent = FakeAgent(plan={**FakeAgent().plan, "reference_image": None})
    out = vfx.run_shot(tmp_path, s.id, tl=_tl(raw), agent=agent, hf=hf,
                       source_fn=lambda *a, **k: raw)  # fmt: skip
    assert out.status == "error" and "tetto" in out.error and not created


@needs_ffmpeg
def test_bake_puts_active_shots_inside_the_camera_extract(tmp_path):
    source = _clip(tmp_path / "src.mp4", dur=4)
    s = vfx.add(tmp_path, start_ms=1000, dur_ms=1000, request="x", camera_ms=10000)
    d = vfx.shot_dir(tmp_path, s.id)
    d.mkdir(parents=True)
    _clip(d / "final-1.mp4", dur=1, color="color=c=red:")
    vfx.edit(tmp_path, s.id, final="final-1.mp4", status="done")
    assert vfx.bake(tmp_path, source, 0, 4000) == source  # non attiva: niente da fare
    vfx.edit(tmp_path, s.id, enabled=True)
    baked = vfx.bake(tmp_path, source, 0, 4000)
    assert baked != source and baked.is_file()
    assert vfx.bake(tmp_path, source, 0, 4000) == baked  # cache
    assert vfx.bake(tmp_path, source, 5000, 9000) == source  # fuori dalla finestra


def test_api_create_enable_delete(tmp_path):
    ran = []
    c, pdir = make_client(tmp_path, vfx_runner=lambda p, sid: ran.append(sid))
    p = c.post("/api/vfx", json={"start_ms": 0, "dur_ms": 2000, "request": "drago"}).json()
    shot = p["vfx"]["shots"][0]
    assert ran == [shot["id"]] and shot["status"] == "running" and p["vfx"]["max_ms"] == 3000
    assert (
        c.post("/api/vfx", json={"start_ms": 0, "dur_ms": 2000, "request": "x"}).status_code == 409
    )
    assert (
        c.post(f"/api/vfx/{shot['id']}/enable", json={"enabled": True}).status_code == 400
    )  # non pronta
    vfx.edit(pdir, shot["id"], status="done", final="final-1.mp4")
    p = c.post(f"/api/vfx/{shot['id']}/enable", json={"enabled": True}).json()
    assert p["vfx"]["shots"][0]["enabled"] and p["vfx"]["shots"][0]["final_url"].endswith(
        "final-1.mp4"
    )
    assert c.get(f"/media/vfx/{shot['id']}/..%2Ftimeline.json").status_code == 404
    vfx.shot_dir(pdir, shot["id"]).mkdir(parents=True, exist_ok=True)
    (vfx.shot_dir(pdir, shot["id"]) / "final-1.mp4").write_bytes(b"x")
    p = c.post(f"/api/vfx/{shot['id']}/delete").json()
    assert p["vfx"]["shots"] == []
    trash = list((pdir / "work" / "vfx" / vfx.TRASH_DIR).glob(f"{shot['id']}-*"))
    assert len(trash) == 1 and (trash[0] / "final-1.mp4").is_file()  # nel cestino, non perso
    assert (trash[0] / "shot.json").is_file()


def test_effect_end_finds_when_the_ai_element_leaves():
    import numpy as np

    src = [np.full((16, 9, 3), 100, np.uint8) for _ in range(20)]
    gen = [x.copy() for x in src]
    for j in range(5, 14):  # l'elemento AI è in scena dal fotogramma 5 al 13
        gen[j][:6] = 250
    one, zero = np.ones(3, np.float32), np.zeros(3, np.float32)
    assert vfx.effect_end(src, gen, None, 0, one, zero) == 13
    assert vfx.effect_end(src, [x.copy() for x in src], None, 0, one, zero) is None


@needs_ffmpeg
def test_starter_quality_upscales_the_ai_clip_before_compositing(tmp_path):
    raw = _clip(tmp_path / "raw.mp4")
    source = _clip(tmp_path / "source.mp4")
    gen_src = _clip(tmp_path / "gen.mp4", size="720x1280", color="smptebars")
    calls = []

    def hf(args):
        calls.append(args)
        if args[:2] == ["generate", "cost"]:
            return {"credits": 2 if vfx.UPSCALE_JOB in args else 10}
        if vfx.UPSCALE_JOB in args:
            return {"result_url": "https://cdn/gen-1080.mp4"}
        return {"result_url": "https://cdn/gen.mp4"}

    plan = {**FakeAgent().plan, "reference_image": None}
    s = vfx.add(
        tmp_path, start_ms=0, dur_ms=1000, request="drago", quality="hd720", camera_ms=10000
    )
    out = vfx.run_shot(
        tmp_path, s.id, tl=_tl(raw), agent=FakeAgent(plan=plan), hf=hf,
        fetch=lambda url, dest: shutil.copy(gen_src, dest),
        masks_fn=lambda src: _masks(tmp_path / f"m-{src.stem}"), source_fn=lambda *a, **k: source,
    )  # fmt: skip
    assert out.status == "done", out.error
    up = next(a for a in calls if a[:2] == ["generate", "create"] and vfx.UPSCALE_JOB in a)
    assert up[up.index("--preset") + 1] == "aigc" and up[up.index("--resolution") + 1] == "1080p"
    assert out.plan["upscaled"] is True and out.credits == pytest.approx(12)
    assert (vfx.shot_dir(tmp_path, s.id) / "gen-1-1080.mp4").is_file()


def _faces(n=200):
    return [[0.35, 0.2, 0.3, 0.15]] * n  # volto al centro, in alto (frazioni dell'immagine)


@needs_ffmpeg
def test_auto_routes_an_outfit_change_to_genjutsu_with_the_real_head(tmp_path):
    raw = _clip(tmp_path / "raw.mp4")
    source = _clip(tmp_path / "source.mp4")
    gen_src = _clip(tmp_path / "gen.mp4", size="720x1280", color="smptebars")
    calls = []

    def hf(args):
        calls.append(args)
        if args[:2] == ["generate", "cost"]:
            return {"credits": 2 if vfx.UPSCALE_JOB in args else 8}
        if "gpt_image_2_6" in args:
            return {"result_url": "https://cdn/jacket.png"}
        return {"result_url": "https://cdn/out.mp4"}

    def fetch(url, dest):
        shutil.copy(gen_src if url.endswith(".mp4") else _png(tmp_path / "j.png"), dest)

    plan = {
        **FakeAgent().plan,
        "recipe": "outfit",
        "prompt": "TASK\nEdit Video 1. Replace the grey fleece with the leather jacket in Image 1.",
        "reference_image": {"prompt": "black leather biker jacket, ghost mannequin", "why": "x"},
    }
    agent = FakeAgent(plan=plan)
    s = vfx.add(tmp_path, start_ms=0, dur_ms=2000, request="giacca di pelle", camera_ms=10000)
    out = vfx.run_shot(
        tmp_path, s.id, tl=_tl(raw), agent=agent, hf=hf, fetch=fetch,
        masks_fn=lambda src: _masks(tmp_path / f"m-{src.stem}", 130),
        source_fn=lambda *a, **k: source, faces_fn=lambda src: _faces(),
    )  # fmt: skip
    assert out.status == "done", out.error
    assert out.recipe == "outfit" and out.plan["protect_mode"] == "head"
    create = next(a for a in calls if a[:2] == ["generate", "create"] and vfx.GENJUTSU_JOB in a)
    assert create[create.index("--image-references") + 1].endswith("ref.png")
    assert "--generate_audio" not in create and "--start-image" not in create
    assert any(vfx.UPSCALE_JOB in a for a in calls if a[:2] == ["generate", "create"])
    assert out.credits == pytest.approx(10.5)  # 8 Genjutsu + 2 upscale + 0.5 foto della giacca
    assert out.dur_ms == 2000  # il cambio vestiti non si allunga come un effetto
    assert "AUTOMATICA" in agent.calls[0] and "outfit" in agent.calls[0]


@needs_ffmpeg
def test_claude_asks_before_spending_then_uses_the_answers(tmp_path):
    raw = _clip(tmp_path / "raw.mp4")
    created = []

    def hf(args):
        if args[:2] == ["generate", "create"]:
            created.append(args)
        return {"credits": 4}

    agent = FakeAgent(plan={**FakeAgent().plan, "questions": ["Che giacca: colore e materiale?"]})
    s = vfx.add(tmp_path, start_ms=0, dur_ms=1000, request="cambiami la giacca", camera_ms=10000)
    out = vfx.run_shot(tmp_path, s.id, tl=_tl(raw), agent=agent, hf=hf,
                       source_fn=lambda *a, **k: raw)  # fmt: skip
    assert out.status == "asking" and out.plan["questions"] == ["Che giacca: colore e materiale?"]
    assert not created  # nessun credito speso prima delle risposte
    again = vfx.answer(tmp_path, s.id, ["pelle nera da motociclista"])
    assert again.status == "running" and again.asked
    assert again.answers == ["Che giacca: colore e materiale? -> pelle nera da motociclista"]
    vfx.run_shot(tmp_path, s.id, tl=_tl(raw), agent=agent, hf=hf, source_fn=lambda *a, **k: raw)
    assert "pelle nera da motociclista" in agent.calls[-1]
    assert "NON fare altre domande" in agent.calls[-1]
    assert vfx.get(tmp_path, s.id).status != "asking"  # le domande non si ripetono


def test_head_alpha_keeps_the_head_and_not_the_shoulders():
    import numpy as np

    person = np.ones((320, 180, 1), np.float32)
    a = vfx.head_alpha([0.35, 0.2, 0.3, 0.15], person, 180, 320)
    assert a[int(0.27 * 320), 90, 0] > 0.9  # centro del volto
    assert a[int(0.6 * 320), 90, 0] < 0.05  # petto: lì c'è il vestito nuovo
    assert a[int(0.27 * 320), 5, 0] < 0.05  # lato dell'inquadratura


def test_api_answer_restarts_the_shot(tmp_path):
    ran = []
    c, pdir = make_client(tmp_path, vfx_runner=lambda p, sid: ran.append(sid))
    sid = c.post("/api/vfx", json={"start_ms": 0, "dur_ms": 2000, "request": "giacca"}).json()[
        "vfx"
    ]["shots"][0]["id"]
    vfx.edit(pdir, sid, status="done")  # il runner finto non lo fa
    assert c.post(f"/api/vfx/{sid}/answer", json={"answers": []}).status_code == 400  # non chiede
    vfx.edit(pdir, sid, status="asking", plan={"questions": ["Che colore?"]})
    p = c.post(f"/api/vfx/{sid}/answer", json={"answers": ["nera"]}).json()
    shot = p["vfx"]["shots"][0]
    assert shot["status"] == "running" and shot["asked"] and ran == [sid, sid]
    assert set(p["vfx"]["recipes"]) == {"effect", "outfit", "transform"}


@needs_ffmpeg
def test_a_job_blocked_by_the_filter_is_rewritten_once_without_protected_names(tmp_path):
    raw = _clip(tmp_path / "raw.mp4")
    created = []

    def hf(args):
        if args[:2] == ["generate", "cost"]:
            return {"credits": 4}
        created.append(args)
        raise vfx.VfxError(f"Generazione {vfx.BLOCKED}: nome protetto. Credito restituito.")

    plan = {**FakeAgent().plan, "recipe": "transform", "prompt": "Strictly edit Video 1: " * 4}
    agent = FakeAgent(plan=plan)
    s = vfx.add(tmp_path, start_ms=0, dur_ms=3000, request="faccia di Hulk", camera_ms=10000)
    out = vfx.run_shot(tmp_path, s.id, tl=_tl(raw), agent=agent, hf=hf,
                       source_fn=lambda *a, **k: raw)  # fmt: skip
    assert out.status == "error" and vfx.BLOCKED in (out.error or "")
    assert len(agent.calls) == 2 and "BLOCCATO" in agent.calls[1]  # riscritto una volta sola
    assert len(created) == 4  # per giro: Seedream bloccato + ripiego Soul; due giri, poi stop
    assert "AUTOMATICA" in agent.calls[0] and "MAI nomi" in agent.calls[0]
