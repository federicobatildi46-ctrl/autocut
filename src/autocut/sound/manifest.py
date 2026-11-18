"""Elenco dei suoni della libreria, ricavato dal documento master del sound design
(UE-Sound-Design-Claude-Training-COMPLETE.md, sezioni A2 e A3).

Ogni voce è un tipo di suono con il suo uso, il prompt per ElevenLabs, la durata, il numero di
varianti (il documento chiede di ascoltare più varianti e sceglierne una) e il livello di default.
La musica non c'è apposta: il documento dice di non generarla mai.
"""

from __future__ import annotations

from dataclasses import dataclass

FAMILIES = ("whooshes", "textures", "risers", "hits")
LEVEL_DB = {"whooshes": -12.0, "textures": -6.5, "risers": -5.0, "hits": -8.0}

_CLEAN = "isolated sound effect, no music, no voice, clean studio quality"


@dataclass(frozen=True)
class SfxSpec:
    id: str  # es. "whoosh.hollow"
    family: str  # whooshes | textures | risers | hits
    folder: str  # sottocartella in library/sfx/<family>/
    label: str
    usage: str  # quando si usa (dal documento)
    prompt: str
    duration_s: float
    variations: int
    frequency: str = "normale"  # spesso | normale | raro

    @property
    def level_db(self) -> float:
        return LEVEL_DB[self.family]


def _w(folder, label, usage, prompt, dur, var, freq="normale"):
    return SfxSpec(
        f"whoosh.{folder}", "whooshes", folder, label, usage, f"{prompt}, {_CLEAN}", dur, var, freq
    )


def _t(folder, label, usage, prompt, dur, var, freq="normale"):
    return SfxSpec(
        f"texture.{folder}", "textures", folder, label, usage, f"{prompt}, {_CLEAN}", dur, var, freq
    )


def _r(folder, label, usage, prompt, dur, var, freq="normale"):
    return SfxSpec(
        f"riser.{folder}", "risers", folder, label, usage, f"{prompt}, {_CLEAN}", dur, var, freq
    )


MANIFEST: tuple[SfxSpec, ...] = (
    # --- WHOOSHES: movimento (picco sul frame più veloce, -12 dB, max -10) ---------------
    _w(
        "classy_airy",
        "Classy airy whoosh",
        "movimenti grandi e pesanti (raro)",
        "big heavy classy airy whoosh, wide smooth rush of air, cinematic and elegant",
        2.0,
        2,
        "raro",
    ),
    _w(
        "hollow",
        "Hollow whoosh",
        "slide e pan standard (molto usato)",
        "hollow textured whoosh, quick swoosh of a title sliding across the screen, modern motion graphics",
        1.0,
        3,
        "spesso",
    ),
    _w(
        "futuristic",
        "Futuristic whoosh",
        "slide e pan standard, tocco sci-fi (molto usato)",
        "futuristic textured whoosh with a subtle digital shimmer, UI card sliding in, sleek tech",
        1.0,
        3,
        "spesso",
    ),
    _w(
        "deep_voice",
        "Deep voice whoosh",
        "default per le animazioni quando non sei sicuro",
        "deep low sci-fi whoosh with a breathy throaty texture, smooth swoosh for motion graphics",
        1.2,
        3,
        "spesso",
    ),
    _w(
        "generic_long",
        "Generic long whoosh",
        "costruire verso una transizione veloce (mezzo riser)",
        "long building whoosh that swells up and ends in a fast pass-by, leading into a quick transition",
        2.5,
        2,
    ),
    _w(
        "organic_wind",
        "Organic wind whoosh",
        "movimenti lenti e metodici, camera drift",
        "soft organic wind whoosh, gentle slow movement of air, calm camera drift",
        2.0,
        2,
    ),
    _w(
        "short",
        "Short whoosh",
        "movimenti molto rapidi e piccoli (raro)",
        "very short tiny quick swish, fast small movement",
        0.6,
        2,
        "raro",
    ),
    _w(
        "synthetic",
        "Synthetic whoosh",
        "transizioni di scena, taglio sci-fi",
        "synthetic electronic sweep whoosh, sci-fi scene transition",
        1.5,
        2,
    ),
    _w(
        "transition_spacey",
        "Transition spacey whoosh",
        "transizioni di scena, taglio sci-fi",
        "spacey airy transition whoosh with shimmering cosmic texture, scene change",
        1.8,
        2,
    ),
    _w(
        "water_dropper",
        "Water dropper",
        "transizioni di scena, taglio sci-fi",
        "sci-fi liquid water dropper transition, digital droplet with a short whoosh, scene change",
        1.2,
        2,
    ),
    # --- TEXTURES: eventi senza scorrimento (sul frame dell'evento, -6/-7 dB) ------------
    _t(
        "pop",
        "Pop",
        "testo che appare intero, pop di UI",
        "clean short cartoon pop, bubbly pop of text appearing on screen",
        0.5,
        3,
        "spesso",
    ),
    _t(
        "ui_click",
        "UI click",
        "elemento di interfaccia che appare",
        "crisp clearly audible modern UI click, interface element appears, clean digital tap with an immediate attack",
        0.5,
        3,
        "spesso",
    ),
    _t(
        "scifi_click",
        "Sci-fi click",
        "click o cambio dentro l'animazione (es. colore)",
        "short sci-fi interface click with a tiny futuristic beep, immediate attack at the very start, element changes state",
        0.5,
        3,
        "spesso",
    ),
    _t(
        "gears",
        "Gears / complex mechanism gizmo",
        "testo lettera per lettera, comparsa meccanica, più elementi in sequenza",
        "complex mechanism gizmo, tiny gears turning and clicking, intricate mechanical write-out texture",
        1.5,
        2,
    ),
    _t(
        "tiny_gearwheel",
        "Tiny gearwheel",
        "scrittura lettera per lettera, dettagli meccanici",
        "tiny gearwheel ratchet ticking, small precise mechanical clicks",
        1.0,
        2,
    ),
    _t(
        "keyboard_writing",
        "Keyboard writing",
        "digitazione sullo schermo",
        "typing on a mechanical keyboard, short natural burst of keystrokes",
        2.0,
        2,
    ),
    _t(
        "analog_button",
        "Analog button",
        "click meccanici più fisici, oggetti che compaiono",
        "analog mechanical button press, tactile switch click",
        0.5,
        2,
    ),
    _t(
        "video_scan",
        "Video scan / gears moving",
        "singola immagine o oggetto che appare e va sottolineato",
        "digital video scan sweep with small gears moving, single object emphasis",
        1.0,
        2,
    ),
    _t(
        "scifi_impact",
        "Sci-fi impact",
        "nuova UI o oggetto rivelato che entra in scena (preferiti)",
        "high quality punchy sci-fi impact hit, futuristic reveal of a new interface element",
        1.5,
        3,
        "spesso",
    ),
    _t(
        "activate_protection_energy",
        "Activate protection energy",
        "ingresso in una nuova animazione",
        "sci-fi energy shield activation, power-up sweep into a bright energy hum",
        2.0,
        2,
    ),
    _t(
        "digital_camera_click",
        "Digital camera click",
        "transizione clip-clip o flash, sul frame del taglio",
        "crisp digital camera shutter click, quick photo snap",
        0.5,
        2,
    ),
    _t(
        "heavenly_choir",
        "Cartoon heavenly choir",
        "grande rivelazione importante",
        "short cartoon heavenly choir sting, bright angelic aah reveal",
        2.0,
        2,
        "raro",
    ),
    _t(
        "success_reward",
        "Success reward",
        "si arriva a una conclusione",
        "success reward chime, positive achievement sparkle sound",
        1.2,
        2,
    ),
    _t(
        "alarm_buzzer",
        "Alarm buzzer",
        "piccola attesa a volume molto basso (raro)",
        "subtle low alarm buzzer, short soft warning buzz",
        1.0,
        1,
        "raro",
    ),
    _t(
        "scifi_hit",
        "Sci-fi hit",
        "transizioni tra scene (molto usato)",
        "punchy short sci-fi hit, digital transition accent between scenes",
        1.0,
        3,
        "spesso",
    ),
    # --- RISERS & HITS: anticipazione (-5 dB; finiscono sul frame di transizione) --------
    _r(
        "sharp_bass",
        "Sharp bass riser",
        "~5 s dopo l'hook; almeno 2 per video (preferito)",
        "sharp bass riser, rising sub bass tension build-up ending abruptly, cinematic transition",
        4.0,
        3,
        "spesso",
    ),
    _r(
        "metallic",
        "Metallic riser",
        "build verso il segmento successivo; almeno 2 per video (preferito)",
        "metallic riser, shimmering metallic tension that keeps rising and is loudest at the very end, cinematic transition into the next segment",
        4.0,
        3,
        "spesso",
    ),
    _r(
        "suspenseful",
        "Suspenseful build-up",
        "build-up di tensione, con parsimonia",
        "suspenseful slow tension build-up swell",
        5.0,
        2,
        "raro",
    ),
    _r(
        "suck_back",
        "Suck-back riser",
        "build lento e bello; volume molto basso o molto alto, mai a metà",
        "reverse suck-back riser, reversed swell sucking back into silence, slow beautiful build",
        3.0,
        3,
    ),
    SfxSpec(
        "hit.impact",
        "hits",
        "impact",
        "Impact hit",
        "sotto il riser per chiudere la transizione",
        f"single deep cinematic impact hit with a sub boom, sharp attack at the very start then a decaying tail, no build-up, {_CLEAN}",
        2.0,
        3,
        "spesso",
    ),
)


def by_id() -> dict[str, SfxSpec]:
    return {s.id: s for s in MANIFEST}


def total_seconds(specs: tuple[SfxSpec, ...] = MANIFEST) -> float:
    return sum(s.duration_s * s.variations for s in specs)


def total_files(specs: tuple[SfxSpec, ...] = MANIFEST) -> int:
    return sum(s.variations for s in specs)
