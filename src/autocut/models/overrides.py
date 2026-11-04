"""Modelli di overrides.json: correzioni dell'utente sopra le proposte, mai dentro la timeline.

- `overrides`: stato attuale, una voce per id della proposta ribaltata (chiave = target.id).
- `history`: cronologia append-only; l'undo è una nuova voce con `reverts`, non una cancellazione.

Azioni riservate per l'editor (non ancora accettate): `manual_range`, `adjust_boundary`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

OVERRIDES_SCHEMA_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class TimelineRef(_Model):
    project: str
    timeline_schema_version: int


class Target(_Model):
    id: str
    type: Literal["segment", "repeat_group"]


class Override(_Model):
    id: str
    target: Target
    action: Literal["set_state", "choose_take"]
    value: dict[str, Any]
    proposed: dict[str, Any] | None = None
    status: Literal["active", "orphan"] = "active"
    snapshot: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None

    @model_validator(mode="after")
    def _action_matches(self) -> Override:
        if self.action == "set_state":
            if self.target.type != "segment":
                raise ValueError(f"{self.id}: set_state vale solo per i segmenti")
            if self.value.get("state") not in ("keep", "remove"):
                raise ValueError(f"{self.id}: set_state richiede value.state = keep|remove")
        elif self.action == "choose_take":
            if self.target.type != "repeat_group":
                raise ValueError(f"{self.id}: choose_take vale solo per i gruppi di ripetizioni")
            if "take_id" not in self.value:
                raise ValueError(f"{self.id}: choose_take richiede value.take_id (null = tutte)")
            take = self.value["take_id"]
            if take is not None and not isinstance(take, str):
                raise ValueError(f"{self.id}: value.take_id deve essere un id o null")
        return self


class HistoryEntry(_Model):
    seq: int = Field(ge=1)
    at: AwareDatetime
    action: Literal["create", "update", "remove", "undo", "orphaned", "restored"]
    override_id: str
    target_id: str
    before: Any = None
    after: Any = None
    reverts: int | None = None

    @model_validator(mode="after")
    def _undo_has_target(self) -> HistoryEntry:
        if self.action == "undo":
            if self.reverts is None:
                raise ValueError(f"voce {self.seq}: un undo deve indicare reverts")
            if self.reverts >= self.seq:
                raise ValueError(f"voce {self.seq}: un undo può annullare solo voci precedenti")
        elif self.reverts is not None:
            raise ValueError(f"voce {self.seq}: reverts vale solo per undo")
        return self


class OverridesFile(_Model):
    model_config = ConfigDict(extra="allow", title="autocut overrides")

    schema_version: int = OVERRIDES_SCHEMA_VERSION
    timeline_ref: TimelineRef
    overrides: dict[str, Override] = Field(default_factory=dict)
    history: list[HistoryEntry] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _supported(cls, v: int) -> int:
        if v != OVERRIDES_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version {v} non supportata (supportata: {OVERRIDES_SCHEMA_VERSION})"
            )
        return v

    @model_validator(mode="after")
    def _integrity(self) -> OverridesFile:
        ids: set[str] = set()
        for key, ov in self.overrides.items():
            if key != ov.target.id:
                raise ValueError(f"chiave {key!r} diversa da target.id {ov.target.id!r}")
            if ov.id in ids:
                raise ValueError(f"id override duplicato: {ov.id}")
            ids.add(ov.id)
        for expected, entry in enumerate(self.history, start=1):
            if entry.seq != expected:
                raise ValueError(f"cronologia: atteso seq {expected}, trovato {entry.seq}")
        return self
