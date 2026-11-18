# Libreria condivisa (non versionata)

Qui vanno i file pesanti condivisi tra progetti e brand. Git tiene solo questo README e la
struttura delle cartelle; i file audio restano locali (copiali a mano tra laptop).

```
library/sfx/whooshes/   movimento: slide, pan, zoom, transizioni (−12 dB)
library/sfx/textures/   pop, click, gears, sci-fi, UI (−6/−7 dB)
library/sfx/risers/     anticipazione (−5 dB)
library/sfx/hits/       impatti sotto i riser
library/sfx/music/      solo sotto il parlato (−19 dB)
```

Dentro ogni famiglia usa sottocartelle per tipo (es. `whooshes/hollow/`, `textures/pop/`) con
più varianti: la skill `autocut-sound-design` le ascolta e sceglie quella giusta.
Tieni un file `LICENZE.txt` con l'origine di ogni pacchetto.

## Generare la libreria con ElevenLabs

```bash
uv run --system-certs autocut sfx generate --dry-run   # cosa genera e quanto costa
uv run --system-certs autocut sfx generate             # genera i file mancanti, uno per chiamata
uv run --system-certs autocut sfx generate --only riser.   # solo un gruppo
uv run --system-certs autocut sfx catalog              # ricostruisce catalog.json
```

L'elenco dei suoni (30 tipi, 71 file) sta in `src/autocut/sound/manifest.py` ed è preso dal
documento master. `catalog.json` riporta per ogni file famiglia, uso, livello di default,
durata e **posizione del picco** (`peak_ms`), utile per allineare il picco del whoosh al frame
più veloce o il transiente all'evento.
