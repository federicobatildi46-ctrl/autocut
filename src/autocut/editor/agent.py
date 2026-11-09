"""Claude + Higgsfield per il riquadro "Potenzia".

L'editor lancia Claude Code in modalità non interattiva (`claude -p`) con il tuo account:
- `suggest`: Claude guarda il frame (strumento Read) e la trascrizione intorno e propone idee;
- `generate`: Claude usa la skill `higgsfield-generate` e la CLI `higgsfield` per generare
  un'immagine, una grafica o un video, con il frame come riferimento.

Strumenti permessi all'agente in generazione: Read, Skill e solo i comandi `higgsfield`/`hf`.
Prima di generare deve stimare il costo e fermarsi se supera il tetto di crediti.
Setup una volta per laptop: `npm i -g @higgsfield/cli`, `higgsfield auth login`,
`higgsfield workspace set <id>`, `npx skills add higgsfield-ai/skills` (nel repo).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..paths import REPO_ROOT

SUGGEST_TIMEOUT_S = 240
GENERATE_TIMEOUT_S = 1500
STATUS_TIMEOUT_S = 60

KIND_LABEL = {"video": "video AI", "image": "immagine AI", "graphic": "grafica / motion graphic"}
# Tetto di crediti per singola richiesta (sovrascrivibile con variabili d'ambiente).
BUDGET_ENV = {
    "image": "AUTOCUT_AI_BUDGET_IMAGE",
    "graphic": "AUTOCUT_AI_BUDGET_IMAGE",
    "video": "AUTOCUT_AI_BUDGET_VIDEO",
}
BUDGET_DEFAULT = {"image": 6, "graphic": 6, "video": 40}


class AgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameContext:
    frame_path: Path
    time_ms: int  # tempo camera
    rel_ms: int  # tempo dall'inizio del raw (o del tratto)
    portrait: bool
    transcript: str  # parlato intorno al frame
    project: str
    brand: str = ""  # descrizione del brand pack attivo (palette, font, stile grafico)


def _brand_block(ctx: FrameContext) -> str:
    if not ctx.brand:
        return ""
    return f"\nBrand pack da rispettare (colori, tipografia, stile delle grafiche): {ctx.brand}\n"


def budget_for(kind: str) -> int:
    raw = os.environ.get(BUDGET_ENV.get(kind, ""), "").strip()
    try:
        return int(raw) if raw else BUDGET_DEFAULT.get(kind, 6)
    except ValueError:
        return BUDGET_DEFAULT.get(kind, 6)


def child_env() -> dict[str, str]:
    """Ambiente per i processi figli: certificati di sistema per Node (antivirus/proxy TLS)."""
    env = dict(os.environ)
    opts = env.get("NODE_OPTIONS", "")
    if "--use-system-ca" not in opts:
        env["NODE_OPTIONS"] = (opts + " --use-system-ca").strip()
    return env


def _top_level_objects(text: str) -> list[str]:
    """Oggetti {...} di primo livello, ignorando le graffe dentro le stringhe JSON."""
    found: list[str] = []
    depth, start, in_str, escaped = 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth > 0:
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                found.append(text[start : i + 1])
    return found


def extract_json(text: str) -> dict[str, Any]:
    """Ultimo oggetto JSON nella risposta (anche dentro ```json ... ```)."""
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    pool = "\n".join(fenced) if fenced else text
    for raw in _top_level_objects(pool)[::-1]:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise AgentError("la risposta di Claude non contiene un JSON valido")


def parse_account_status(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """Stato della CLI Higgsfield da `higgsfield account status --json`."""
    if returncode == 0:
        try:
            data = json.loads(stdout)
        except ValueError:
            return {"higgsfield": "error", "detail": stdout[-200:]}
        return {
            "higgsfield": "connected",
            "credits": data.get("credits"),
            "plan": data.get("subscription_plan_type"),
        }
    text = (stderr + stdout).lower()
    if "workspace" in text:
        return {"higgsfield": "no_workspace", "detail": "nessun workspace selezionato"}
    auth_words = ("login", "logged", "log in", "auth", "token", "unauthorized", "401")
    if any(word in text for word in auth_words):
        return {"higgsfield": "needs_auth", "detail": "serve higgsfield auth login"}
    return {"higgsfield": "error", "detail": (stderr or stdout).strip()[-200:]}


def _aspect(ctx: FrameContext) -> str:
    return "9:16" if ctx.portrait else "16:9"


def _format(ctx: FrameContext) -> str:
    return "9:16 verticale" if ctx.portrait else "16:9 orizzontale"


def suggest_prompt(ctx: FrameContext) -> str:
    return f"""Sei il direttore creativo di un editor video per i contenuti social di un creator italiano.
Formato del video: {_format(ctx)}.
Frame selezionato a {ctx.rel_ms / 1000:.1f} s: il file immagine è {ctx.frame_path} — guardalo con lo strumento Read.
Cosa dice il creator intorno a questo punto: «{ctx.transcript or "(silenzio)"}»
{_brand_block(ctx)}
Proponi 3 idee concrete e diverse per arricchire questo punto con Higgsfield:
- un B-roll video AI ultra realistico che illustra quello che dice,
- un'immagine o uno sfondo AI,
- una grafica / motion graphic (titolo, parola chiave, overlay).
Ogni idea deve rispettare il formato {_format(ctx)} e stare fuori dalle zone coperte
dall'interfaccia di Reels/TikTok.

Rispondi SOLO con questo JSON, senza altro testo:
{{"suggestions": [{{"kind": "video|image|graphic", "title": "max 6 parole",
"prompt": "richiesta dettagliata in italiano, pronta da inviare", "why": "perché funziona qui, 1 frase",
"duration_s": 3}}]}}
Non generare niente e non usare strumenti diversi da Read."""


def generate_prompt(ctx: FrameContext, kind: str, request: str, budget: int) -> str:
    model_hint = (
        "un modello video (vedi `higgsfield model list --video`); durata 3-6 s salvo richiesta diversa"
        if kind == "video"
        else "un modello immagine ultra realistico (es. nano_banana_2); per le grafiche cura tipografia e composizione"
    )
    return f"""Esegui questa richiesta di generazione con Higgsfield usando la skill higgsfield-generate
e la CLI `higgsfield` (aggiungi sempre --json ai comandi).

Tipo richiesto: {KIND_LABEL.get(kind, kind)}.
Richiesta del creator: «{request}»
Formato: aspect_ratio {_aspect(ctx)} ({_format(ctx)}).
Frame del video a {ctx.rel_ms / 1000:.1f} s: {ctx.frame_path} — guardalo con Read. Se serve coerenza con la
scena (persona, luce, ambiente) passalo alla CLI come riferimento: --image-references "{ctx.frame_path}".
Cosa dice il creator in quel punto: «{ctx.transcript or "(silenzio)"}»
{_brand_block(ctx)}
Regole:
- UN SOLO job, con {model_hint};
- scrivi tu il prompt per il modello, in inglese, dettagliato, ultra realistico;
- prima stima il costo con `higgsfield generate cost <modello> ... --json`: se supera {budget} crediti
  NON generare e rispondi con status "error" spiegando il costo;
- poi `higgsfield generate create <modello> ... --wait --json` e prendi gli URL del risultato;
- non comprare crediti, non cambiare workspace, non cancellare niente, non usare comandi diversi da higgsfield.

Alla fine rispondi SOLO con questo JSON:
{{"status": "done|error", "urls": ["url del file generato"], "media_type": "video|image",
"model": "modello usato", "credits": 0, "prompt_used": "prompt inviato al modello", "note": "breve, in italiano"}}"""


class ClaudeAgent:
    """Esegue `claude -p` (prompt su stdin, output JSON) e controlla la CLI Higgsfield."""

    def __init__(self, workdir: Path | None = None):
        self.workdir = workdir or REPO_ROOT  # qui ci sono le skill in .claude/skills
        self._status: tuple[float, dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def executable(self) -> str | None:
        return shutil.which("claude")

    def higgsfield_executable(self) -> str | None:
        return shutil.which("higgsfield")

    def status(self, refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._status and not refresh and time.time() - self._status[0] < 60:
                return self._status[1]
            result: dict[str, Any] = {"claude": self.executable() is not None}
            hf = self.higgsfield_executable()
            if hf is None:
                result.update(higgsfield="missing", detail="serve npm i -g @higgsfield/cli")
            else:
                try:
                    proc = subprocess.run(
                        [hf, "account", "status", "--json"],
                        capture_output=True,
                        timeout=STATUS_TIMEOUT_S,
                        env=child_env(),
                        check=False,
                    )
                    result.update(
                        parse_account_status(
                            proc.returncode,
                            proc.stdout.decode("utf-8", "replace"),
                            proc.stderr.decode("utf-8", "replace"),
                        )
                    )
                except (OSError, subprocess.TimeoutExpired):
                    result.update(higgsfield="error", detail="la CLI non risponde")
            self._status = (time.time(), result)
            return result

    def start_login(self) -> None:
        """Apre `higgsfield auth login` (login nel browser) in una finestra a parte."""
        hf = self.higgsfield_executable()
        if hf is None:
            raise AgentError("CLI Higgsfield non trovata: npm i -g @higgsfield/cli")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen([hf, "auth", "login"], env=child_env(), creationflags=flags)  # noqa: S603
        with self._lock:
            self._status = None  # al prossimo controllo si rilegge lo stato

    def _run(self, prompt: str, tools: list[str], timeout: int) -> dict[str, Any]:
        exe = self.executable()
        if exe is None:
            raise AgentError("Claude Code (comando `claude`) non trovato nel PATH")
        cmd = [exe, "-p", "--output-format", "json", "--allowedTools", *tools]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                cwd=self.workdir,
                env=child_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentError(f"Claude non ha risposto entro {timeout} s") from exc
        out = proc.stdout.decode("utf-8", "replace").strip()
        try:
            envelope = json.loads(out)
        except ValueError:
            err = proc.stderr.decode("utf-8", "replace").strip()[-400:]
            raise AgentError(f"risposta inattesa da Claude: {err or out[-400:]}") from None
        if envelope.get("is_error"):
            raise AgentError(
                f"Claude ha risposto con un errore: {str(envelope.get('result'))[:400]}"
            )
        return extract_json(str(envelope.get("result", "")))

    def suggest(self, ctx: FrameContext) -> list[dict[str, Any]]:
        data = self._run(suggest_prompt(ctx), ["Read"], SUGGEST_TIMEOUT_S)
        out = []
        for s in data.get("suggestions", [])[:4]:
            kind = s.get("kind") if s.get("kind") in KIND_LABEL else "video"
            out.append(
                {
                    "kind": kind,
                    "title": str(s.get("title", ""))[:80],
                    "prompt": str(s.get("prompt", ""))[:1200],
                    "why": str(s.get("why", ""))[:300],
                    "duration_s": s.get("duration_s"),
                }
            )
        if not out:
            raise AgentError("Claude non ha proposto idee")
        return out

    def ask_json(self, prompt: str) -> dict[str, Any]:
        """Domanda testuale (pop-up: analisi del parlato e chat). Nessuno strumento che
        modifichi o generi: la risposta è solo un JSON di operazioni da applicare."""
        return self._run(prompt, ["Read"], SUGGEST_TIMEOUT_S)

    def ask_skill(self, prompt: str) -> dict[str, Any]:
        """Come ask_json ma con le skill del progetto (es. higgsfield-vfx): legge e risponde,
        non genera e non lancia comandi."""
        return self._run(prompt, ["Read", "Skill"], SUGGEST_TIMEOUT_S)

    def generate(self, ctx: FrameContext, kind: str, request: str) -> dict[str, Any]:
        tools = ["Read", "Skill", "Bash(higgsfield:*)", "Bash(hf:*)"]
        prompt = generate_prompt(ctx, kind, request, budget_for(kind))
        return self._run(prompt, tools, GENERATE_TIMEOUT_S)
