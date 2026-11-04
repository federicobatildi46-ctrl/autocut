"""Eventi audio di Scribe (es. "[esita]", "(risata)"): quali proteggono il parlato e quali no.

Gli eventi restano tutti nella lista delle parole (id stabili); è questa regola, letta dalle
impostazioni, a decidere se un evento è "morto" (si può tagliare come una pausa) o se conta
come parlato. Cambiare la regola non richiede di rifare la trascrizione.
"""

from __future__ import annotations

from .models.timeline import TranscriptionSettings, Word

_STRIP = "[]()<>{} \t"


def event_tag(text: str) -> str:
    """ "[Esita]" -> "esita"."""
    return text.strip(_STRIP).strip().lower()


def is_dead_event(word: Word, settings: TranscriptionSettings) -> bool:
    if word.kind != "audio_event":
        return False
    if settings.audio_events == "ignore":
        return True
    tag = event_tag(word.text)
    return any(key in tag for key in settings.dead_events)


def protects_speech(word: Word, settings: TranscriptionSettings) -> bool:
    """True se la parola/evento va trattata come parlato (non tagliabile come pausa)."""
    return not is_dead_event(word, settings)
