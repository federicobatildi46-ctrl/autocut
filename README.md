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
| `autocut editor <nome> [--port 8765]` | Apre l'editor visivo in locale nel browser |
| `autocut export-schemas` | Rigenera `schemas/*.schema.json` dai modelli |

In arrivo: `sync`, `repeats`, `validate` e `raw` (tutto il giro).

### Editor visivo (locale)

`autocut editor <nome>` prepara in `projects/<nome>/work/` un proxy H.264 leggero (i raw
HEVC 10 bit HDR dell'iPhone non sempre si riproducono nel browser), le miniature e la forma
d'onda, poi apre `http://127.0.0.1:8765/`. Layout in stile CapCut:

- **lettore** con modalità *Montato* (salta le parti tolte) e *Raw*, sottotitoli in anteprima;
- **timeline** con righello, sottotitoli, striscia video, forma d'onda e tagli (zoom con
  `Ctrl`+rotella, trascina la testina);
- **Modifiche AI**: ogni proposta con il commento e il motivo; *Approva*, *Rifiuta, tieni*,
  *Ascolta* (2 s prima e dopo), *Annulla* (`Ctrl+Z`). Le scelte vanno in `overrides.json`
  con la cronologia; la timeline non viene mai riscritta;
- **Potenzia ✦**: *Suggerisci* fa guardare a Claude il frame e il parlato intorno e propone
  video, immagini o grafiche AI; *Invia* esegue subito la generazione con Higgsfield. L'editor
  lancia Claude Code in background (`claude -p`, con il tuo account) che usa la skill
  `higgsfield-generate` e la CLI `higgsfield`, con soli permessi Read, Skill e comandi
  `higgsfield`. Prima di generare stima il costo e si ferma oltre il tetto (6 crediti per
  immagini e grafiche, 40 per i video; variabili `AUTOCUT_AI_BUDGET_IMAGE` e
  `AUTOCUT_AI_BUDGET_VIDEO`). I risultati finiscono in `projects/<nome>/work/ai/results/`
  e in `ai_requests.json`.

  Una volta per laptop (in PowerShell; `--use-system-ca` serve dietro antivirus/proxy TLS):

  ```bash
  claude auth login
  $env:NODE_OPTIONS = "--use-system-ca"; npm i -g @higgsfield/cli
  higgsfield auth login
  higgsfield workspace list        # poi: higgsfield workspace set <id>
  npx -y skills add higgsfield-ai/skills   # nella cartella del repo
  ```
- **Sottotitoli di anteprima** (non bruciati): in verticale ~5% della larghezza (54 px su
  1080), max 4 parole e 2 righe, dentro l'area sicura (Meta: 14% sopra, 35% sotto, 6% ai
  lati; più margine a destra per i pulsanti TikTok). Pulsante *Area sicura* per vederla.

### Motion graphics (Remotion)

In `motion/` c'è un progetto Remotion 4 (Node richiesto). `npm install` una volta, poi
`npm run studio` per l'anteprima. Remotion è gratuito per singoli e aziende fino a 3 persone;
oltre serve la licenza aziendale.

L'editor scrive solo `overrides.json`, `editor_state.json` (proposte riviste) e
`ai_requests.json`. Rilanciando `cuts`, le scelte senza più una proposta diventano orfane.

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
