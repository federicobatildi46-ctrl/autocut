"""Annulla / Ripeti per tutto l'editor (tagli, testo, sticker, immagini, effetti, audio, stile).

Prima e dopo ogni modifica si fotografa lo stato del progetto; se è cambiato, la foto di prima
va nella pila di Annulla. I file dell'editor si rimettono com'erano; overrides.json invece è
append-only: lo stato di prima si ricostruisce con nuove voci (set_value / clear), la sua
cronologia non si riscrive mai. Le pile vivono finché l'editor è acceso.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..models.timeline import Timeline
from ..overrides import store

FILES = (
    "popups.json",
    "text_style.json",
    "effects.json",
    "cuts.json",
    "audio.json",
    "filters.json",
)  # vfx.json no: lo aggiorna anche il lavoro in background (Annulla romperebbe una generazione)
STATE_KEYS = ("style", "brand", "hook")  # da editor_state.json (le "riviste" no)
LIMIT = 200


class HistoryError(ValueError):
    pass


class History:
    def __init__(self, project_dir: Path, timeline: Callable[[], Timeline], state_file: str):
        self.dir = project_dir
        self.timeline = timeline
        self.state_path = project_dir / state_file
        self.undo_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []
        self.lock = threading.RLock()

    # --- foto dello stato -----------------------------------------------------------

    def _state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        return {k: data.get(k) for k in STATE_KEYS}

    def snapshot(self) -> dict[str, Any]:
        files = {}
        for name in FILES:
            p = self.dir / name
            files[name] = p.read_bytes() if p.exists() else None
        try:
            ov = store.load(self.dir, self.timeline())
            active = {k: dict(o.value) for k, o in ov.overrides.items() if o.status == "active"}
        except Exception:  # timeline o overrides illeggibili: non si traccia quella parte
            active = None
        return {"files": files, "overrides": active, "state": self._state()}

    def record(self, before: dict[str, Any], after: dict[str, Any]) -> None:
        if before == after:
            return
        with self.lock:
            self.undo_stack.append(before)
            del self.undo_stack[:-LIMIT]
            self.redo_stack.clear()

    # --- ripristino -----------------------------------------------------------------

    def _restore(self, snap: dict[str, Any]) -> None:
        for name, body in snap["files"].items():
            p = self.dir / name
            if body is None:
                p.unlink(missing_ok=True)
            else:
                tmp = p.with_suffix(".partial")
                tmp.write_bytes(body)
                tmp.replace(p)
        if snap["overrides"] is not None:
            tl = self.timeline()
            ov = store.load(self.dir, tl)
            now = {k: dict(o.value) for k, o in ov.overrides.items() if o.status == "active"}
            want = snap["overrides"]
            for target in sorted(set(now) | set(want)):
                try:
                    if target in want and now.get(target) != want[target]:
                        ov = store.set_value(ov, tl, target, want[target], note="annulla/ripeti")
                    elif target not in want:
                        ov = store.clear(ov, target)
                except store.OverrideError:
                    continue  # la proposta non c'è più nella timeline
            store.save(self.dir, ov)
        data = json.loads(self.state_path.read_text(encoding="utf-8")) if (
            self.state_path.exists()
        ) else {}  # fmt: skip
        for k, v in snap["state"].items():  # campo assente prima = lo si toglie
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        tmp = self.state_path.with_suffix(".partial")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.state_path)

    def undo(self) -> None:
        with self.lock:
            if not self.undo_stack:
                raise HistoryError("niente da annullare")
            cur = self.snapshot()
            prev = self.undo_stack.pop()
            self._restore(prev)
            self.redo_stack.append(cur)

    def redo(self) -> None:
        with self.lock:
            if not self.redo_stack:
                raise HistoryError("niente da ripetere")
            cur = self.snapshot()
            nxt = self.redo_stack.pop()
            self._restore(nxt)
            self.undo_stack.append(cur)

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)
