# autocut

Motore di montaggio automatico per video long-form (orizzontali) e short-form (verticali).
Riceve il raw della camera (e opzionalmente la registrazione schermo) e produce un
`timeline.json` con sorgenti, sincronizzazione, parole con i tempi, segmenti tenuti/tolti
e gruppi di ripetizioni con la proposta. Niente render, niente stili: solo il motore.

## Setup

Requisiti: [uv](https://docs.astral.sh/uv/), ffmpeg e ffprobe nel `PATH`.

```bash
uv sync
cp .env.example .env    # poi inserisci ELEVENLABS_API_KEY
uv run autocut doctor
```

## Comandi (stato attuale)

| Comando | Cosa fa |
|---|---|
| `autocut doctor` | Verifica ffmpeg, ffprobe e la API key |
| `autocut ingest <nome> <cartella>` | Riconosce camera/schermo e scrive la prima `timeline.json` |
| `autocut transcribe <nome> [--range] [--force]` | Trascrive l'audio camera con Scribe, con cache |
| `autocut cuts <nome> [--range] [--set pauses.threshold_ms=900]` | Toglie le pause morte: segmenti tenuti/tolti |
| `autocut export-schemas` | Rigenera `schemas/*.schema.json` dai modelli |

In arrivo: `sync`, `repeats`, `overrides`, `validate` e `raw` (tutto il giro).

### Pause

- Parlato = parole + eventi audio che non sono in `dead_events` (es. `[esita]` è una parte
  morta, `(risata)` no).
- Una pausa si toglie se dura almeno la soglia; restano `margin_ms` per lato attaccati al
  parlato (in testa e in coda al video nessun margine verso il bordo).
- I segmenti coprono tutto l'asse senza buchi. Id: `gap:<prima>-<dopo>` e `seg:<prima>-<ultima>`.
- `cuts --set` cambia solo `pauses.*`, `transcription.audio_events` e
  `transcription.dead_events`; il valore usato resta nella timeline.

### Trascrizione

- Audio estratto con ffmpeg (prima traccia audio, mono 16 kHz FLAC) in `projects/<nome>/work/`.
- Inviato a ElevenLabs Scribe (`scribe_v2`, italiano, tempi per parola, eventi audio,
  `temperature=0`, `seed=0`). Chiave da `ELEVENLABS_API_KEY` (ambiente o `.env`).
- Risposta grezza salvata in `projects/<nome>/transcript/scribe-<chiave>.json`: la chiave
  dipende da impronta del file camera, tratto, parametri di estrazione e richiesta. Se nulla
  cambia, non si ripaga; `--force` la rifà.
- Con `--range` passa lo stesso valore usato in `ingest`; i tempi restano assoluti sull'asse camera.
- Rilanciarla svuota segmenti e ripetizioni (vanno ricalcolati).

### Opzioni di `ingest`

Al posto della cartella si può passare direttamente un video: diventa la camera, senza schermo
(es. `autocut ingest prova "D:\raw\IMG_1234.MOV"`).

- `--camera F` / `--screen F`: scelta manuale (nome nella cartella o percorso).
  `--camera` da solo = nessuno schermo; `--screen` richiede `--camera`.
- `--profile long|short`: se manca, orizzontale → `long`, verticale → `short`.
- `--range 60-180` (anche `1:00-3:00`): prova su un tratto; scrive in
  `projects/<nome>__range_60-180/`, separato dal progetto vero.
- `--set chiave=valore` (ripetibile), es. `--set pauses.threshold_ms=900`.

Exit code: `0` ok, `1` errore, `2` riconoscimento ambiguo (non scrive niente, elenca i
segnali di ogni file e chiede `--camera`/`--screen`).

### Riconoscimento dei file

A punteggio, con i segnali scritti in `timeline.json` (`detection`):

- camera: tag `com.apple.quicktime.make=Apple`, modello iPhone, nome `IMG_xxxx`, `.mov`, 4K;
- schermo: nome con data e ora, `.mkv`, encoder OBS/Lavf, nessun metadato mobile,
  risoluzione da monitor.

Un ruolo è assegnato solo se ha punteggio ≥ 3 e l'altro ≤ 1. Con un solo video, è la camera.
Con più video servono esattamente una camera e uno schermo riconosciuti, altrimenti si ferma.
Vengono ignorati (e annotati) file non video, nascosti e i `._*` di macOS.

Variabile `AUTOCUT_PROJECTS_DIR`: sposta la cartella dei progetti (default `<repo>/projects`).

## File

- `profiles.toml`: profili `long` / `short` (soglia pause e margini) e default comuni.
- `schemas/`: JSON Schema di `timeline.json` e `overrides.json`, generati da `src/autocut/models/`.
- `projects/<nome>/`: tutto ciò che il motore produce. Escluso da git.
  Da portare tra laptop: `timeline.json`, `overrides.json`, `transcript/`. `work/` si rigenera.

## Regole

- I file raw sono in sola lettura: mai modificati, spostati o ricodificati.
- Tempi in millisecondi interi, asse master = tempo della camera.
- Deterministico: stessi file + stesse impostazioni = stessa timeline (nessun timestamp di esecuzione).
- Le prove sui video veri si fanno con `--range`, mai sul file intero.

## Test

```bash
uv run pytest
uv run ruff check .
```
