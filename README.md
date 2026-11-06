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
- **Schermo intero** (pulsante sotto il lettore, tasto `F` o doppio clic sul video): il montato
  in grande, a forma di telefono se verticale o 16:9 se orizzontale, con barra di scorrimento,
  play/pausa, Montato/Raw (in Raw le parti tolte sono in rosso) e sottotitoli; `Esc` per uscire;
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

### Pannello Testo

Scheda **Testo** a sinistra (e pulsante *Testo* nello schermo intero), con uno stile attivo:
- **font** da Google Fonts: 14 per *Viral* (Anton, Bebas Neue, Lilita One, Bangers…) e 14 per
  *Premium* (Playfair Display, Instrument Serif, Inter, Manrope…), visibili in base al preset.
  *Testo* / *Parola chiave* per mischiare due font (es. un serif sulla parola chiave);
- **stile** (Contorno, Ombra, Ombra netta, Neon, Box, Pulito), grassetto, corsivo, maiuscole;
- **colori** del testo, della parola chiave e di contorno/box/neon (tavolozza + colore libero);
- **testo della scena**: riscrivi la frase sotto la testina (Invio per salvare);
- **nel video**: clicca il testo, trascinalo, ingrandiscilo dagli angoli, ruotalo con la maniglia
  sotto (calamita sul centro e su 0°/90°). Anche nello schermo intero.

*Tutti i sottotitoli* o *Solo questa scena* decide dove va la modifica. Le scelte stanno in
`projects/<nome>/text_style.json`, separate per stile, e il render Remotion le usa uguali.

### Pannello Sticker

Scheda **Sticker** a sinistra (e pulsante *Sticker* nello schermo intero): libreria per stile
(emoji ed etichette *Viral*, numeri ed emoji sobrie *Premium*, più le tue immagini AI), testo o
emoji personalizzati. Si aggiungono alla testina, approvati, solo per lo stile attivo.
Clicca uno sticker nel video (anche i pop-up proposti da Claude) per spostarlo, ingrandirlo
dagli angoli e ruotarlo; nel pannello: **Dietro al testo / Davanti al testo / Dietro la
persona**, grandezza, rotazione, durata, *Inizia qui*, suono, *Elimina* (o tasto Canc).
Gli sticker messi a mano (`placement: "free"`) restano a schermo insieme agli altri.

**Emoji stile iPhone** (`library/emoji/`, fuori da git): tutte le emoji della tastiera (1.653,
per categorie) estratte dal font Apple Color Emoji a 96 px, usate in editor e render al posto
del font Noto. **Sono disegni di Apple: solo per uso personale, non nei video dei clienti.**
Per ricrearle su un altro PC vedi `tools/extract_emoji.py`; senza la cartella si torna al font.

### Pannello Immagini

Scheda **Immagini** a sinistra (e pulsante *Immagini* nello schermo intero): scrivi chi o cosa
ti serve («trovami delle immagini di Francesco Totti» → cerca «Francesco Totti») e l'editor
cerca sul web come il browser (Bing Immagini). Clicchi una foto: viene scaricata, **scontornata
in locale** e messa nel video dove c'è la testina, in basso appoggiata al bordo; poi la sposti,
la ingrandisci, la ruoti e le dai entrata e uscita come uno sticker. Le immagini le mette solo
l'utente: Claude non le inserisce mai da solo.
- **Scontorno** sul processore, gratis e senza account: *Rapida* (ISNet, ~2 s) o *Massima*
  (BiRefNet leggero, ~20 s, capelli e bordi molto più puliti). Sulla foto selezionata puoi
  rifarlo in qualità massima o tornare alla *Foto intera*. I modelli (~180 e ~220 MB) si
  scaricano da soli la prima volta in `library/models/` (fuori da git).
- Filtri: *Già trasparenti* (solo PNG senza sfondo), *Licenza libera* (Wikimedia Commons, con
  autore e licenza), *Dal PC* (anche trascinando il file nel pannello).
- I file stanno in `projects/<nome>/work/images/` (originali in `src/`, provenienza in
  `index.json`) e restano in **Le tue immagini** per riusarli.

Le foto del web hanno quasi sempre un copyright: per i video da pubblicare preferisci
*Licenza libera* o foto tue.

### Pannello Effetti

Scheda **Effetti** a sinistra (e pulsante *Effetti* nello schermo intero), tre sezioni:
- **Testo**: entrata e uscita dei sottotitoli (pop, parola per parola, rimbalzo, macchina da
  scrivere, emersione, messa a fuoco…), con la durata;
- **Sticker**: entrata, uscita e loop (galleggia, pulsa, battito, dondola, trema…) per tutti
  gli sticker o solo per quello selezionato, con durata e velocità;
- **Transizioni**: a ogni giunta tra due clip (rombo nella timeline) — ufficiali di
  `@remotion/transitions` (fade, slide, wipe, cube, flip, iris, orologio, push cut) e in stile
  CapCut (zoom, whip, flash, dissolvenza sfocata, passaggio al nero). I punti vengono da tagli e
  cambi di inquadratura (differenza tra i fotogrammi, ffmpeg); serve un po' di girato oltre il
  taglio, quindi la durata si accorcia da sola se manca.

Ogni stile ha la sua galleria (*Premium* morbida, *Viral* d'impatto) e i suoi valori di partenza.
La prima volta che apri Effetti, Claude compone il preset guardando parlato, tagli e sticker;
*Fai scegliere a Claude* lo rifà (le transizioni scelte a mano restano). Le scelte stanno in
`projects/<nome>/effects.json`. Il motore delle animazioni è `motion/src/anim.js`, lo stesso per
editor e render; nell'anteprima le transizioni sono approssimate, nel render sono quelle vere.

### Brand pack

`brands/<id>/brand.json`: palette, font (Google Fonts o locali), stile dei sottotitoli con
parola chiave evidenziata, lower third, stile grafico, transizioni e livelli del sound. Si sceglie
dal menu **Brand** in alto (salvato per progetto); la scheda **Brand** a sinistra lo mostra.
Il brand attivo viene passato anche a Claude quando suggerisce o genera con Higgsfield.
Esempi: `federico` (premium tech scuro) e `editoriale-chiaro`. Dettagli in `brands/README.md`.

### Preset di stile (Premium / Viral)

`styles/<id>/style.json`: la grammatica del montaggio, separata dal brand (brand × stile si
combinano liberamente). Ritmo e punch-in, look del colore, sottotitoli (posizione, grandezza,
gerarchia, animazione), hook-copertina dei primi 3 s (centrato: aggancio piccolo, riga GRANDE,
sottotitolo), card dei pop-up, suoni. Si sceglie dal menu **Stile** in alto.
- `premium`: camera fissa, look cinematografico, parola chiave bold su una riga sua, card di
  vetro, grafiche che possono passare *dietro* la persona.
- `viral`: jump cut con zoom secchi, colori saturi, sottotitoli piccoli e bassi in minuscolo,
  emoji e sticker.

Anteprima sul video vero, renderizzata con Remotion (zero crediti):
```
uv run autocut style-preview <nome> --at 39.8 --style viral --hook "A 25 anni|MOLLO TUTTO|e vado in Thailandia"
uv run autocut style-preview <nome> --at 22.5 --before 0 --after 18 --style premium --clip
```
PNG o MP4 in `projects/<nome>/renders/`.

### Pop-up

`projects/<nome>/popups.json`: elementi che compaiono quando dici una parola (immagine, emoji,
numero/parola), con posizione (`side`, `above`, `pair`, `center`, `top`, `behind`) e grandezza.
Quando scegli uno stile, Claude analizza il parlato e li propone da solo, con parsimonia (tetto
in base alla durata e distanza minima). Nella scheda **Pop-up** li approvi/rifiuti, accendi o
spegni il suono, generi le immagini con Higgsfield (solo su conferma: costa crediti) e chiedi
modifiche in chat. Le grafiche `behind` usano una sagoma della persona calcolata in locale con
MediaPipe (ambiente separato Python 3.12, scaricato da `uv` la prima volta).

### Sound design

Skill di progetto `autocut-sound-design` (`.claude/skills/`), basata sulle regole in
`UE-Sound-Design-Claude-Training-COMPLETE.md` (documento locale, non versionato). Libreria suoni
in `library/sfx/` (non versionata): `whooshes/`, `textures/`, `risers/`, `hits/`, `music/`.
`autocut sfx generate` crea con ElevenLabs tutti i suoni del documento (30 tipi, 71 varianti,
~4.700 crediti) e scrive `library/sfx/catalog.json`; vedi `library/README.md`.

Nel render la voce viene portata a −14 LUFS e ogni effetto sta 15–20 dB sotto la voce
(`relative_db` dello stile). I suoni partono solo sui momenti chiave: hook, pop-up con il suono
acceso, una parola chiave ogni tanto, veri cambi di blocco. Il picco è allineato al fotogramma
in cui l'elemento compare. Con il piano gratuito ElevenLabs i suoni non si possono usare per
lavori commerciali: per i clienti serve un piano a pagamento (poi `autocut sfx generate --force`).

### Motion graphics (Remotion)

In `motion/` c'è un progetto Remotion 4 (Node richiesto). `npm install` una volta, poi
`npm run studio` per l'anteprima. Remotion è gratuito per singoli e aziende fino a 3 persone;
oltre serve la licenza aziendale.

L'editor scrive solo `overrides.json`, `editor_state.json` (proposte riviste, brand, stile),
`ai_requests.json`, `popups.json`, `text_style.json` e `effects.json`. Rilanciando `cuts`, le scelte senza più una proposta diventano orfane.

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
