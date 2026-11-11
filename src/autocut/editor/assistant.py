"""«Chiedi a Claude»: la chat dentro l'editor, collegata a Claude Code.

Due modalità:
- edit (Edita il video): selezioni un tratto o un fotogramma nella timeline e chiedi cosa fare.
  Claude Code lavora su COPIE dei file del progetto (pop-up, testi, effetti, filtri, tagli,
  audio) in una cartella sua; l'editor le convalida con gli stessi modelli dei pannelli e le
  applica tutte insieme (un solo Annulla le toglie). Se manca uno strumento lo dice.
- dev (Modifica l'editor): Claude Code lavora sul codice del repo come in una sessione
  normale (niente commit, niente push, niente .env). Prima si fotografa lo stato con git, così
  «Annulla modifiche» rimette i file com'erano; alla fine la pagina si ricarica e, se è
  cambiato il Python, l'editor si riavvia da solo.

La conversazione continua fra un messaggio e l'altro (`claude -p --resume`) e si salva in
claude_chat.json nel progetto, così sopravvive ai ricaricamenti.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import audio_mix as amix
from .. import effects as fx
from .. import filters as flt
from .. import manual_cuts as cutmod
from .. import music as mus
from .. import popups as pops
from .. import text_style as txt
from .agent import AgentError, child_env, extract_json

CHAT_FILE = "claude_chat.json"
STAGING = Path("work") / "claude" / "edit"
ATTACH = Path("work") / "claude" / "attachments"  # screenshot incollati nella chat
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8_000_000
IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
GUIDE = Path(__file__).with_name("assistant_guide.md")
EDIT_TIMEOUT_S = 600
DEV_TIMEOUT_S = 1800
MAX_MESSAGES = 200
# file del progetto che la modalità Edita può cambiare -> modulo che li convalida (load)
EDIT_FILES: dict[str, Any] = {
    pops.POPUPS_FILE: pops,
    fx.EFFECTS_FILE: fx,
    txt.TEXT_FILE: txt,
    flt.FILTERS_FILE: flt,
    cutmod.CUTS_FILE: cutmod,
    amix.AUDIO_FILE: amix,
    mus.MUSIC_FILE: mus,
}
EDIT_TOOLS = ["Read", "Glob", "Grep"]  # le modifiche le autorizza acceptEdits, solo nella cartella
DEV_TOOLS = [
    "Read", "Glob", "Grep", "Skill",
    "Bash(uv run --no-sync pytest:*)", "Bash(uv run --no-sync ruff:*)",
    "Bash(git status:*)", "Bash(git diff:*)",
]  # fmt: skip
NEVER = [
    "Read(./.env)", "Read(**/.env)", "Bash(git push:*)", "Bash(git commit:*)",
    "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(rm:*)",
]  # fmt: skip

Runner = Callable[..., dict[str, Any]]


class AssistantError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _short(path: str) -> str:
    return Path(str(path)).name or str(path)


def describe_tool(name: str, inp: dict[str, Any]) -> str:
    """Cosa sta facendo Claude, in una riga leggibile (dagli eventi stream-json)."""
    if name == "Read":
        return f"Leggo {_short(inp.get('file_path', ''))}"
    if name in ("Edit", "MultiEdit"):
        return f"Modifico {_short(inp.get('file_path', ''))}"
    if name == "Write":
        return f"Scrivo {_short(inp.get('file_path', ''))}"
    if name in ("Grep", "Glob"):
        return f"Cerco «{str(inp.get('pattern', ''))[:50]}»"
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        if "pytest" in cmd:
            return "Eseguo i test"
        if "ruff" in cmd:
            return "Controllo lo stile del codice"
        return f"Eseguo {cmd[:60]}"
    if name == "Skill":
        return f"Uso la skill {inp.get('skill', inp.get('command', ''))}"
    if name in ("TodoWrite", "Task"):
        return "Organizzo il lavoro"
    return name


def run_claude(
    prompt: str,
    *,
    cwd: Path,
    tools: list[str],
    timeout: int,
    resume: str | None = None,
    on_step: Callable[[str], None] = lambda s: None,
    add_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """`claude -p` in streaming: ogni strumento usato diventa un passo; ritorna il risultato."""
    exe = shutil.which("claude")
    if exe is None:
        raise AssistantError("Claude Code (comando `claude`) non trovato nel PATH")
    cmd = [exe, "-p", "--output-format", "stream-json", "--verbose",
           "--permission-mode", "acceptEdits", "--allowedTools", *tools,
           "--disallowedTools", *NEVER]  # fmt: skip
    for d in add_dirs or []:  # cartelle fuori dal lavoro che Claude può leggere (screenshot)
        cmd += ["--add-dir", str(d)]
    if resume:
        cmd += ["--resume", resume]
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=child_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )  # fmt: skip
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(prompt)
    proc.stdin.close()
    killed: list[bool] = []

    def _kill() -> None:
        killed.append(True)
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    result: dict[str, Any] = {}
    session = None
    try:
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            session = ev.get("session_id") or session
            if ev.get("type") == "assistant":
                for part in (ev.get("message") or {}).get("content") or []:
                    if part.get("type") == "tool_use":
                        on_step(describe_tool(part.get("name", ""), part.get("input") or {}))
                    elif part.get("type") == "text" and part.get("text", "").strip():
                        first = part["text"].strip().splitlines()[0]
                        if not first.lstrip().startswith(("{", "```")):
                            on_step(first[:160])
            elif ev.get("type") == "result":
                result = ev
    finally:
        timer.cancel()
        proc.wait()
    if not result:
        err = (proc.stderr.read() if proc.stderr else "").strip()[-400:]
        if killed:
            raise AssistantError(f"Claude non ha finito entro {timeout // 60} minuti")
        raise AssistantError(f"Claude si è fermato: {err or 'nessuna risposta'}")
    return {
        "text": str(result.get("result") or ""),
        "session_id": result.get("session_id") or session,
        "is_error": bool(result.get("is_error")),
        "cost_usd": result.get("total_cost_usd"),
    }


def decode_image(data_url: str) -> tuple[bytes, str]:
    """Un'immagine incollata (data URL) -> (byte, estensione). Solo png/jpg/webp/gif."""
    m = re.fullmatch(r"data:(image/[a-z+.-]+);base64,(.+)", str(data_url).strip(), re.S)
    if not m or m.group(1) not in IMAGE_EXT:
        raise AssistantError("immagine non valida: servono PNG, JPG, WEBP o GIF")
    try:
        raw = base64.b64decode(m.group(2))
    except (binascii.Error, ValueError) as exc:
        raise AssistantError("immagine rovinata: riprova a incollarla") from exc
    if not raw:
        raise AssistantError("immagine vuota")
    if len(raw) > MAX_IMAGE_BYTES:
        raise AssistantError(f"immagine troppo grande (massimo {MAX_IMAGE_BYTES // 1_000_000} MB)")
    return raw, IMAGE_EXT[m.group(1)]


def _parse_final(text: str) -> dict[str, Any]:
    try:
        data = extract_json(text)
    except AgentError:
        return {"summary": text.strip()[-1500:]}
    return data


# --- git: fotografia e annullamento della modalità Sviluppa ---------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise AssistantError(f"git {args[0]}: {proc.stderr.strip()[-200:]}")
    return proc.stdout


BACKUP_MAX_BYTES = 2_000_000  # i file non in git più grandi (immagini, video) non si copiano


def _inside(repo: Path, rel: str) -> Path | None:
    p = (repo / rel).resolve()
    return p if p.is_relative_to(repo.resolve()) else None


def git_snapshot(repo: Path, backup: Path) -> dict[str, Any]:
    """Stato del repo PRIMA del lavoro: un commit "stash" (anche le modifiche non salvate, senza
    toccare la cartella) + una copia dei file non ancora in git (es. un file nuovo non salvato),
    così «Annulla modifiche» rimette anche quelli."""
    base = _git(repo, "stash", "create").strip() or _git(repo, "rev-parse", "HEAD").strip()
    untracked = sorted(_git(repo, "ls-files", "--others", "--exclude-standard").splitlines())
    backed = []
    for rel in untracked:
        src = _inside(repo, rel)
        if src is None or not src.is_file() or src.stat().st_size > BACKUP_MAX_BYTES:
            continue
        dest = backup / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        backed.append(rel)
    return {"base": base, "untracked": untracked, "backed": backed, "backup": str(backup)}


def git_changes(repo: Path, snap: dict[str, Any]) -> dict[str, list[str]]:
    changed = {f for f in _git(repo, "diff", "--name-only", snap["base"]).splitlines() if f}
    backup = Path(snap.get("backup", ""))
    for rel in snap.get("backed", []):  # file non in git già presenti: cambiati?
        cur = _inside(repo, rel)
        before = (backup / rel).read_bytes()
        if cur is None or not cur.is_file() or cur.read_bytes() != before:
            changed.add(rel)
    now_untracked = _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    added = sorted(set(now_untracked) - set(snap["untracked"]))
    return {"changed": sorted(changed), "added": added}


def git_revert(repo: Path, snap: dict[str, Any], files: dict[str, list[str]]) -> None:
    """Rimette i file com'erano prima del lavoro (senza metterli in stage in git)."""
    backup = Path(snap.get("backup", ""))
    backed = set(snap.get("backed", []))
    for rel in files["changed"]:
        dest = _inside(repo, rel)
        if dest is None:
            continue
        if rel in backed:
            body = (backup / rel).read_bytes()
        else:
            proc = subprocess.run(
                ["git", "cat-file", "--filters", f"{snap['base']}:{rel}"], cwd=repo,
                capture_output=True, check=False,
            )  # fmt: skip
            if proc.returncode != 0:  # non esisteva prima: si toglie
                dest.unlink(missing_ok=True)
                continue
            body = proc.stdout
            # git conserva i file con fine riga LF: se sul disco erano CRLF (Windows) si rimettono
            if dest.is_file() and b"\r\n" in dest.read_bytes() and b"\r\n" not in body:
                body = body.replace(b"\n", b"\r\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    for rel in files["added"]:
        p = _inside(repo, rel)
        if p is not None and p.is_file():
            p.unlink()


# --- la chat --------------------------------------------------------------------------------


class Assistant:
    def __init__(
        self,
        project_dir: Path,
        repo: Path,
        *,
        context: Callable[[dict[str, Any]], dict[str, Any]],
        apply_edit: Callable[[dict[str, bytes]], None],
        frame: Callable[[int, Path], None] | None = None,
        runner: Runner = run_claude,
        git: bool = True,
    ):
        self.dir = project_dir
        self.repo = repo
        self.context = context  # selezione -> contesto (parole, didascalie, pop-up, cataloghi)
        self.apply_edit = apply_edit  # file convalidati -> progetto (con Annulla)
        self.frame = frame
        self.runner = runner
        self.git = git
        self.lock = threading.RLock()

    # --- file della chat ---

    def load(self) -> dict[str, Any]:
        p = self.dir / CHAT_FILE
        if not p.exists():
            return {"messages": [], "sessions": {}}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return {"messages": [], "sessions": {}}

    def _save(self, data: dict[str, Any]) -> None:
        data["messages"] = data["messages"][-MAX_MESSAGES:]
        p = self.dir / CHAT_FILE
        tmp = p.with_suffix(".partial")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)

    def _edit(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with self.lock:
            data = self.load()
            for m in data["messages"]:
                if m.get("id") == job_id:
                    m.update(fields)
                    self._save(data)
                    return m
        raise AssistantError(f"messaggio {job_id} non trovato")

    def _step(self, job_id: str, text: str) -> None:
        with self.lock:
            data = self.load()
            for m in data["messages"]:
                if m.get("id") == job_id:
                    steps = m.setdefault("steps", [])
                    if not steps or steps[-1]["text"] != text:
                        steps.append({"t": round(time.time() - m["t0"], 1), "text": text[:200]})
                        del steps[:-40]
                    self._save(data)
                    return

    def running(self) -> dict[str, Any] | None:
        return next((m for m in self.load()["messages"] if m.get("status") == "running"), None)

    def payload(self) -> dict[str, Any]:
        data = self.load()
        msgs = [{k: v for k, v in m.items() if k not in ("snapshot",)} for m in data["messages"]]
        return {"messages": msgs, "running": any(m.get("status") == "running" for m in msgs)}

    def clear(self) -> None:
        with self.lock:
            if self.running():
                raise AssistantError("Claude sta ancora lavorando")
            self._save({"messages": [], "sessions": {}})

    # --- avvio ---

    def start(
        self,
        mode: str,
        prompt: str,
        selection: dict[str, Any] | None,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        if mode not in ("edit", "dev"):
            raise AssistantError(f"modalità sconosciuta: {mode}")
        prompt = prompt.strip()
        images = images or []
        if not prompt and not images:
            raise AssistantError("scrivi cosa vuoi fare")
        if len(images) > MAX_IMAGES:
            raise AssistantError(f"al massimo {MAX_IMAGES} immagini per messaggio")
        decoded = [decode_image(u) for u in images]
        prompt = prompt or "Guarda l'immagine che ti ho mandato."
        with self.lock:
            if self.running():
                raise AssistantError("Claude sta già lavorando: aspetta che finisca")
            data = self.load()
            n = len(data["messages"]) + 1
            job_id = f"msg_{int(time.time() * 1000)}_{n}"
            job = {
                "id": job_id, "mode": mode, "prompt": prompt[:4000],
                "selection": selection or None, "status": "running", "created_at": _now(),
                "t0": time.time(), "steps": [], "summary": "", "missing": "",
                "images": self._save_images(job_id, decoded),
            }  # fmt: skip
            data["messages"].append(job)
            self._save(data)
        return job

    def _save_images(self, job_id: str, decoded: list[tuple[bytes, str]]) -> list[str]:
        names = []
        for i, (raw, ext) in enumerate(decoded, 1):
            dest = self.dir / ATTACH / f"{job_id}_{i}.{ext}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            names.append(dest.name)
        return names

    def image_path(self, name: str) -> Path | None:
        """Percorso di uno screenshot della chat (solo i nomi che abbiamo creato noi)."""
        if not re.fullmatch(r"msg_\d+_\d+_\d+\.(png|jpg|webp|gif)", name):
            return None
        p = self.dir / ATTACH / name
        return p if p.is_file() else None

    def run(self, job_id: str) -> dict[str, Any]:
        job = next(m for m in self.load()["messages"] if m["id"] == job_id)
        try:
            if job["mode"] == "edit":
                return self._run_edit(job)
            return self._run_dev(job)
        except Exception as exc:  # qualsiasi errore va nella chat
            return self._edit(job_id, status="error", error=str(exc)[:600],
                              elapsed_s=round(time.time() - job["t0"]))  # fmt: skip

    def _session(self, mode: str, sid: str | None = None) -> str | None:
        with self.lock:
            data = self.load()
            if sid:
                data.setdefault("sessions", {})[mode] = sid
                self._save(data)
            return data.get("sessions", {}).get(mode)

    # --- Edita il video ---

    def _run_edit(self, job: dict[str, Any]) -> dict[str, Any]:
        stage = self.dir / STAGING
        stage.mkdir(parents=True, exist_ok=True)
        before: dict[str, bytes | None] = {}
        for name in EDIT_FILES:
            src = self.dir / name
            body = src.read_bytes() if src.exists() else None
            before[name] = body
            dest = stage / name
            if body is None:
                dest.unlink(missing_ok=True)
            else:
                dest.write_bytes(body)
        for old in stage.glob("allegato_*"):
            old.unlink(missing_ok=True)
        shots = []
        for i, name in enumerate(job.get("images") or [], 1):
            src = self.image_path(name)
            if src is not None:
                shots.append(f"allegato_{i}{src.suffix}")
                shutil.copyfile(src, stage / shots[-1])
        sel = job.get("selection") or {}
        ctx = self.context(sel)
        frame_ms = sel.get("frame_ms", sel.get("start_ms"))
        if self.frame is not None and frame_ms is not None:
            try:
                self.frame(int(frame_ms), stage / "frame.jpg")
                ctx["frame"] = "frame.jpg"
            except Exception:  # noqa: BLE001 - il fotogramma aiuta ma non è indispensabile
                (stage / "frame.jpg").unlink(missing_ok=True)
        (stage / "context.json").write_text(
            json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.copyfile(GUIDE, stage / "GUIDA.md")
        out = self.runner(
            edit_prompt(job["prompt"], sel, shots), cwd=stage, tools=EDIT_TOOLS,
            timeout=EDIT_TIMEOUT_S, resume=self._session("edit"),
            on_step=lambda s: self._step(job["id"], s),
        )  # fmt: skip
        self._session("edit", out.get("session_id"))
        final = _parse_final(out.get("text", ""))
        changed: dict[str, bytes] = {}
        for name, mod in EDIT_FILES.items():
            p = stage / name
            body = p.read_bytes() if p.exists() else None
            if body is None or body == before[name]:
                continue
            try:
                mod.load(stage)  # stessi controlli dei pannelli: un file sbagliato non entra
            except Exception as exc:
                raise AssistantError(f"{name} non valido, niente applicato: {exc}") from exc
            changed[name] = body
        if changed:
            self.apply_edit(changed)
        return self._edit(
            job["id"], status="done" if not out.get("is_error") else "error",
            summary=str(final.get("summary") or out.get("text", ""))[:2000],
            missing=str(final.get("missing") or "")[:800], changed=sorted(changed),
            error=None if not out.get("is_error") else str(out.get("text", ""))[:600],
            elapsed_s=round(time.time() - job["t0"]),
        )  # fmt: skip

    # --- Modifica l'editor ---

    def _run_dev(self, job: dict[str, Any]) -> dict[str, Any]:
        backup = self.dir / "work" / "claude" / "dev" / job["id"]
        snap = git_snapshot(self.repo, backup) if self.git else None
        if snap:
            self._edit(job["id"], snapshot=snap)
        shots = [p for n in job.get("images") or [] if (p := self.image_path(n)) is not None]
        extra = {"add_dirs": [self.dir / ATTACH]} if shots else {}
        out = self.runner(
            dev_prompt(job["prompt"], self.dir, [str(p) for p in shots]), cwd=self.repo,
            tools=DEV_TOOLS, timeout=DEV_TIMEOUT_S, resume=self._session("dev"),
            on_step=lambda s: self._step(job["id"], s), **extra,
        )  # fmt: skip
        self._session("dev", out.get("session_id"))
        final = _parse_final(out.get("text", ""))
        files = git_changes(self.repo, snap) if snap else {"changed": [], "added": []}
        touched = files["changed"] + files["added"]
        restart = any(f.endswith(".py") and f.startswith("src/") for f in touched)
        return self._edit(
            job["id"], status="done" if not out.get("is_error") else "error",
            summary=str(final.get("summary") or out.get("text", ""))[:2000],
            how_to_use=str(final.get("how_to_use") or "")[:600],
            tests=str(final.get("tests") or "")[:300], files=files, restart=restart,
            error=None if not out.get("is_error") else str(out.get("text", ""))[:600],
            elapsed_s=round(time.time() - job["t0"]),
        )  # fmt: skip

    def revert(self, job_id: str) -> dict[str, Any]:
        m = next((x for x in self.load()["messages"] if x["id"] == job_id), None)
        if m is None or m.get("mode") != "dev" or not m.get("snapshot"):
            raise AssistantError("niente da annullare per questo messaggio")
        if m.get("reverted"):
            raise AssistantError("già annullato")
        git_revert(self.repo, m["snapshot"], m.get("files") or {"changed": [], "added": []})
        return self._edit(job_id, reverted=True)


# --- prompt -----------------------------------------------------------------------------------


def _shots_note(images: list[str] | tuple[str, ...]) -> str:
    if not images:
        return ""
    return (
        "\nIl creator ha allegato degli screenshot (è quello che vede nell'editor): guardali "
        "con Read prima di agire: " + ", ".join(images) + ".\n"
    )


def edit_prompt(request: str, sel: dict[str, Any], images: list[str] | tuple[str, ...] = ()) -> str:
    if sel.get("start_ms") is not None and sel.get("end_ms") is not None:
        where = f"il tratto selezionato va da {sel['start_ms']} a {sel['end_ms']} ms del raw"
    elif sel.get("frame_ms") is not None:
        where = f"il fotogramma selezionato è a {sel['frame_ms']} ms del raw"
    else:
        where = "nessuna selezione: vale per tutto il video"
    return f"""Sei il montatore dentro l'editor video autocut. Il creator ti chiede, dalla chat:
«{request}»
Selezione: {where}.{_shots_note(images)}

Lavori SOLO sui file JSON di questa cartella (copie del progetto): leggi prima GUIDA.md (come
funziona ogni file e le ricette) e context.json (cosa c'è nella selezione, cataloghi, stile
attivo). Se c'è frame.jpg guardalo. Scegli l'opzione migliore con gli strumenti che l'editor ha,
come farebbe un montatore esperto, e modifica i file con Edit/Write. Non creare altri file.
Se una parte della richiesta non si può fare con gli strumenti di oggi, falla per quanto
possibile e scrivi in "missing" cosa manca all'editor (in italiano, una frase).

Alla fine rispondi SOLO con:
{{"summary": "cosa hai cambiato, in italiano, 1-3 frasi", "missing": ""}}"""


def dev_prompt(request: str, project_dir: Path, images: list[str] | tuple[str, ...] = ()) -> str:
    return f"""Sei Claude Code dentro l'editor video autocut: il creator ti scrive dalla chat
«Chiedi a Claude» dell'editor (è italiano, rispondi in italiano). Richiesta:
«{request}»
{_shots_note(images)}
Lavora come in una normale sessione di sviluppo su questo repo: leggi README.md e il codice
che serve (editor: src/autocut/editor/server.py, static/app.js, static/index.html,
static/styles.css), fai la modifica completa e curata, aggiungi o aggiorna i test in tests/,
poi `uv run --no-sync ruff check` e `uv run --no-sync pytest -q <test pertinenti>`.
Regole: niente commit né push, non toccare .env, projects/, inspiration/, main.py; non
avviare server (l'editor è acceso: alla fine si ricarica e, se cambia il Python, si riavvia da
solo). Progetto aperto ora: {project_dir.name}. Se la richiesta non è chiara o è rischiosa,
non indovinare: spiega e chiedi nel summary.

Alla fine rispondi SOLO con:
{{"summary": "cosa hai fatto, 2-4 frasi", "how_to_use": "dove lo trovo nell'editor",
"tests": "esito di ruff e test"}}"""
