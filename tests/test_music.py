"""Musica di sottofondo dalla libreria Audio Library (YouTube e Claude finti, niente rete)."""

import json

import pytest

from autocut import music as mus
from autocut.render.preview import Piece, to_out

from .test_editor_server import make_client

DESC = """Set a hopeful mood with this free to use cinematic track.

 *FREE DOWNLOAD:* https://links.al/LHs

 *FREE USE & MONETIZATION*
Just copy and paste the following credits into your video description:
────────────
Music: First Snow by Scott Buckley – http://www.scottbuckley.com.au/
License: Creative Commons — Attribution 4.0 International — CC BY 4.0
Free Download / Stream: https://links.al/LHs
Music promoted by Audio Library: https://links.al/youtube
────────────

 *TRACK BREAKDOWN*

0:00 Hushed wintry atmosphere: Great for openers
1:00 Rising hopeful energy: Ideal for motivational reels
2:06 Powerful emotional peak: Perfect for tribute films

 *DISCOVER MORE VIBES*
"""

TITLES = [
    ("AAAAAAAAAAA", 214, "Hopeful Cinematic Music for Motivational Videos  (No Copyright) | Scott Buckley - Golden Hour"),
    ("BBBBBBBBBBB", 150, "Upbeat Corporate Music for Tutorials & Tech Reviews  (Free to Use) | Kevin MacLeod - Move Forward"),
    ("CCCCCCCCCCC", 112, "Cheerful Christmas Music for Winter Montages  (Royalty Free) | Ondrosik - Santa March"),
    ("DDDDDDDDDDD", 180, "Inspiring Motivational Piano for Business Videos  (No Copyright) | KV - Rise"),
    ("EEEEEEEEEEE", 20, "Hopeful Motivational Sting for Intros  (No Copyright) | X - Short"),
]  # fmt: skip


def fake_run(calls):
    def run(args, timeout):
        calls.append(args)
        if "--flat-playlist" in args:
            return "\n".join(f"{i}|{d}|{t}" for i, d, t in TITLES)
        url = args[-1]
        vid = url.rsplit("=", 1)[-1]
        if "--dump-single-json" in args:
            title = next(t for i, _, t in TITLES if i == vid)
            dur = next(d for i, d, _ in TITLES if i == vid)
            return json.dumps({"title": title, "duration": dur, "description": DESC})
        out = args[args.index("-o") + 1].replace("%(ext)s", "m4a")
        with open(out, "wb") as fh:
            fh.write(b"audio")
        return ""

    return run


def test_titles_and_descriptions_are_parsed():
    t = mus.parse_title(TITLES[0][2])
    assert t == {"mood": "Hopeful Cinematic Music", "uses": "Motivational Videos",
                 "artist": "Scott Buckley", "song": "Golden Hour"}  # fmt: skip
    d = mus.parse_description(DESC)
    assert d["credits"].startswith("Music: First Snow by Scott Buckley")
    assert "Music promoted by Audio Library" in d["credits"] and "CC BY 4.0" in d["license"]
    assert [b["at_s"] for b in d["breakdown"]] == [0, 60, 126]


def test_catalog_search_prefers_mood_words_and_skips_short_stings(tmp_path):
    calls = []
    cat = mus.refresh_catalog(tmp_path, fake_run(calls))
    assert len(cat["tracks"]) == 5
    assert mus.refresh_catalog(tmp_path, fake_run(calls)) == cat and len(calls) == 1  # in cache
    ids = [t["id"] for t in mus.search(cat, ["motivational", "hopeful"])]
    assert ids[0] == "AAAAAAAAAAA" and "EEEEEEEEEEE" not in ids  # 20 s: troppo corto


def _ask(prompt):
    if "Decidi il mood" in prompt:
        return {"vibe": "motivante e luminoso", "energy": "medium",
                "keywords": ["motivational", "hopeful", "inspiring"]}  # fmt: skip
    if '"picks"' in prompt:
        return {"picks": [{"id": "DDDDDDDDDDD", "why": "pianoforte che spinge"},
                          {"id": "AAAAAAAAAAA", "why": "cinematico"}, {"id": "ZZZZZZZZZZZ"}]}  # fmt: skip
    return {"sections": [{"id": "DDDDDDDDDDD", "start_s": 60, "section": "energia che sale"}]}


def test_suggest_picks_downloads_and_chooses_a_starting_section(tmp_path):
    calls = []
    vibe, cands = mus.suggest(ask=_ask, context="parlo di crescere", style="viral", seconds=40,
                              root=tmp_path, run=fake_run(calls), lufs=lambda p: -20.0)  # fmt: skip
    assert vibe == "motivante e luminoso"
    assert [c.id for c in cands] == ["DDDDDDDDDDD", "AAAAAAAAAAA"]  # l'id inventato si scarta
    assert cands[0].offset_ms == 60000 and cands[0].section == "energia che sale"
    assert mus.track_path("DDDDDDDDDDD", tmp_path).exists()
    meta = mus.track_meta("DDDDDDDDDDD", tmp_path)
    assert meta["lufs"] == -20.0 and meta["credits"]


def test_render_music_maps_the_range_onto_the_edit_with_level_and_loop(tmp_path):
    root = tmp_path / "lib"
    mus.download("AAAAAAAAAAA", root, fake_run([]), lambda p: -20.0)
    pdir = tmp_path / "p"
    pdir.mkdir()
    data, _ = mus.add_item(mus.MusicFile(), track="AAAAAAAAAAA", start_ms=12000, end_ms=30000,
                           offset_ms=205_000, style="viral")  # fmt: skip
    data, _ = mus.add_item(data, track="AAAAAAAAAAA", muted=True)
    mus.save(pdir, data)
    # due pezzi del raw: 10-20 s e 25-40 s -> montato 0-10 s e 10-25 s
    pieces = [Piece(10000, 20000, 0), Piece(25000, 40000, 10000)]
    out = mus.render_music(pdir, tmp_path / "work", to_out, pieces, "viral",
                           {"voice_lufs": -14, "music_db": -19}, root)  # fmt: skip
    assert len(out) == 1  # la seconda è muta
    m = out[0]
    assert (m["from_ms"], m["dur_ms"]) == (2000, 13000)  # 12 s -> 2 s, 30 s -> 15 s
    assert m["volume"] == pytest.approx(10 ** (-13 / 20), rel=1e-3)  # -14 -19 -(-20) = -13 dB
    assert m["loop"] is True  # parte a 205 s di un brano da 214 s: 9 s non bastano per 13
    assert (tmp_path / "work" / "render" / "music" / "AAAAAAAAAAA.m4a").is_file()
    assert mus.render_music(pdir, tmp_path / "w2", to_out, pieces, "premium", {}, root) == []


def test_editor_music_flow(tmp_path):
    root = tmp_path / "lib"
    c, pdir = make_client(tmp_path, music_root=root, music_run=fake_run([]),
                          music_lufs=lambda p: -18.0, music_threaded=False)  # fmt: skip
    c.fake_agent.ask_json = _ask
    p = c.post("/api/music/suggest", json={"start_ms": 500, "end_ms": 4000}).json()["music"]
    assert p["job"]["status"] == "done", p["job"]
    assert [x["id"] for x in p["suggestion"]["candidates"]] == ["DDDDDDDDDDD", "AAAAAAAAAAA"]
    assert p["suggestion"]["candidates"][0]["track_info"]["url"] == "/media/music/DDDDDDDDDDD.m4a"
    assert p["items"] == []  # proporre non mette niente nel video
    p = c.post("/api/music/item", json={"action": "use", "track": "DDDDDDDDDDD",
                                        "fields": {"offset_ms": 60000}}).json()["music"]  # fmt: skip
    it = p["items"][0]
    assert it["offset_ms"] == 60000 and it["start_ms"] is None and "Scott Buckley" in p["credits"]
    p = c.post("/api/music/item", json={"action": "update", "id": it["id"],
                                        "fields": {"gain_db": -6, "muted": True}}).json()["music"]  # fmt: skip
    assert p["items"][0]["muted"] and p["items"][0]["gain_db"] == -6 and p["credits"] == ""
    assert c.post("/api/music/item", json={"action": "update", "id": it["id"],
                                           "fields": {"id": "x"}}).status_code == 400  # fmt: skip
    assert c.get("/media/music/DDDDDDDDDDD.m4a").status_code == 200
    assert c.get("/media/music/..%2Fcatalog.json").status_code == 404
    r = c.get("/api/music/search?q=christmas").json()
    assert [t["id"] for t in r["results"]] == ["CCCCCCCCCCC"] and r["count"] == 5
    c.post("/api/history/undo")  # l'ultima modifica della musica si annulla come le altre
    assert not mus.load(pdir).items[0].muted
    c.post("/api/music/item", json={"action": "remove", "id": it["id"]})
    assert mus.load(pdir).items == []


def test_premontaggio_picks_music_once_per_style(tmp_path):
    c, pdir = make_client(tmp_path, music_root=tmp_path / "lib", music_run=fake_run([]),
                          music_lufs=lambda p: -18.0, music_threaded=False,
                          auto_music=True)  # fmt: skip
    c.fake_agent.ask_json = _ask
    c.post("/api/style", json={"id": "viral"})
    data = mus.load(pdir)
    assert [i.track for i in data.items] == ["DDDDDDDDDDD"] and data.items[0].origin == "ai"
    assert data.items[0].offset_ms == 60000 and "viral" in data.auto_done
    c.post("/api/music/item", json={"action": "remove", "id": data.items[0].id})
    c.get("/api/project")  # tolta a mano: il premontaggio non la rimette
    assert mus.load(pdir).items == []
