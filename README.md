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

### Timeline: testo, tagli, Annulla / Ripeti

- **Clic su una frase** (blocchi rossi in alto): si apre il pannello Testo su quella scena con il
  testo già selezionato; scrivi e premi Invio. Le frasi modificate hanno ✎ e la timeline mostra
  il testo nuovo.
- **Dividi** (forbice nella barra, o Ctrl+B) alla testina; clicca un pezzo e **Togli** (Canc).
  Un pezzo tolto da te è arancione: cliccalo e *Ripristina*. Clic su una linea di divisione
  per toglierla. Sta in `projects/<nome>/cuts.json`, sopra le scelte del motore (che restano).
- **Annulla / Ripeti** (in alto e nella barra; Ctrl+Z, Ctrl+Y o Ctrl+Maiusc+Z) valgono per
  tutto: tagli, testo, sticker, immagini, effetti, audio e stile. `overrides.json` resta
  append-only (l'annulla aggiunge voci, non riscrive). Le pile durano finché l'editor è acceso.

### Pannello Audio

Scheda **Audio** a sinistra (e pulsante *Audio* nello schermo intero) e **traccia audio** sotto il
video nella timeline, con i suoni che lo stile mette da solo (pop sugli sticker, whoosh sui
cambi di blocco…) e quelli aggiunti da te.
- **Voce**: volume rispetto al livello già normalizzato del render, o muta.
- **Effetti sonori**: volume di tutti insieme, o tutti muti.
- **Ogni suono**: clic nella traccia (o nella lista) → ascolta, volume, muto, *Cambia suono*,
  *Sposta qui*, ◀ ▶ di 0,1 s, oppure trascinalo nella traccia. Canc lo mette muto (o elimina
  quelli aggiunti da te).
- **Aggiungi un suono alla testina** dalla libreria `library/sfx`, con anteprima ▶.

Nell'anteprima dell'editor senti voce ed effetti con gli stessi livelli del render. Le scelte
stanno in `projects/<nome>/audio.json` (per stile); il render usa lo stesso elenco di suoni.

### Esporta: copertine Shorts e YouTube

Il tasto **Esporta** in alto apre l'anteprima delle copertine: **Shorts 9:16** (nel telefono) e
**YouTube 16:9** (come appare nel feed, con titolo, canale, durata e miniatura piccola).
- **Persona**: nome, Soul ID del personaggio allenato su Higgsfield (tuo o del cliente) e foto
  frontale del volto, che tiene la stessa identità.
- **Di cosa parla il video** → *Proponi con Claude*: frase (riga piccola + scritta grande) e
  sfondo legati al tema. Tutto si corregge a mano.
- **Genera / Rigenera**: Soul 2 mette la persona nella scena con luce da copertina, poi GPT
  Image 2 impagina scritta e sfondo in 4K (~11 crediti, parte solo dopo *Conferma*). Ogni
  versione resta: clicca una miniatura per sceglierla, *Scarica* per il PNG.
- Serve la CLI Higgsfield collegata: lo stato è in alto nella finestra, con **Ricollega** se
  la sessione è scaduta (l'editor acceso la rinnova da solo ogni 20 minuti).
- **Stile Viral**: solo la copertina verticale, gratis e in locale (Remotion, ~10 s): un
  fotogramma del video (l'apertura o quello della testina) + la frase d'esordio al centro con
  il font, il contorno e l'ombra dell'apertura del video, riga piccola nel colore scelto, 0-2
  emoji iPhone ai lati. Claude propone la frase senza inventare fatti.
- File in `projects/<nome>/covers.json` e `work/covers/`.

### Pannelli Filtri e Transizioni

- **Filtri**: il colore del video sopra il look dello stile. Preset (Naturale, Vivido, Caldo,
  Freddo, Cinema, Pastello, Bianco e nero) con anteprima sul fotogramma, e cursori per
  luminosità, contrasto, saturazione, calore, tinta e vignetta. Vale nell'anteprima, nel render
  e nella copertina Viral; per stile, in `projects/<nome>/filters.json`.
- **Transizioni**: le giunte tra le clip con la loro transizione (lo stesso motore del pannello
  Effetti), anche dal rombo nella timeline.

### Esporta video

Nella finestra **Esporta**, *Esporta video* fa il render del video intero con tutto quello che
hai fatto (tagli, testo, sticker, immagini, effetti, audio, filtri) e mette la copertina scelta
dentro il file MP4 come miniatura. Qualche minuto per un minuto di video; il file finisce in
`projects/<nome>/renders/<nome>-<stile>-finale-<data>.mp4` e si scarica dalla finestra.

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

### Importa un raw, Salva e Annulla

- **File multimediali → Importa un video**: scegli un file dal PC (o uno scaricato da iCloud) o
  premi «Cerca nei Download e iCloud». Il video si copia in `raw/<progetto>/` (l'originale non si
  tocca) e parte il premontaggio: ingest, trascrizione (ElevenLabs Scribe, a pagamento), tagli
  delle pause. A fine lavoro «Apri il progetto» riavvia l'editor sul progetto nuovo.
- **Salva** (in alto, o Ctrl+S): ogni modifica è già salvata; qui fissi una *versione con nome*
  (`versions/`) a cui torni quando vuoi, anche dopo aver chiuso l'editor. Ripristinare si può
  annullare. **Annulla/Ripeti** ora sopravvivono ai riavvii (`work/history.json`, ultimi 60 passi).
- Le icone a sinistra della timeline sono cliccabili: testo (modifica la frase sotto la testina),
  clip (seleziona la clip sotto la testina; 🔊 muta la voce), audio, Genera AI, B-roll.

### B-roll e voice-over

Scheda **B-roll** (a sinistra, e nello schermo intero): carichi video o foto (anche più file, o
trascinandoli sul pannello) e vanno **sopra la ripresa** dalla testina; la voce di chi parla
continua. Durata e punto di partenza del video si regolano nel pannello; i blocchi azzurri nella
timeline si trascinano per spostarli. Nella scheda **Audio** la carta **🎤 Voice-over** carica una
registrazione fatta col telefono (m4a, mp3, wav…): parte dalla testina, ha il suo volume e può
**zittire la voce della ripresa** mentre parla (blocchi arancioni). Tutto in `broll.json`
(file in `work/broll/` e `work/voiceover/`), con Annulla/Ripeti; nell'export il B-roll è cucito
con ffmpeg nell'estratto della camera e il voice-over è una traccia di Remotion. I tempi sono
sull'asse della camera: restano giusti se cambi i tagli.

### Musica di sottofondo (libreria gratuita Audio Library di YouTube)

Pannello **Audio → 🎵 Musica di sottofondo**. I brani vengono solo dal canale YouTube
[Audio Library](https://www.youtube.com/@audiolibrary_) (oltre 4000, gratuiti anche per video
monetizzati con i crediti in descrizione):
1. il catalogo (titoli con mood, genere e uso) si scarica con yt-dlp in `library/music/catalog.json`
   e si aggiorna una volta a settimana;
2. Claude legge il parlato del video (o del tratto scelto) e lo stile e decide il mood; dai titoli
   più vicini sceglie 5 brani; dalle sezioni di ogni brano («1:45 Minimalist calm section»)
   sceglie da dove farlo partire. I 5 brani vengono scaricati subito (`library/music/files/`),
   così li ascolti con ▶ e li metti con *Usa*;
3. **premontaggio**: appena c'è uno stile, la musica consigliata va da sola su tutto il video
   (una volta per stile; se la togli non torna);
4. ogni musica ha volume (rispetto al livello dello stile: `music_db`, di base 19 dB sotto la voce
   normalizzata, misurando la loudness del brano), muto, punto di partenza, tratto (*Tutto il
   video* oppure *Da qui* / *A qui* con la testina), *Rigenera*, *Togli*; si vede come barra verde
   nella traccia audio e suona nell'anteprima e nel render (loop se il brano è più corto);
5. **Cerca nella libreria** per parola (es. «motivational cinematic») e *Usa* qualsiasi brano;
6. **Crediti da incollare nella descrizione**: il blocco che il canale chiede, pronto da copiare.

Dalla chat *Chiedi a Claude* puoi anche dire «musica solo in questa clip» o «abbassala qui».
File: `projects/<nome>/music.json` (con Annulla).

### Chiedi a Claude (chat collegata a Claude Code)

Pulsante **Chiedi a Claude** in basso a destra: una chat dentro l'editor, con due modalità.

- **Edita il video**: premi *Seleziona sulla timeline* (la timeline si illumina), trascina su un
  tratto o clicca un fotogramma, poi scrivi cosa vuoi («la scritta più grande con bagliore e
  fade», «sotto la frase l'emoji del pianto»). Claude Code lavora su copie dei file del
  progetto (pop-up, testi, effetti, filtri, tagli, audio) seguendo
  `src/autocut/editor/assistant_guide.md`; l'editor le convalida e le applica tutte insieme:
  **un solo Annulla** le toglie. Se manca uno strumento lo dice, con il pulsante *Aggiungilo
  all'editor*.
- **Modifica l'editor**: chiedi una funzione nuova («una scheda per…»). Claude Code cambia il
  codice del repo come in una sessione normale (niente commit, push, `.env`), lancia ruff e i
  test, e nella chat vedi i passi e il tempo. Alla fine la pagina si ricarica; se è cambiato il
  Python l'editor **si riavvia da solo** (`autocut editor` fa da supervisore: uscita 75 =
  riavvio). *Annulla modifiche* rimette il codice com'era (fotografia git + copia dei file non
  ancora in git, senza mettere niente in stage).

La conversazione continua fra un messaggio e l'altro (`claude -p --resume`) ed è salvata in
`projects/<nome>/claude_chat.json`. Usa il tuo account Claude Code; nessun credito Higgsfield.

### Genera AI (Genera con Higgsfield)

Scheda **Genera AI** a sinistra (e pulsante *Genera AI* nello schermo intero): metti la testina
nel punto giusto, scegli la durata (max 3 s), scrivi cosa vuoi vedere («dietro di me compare un
dragone che sputa fuoco») e premi *Genera*. L'AI modifica **la tua ripresa vera**, non la
reinventa da un fotogramma:
1. l'editor prende quei secondi dal raw (4 s, il minimo di Seedance);
2. Claude con la skill `higgsfield-vfx` (`.claude/skills/higgsfield-vfx/`) guarda il frame e
   scrive il prompt video-to-video (scena, ruoli dei riferimenti, azioni coi secondi, blocchi su
   volto/voce/camera); se serve genera prima un'immagine di riferimento (Soul 2.0, 0,12 crediti);
3. Seedance 2.0 a 480p con **audio spento**: prima stima i crediti, sopra i 6 non genera;
4. in locale: allineamento al fotogramma, colori presi dal video, **persona vera rimessa sopra**
   se *Proteggi la persona* è attivo (volto e bocca restano al 100% tuoi): sagoma con Robust
   Video Matting (modello ~15 MB scaricato la prima volta in `library/models/`, licenza
   GPL-3.0, uso locale), ricostruzione della scena AI nella striscia dove l'AI ti aveva
   disegnato più largo (niente alone), luce della scena sul tuo bordo; la clip si allunga da
   sola fino a dove l'effetto finisce davvero (max 4 s), poi dissolvenza;
5. Claude rivede il prima/dopo (ok / da correggere con prompt corretto / non va bene).

**Automatica (predefinita): Claude fa da regista e smista.** Scrivi la richiesta come la diresti
a voce; Claude la completa con le 5 domande del regista (camera, tono, chi/cosa/perché, luce,
texture e interazione), se manca qualcosa di essenziale **ti fa 1-3 domande nella scheda prima di
spendere** (*Rispondi e genera* oppure *Genera così*), poi sceglie la ricetta
(`knowledge/higgsfield-router.md`):
- **effetto** attorno a te (drago, fuoco, cielo): Seedance 2.0 720p + upscale, persona vera
  rimessa sopra (~12 crediti);
- **cambio vestiti / oggetto**: Genjutsu Lite 720p + foto del vestito (GPT Image) + upscale, solo
  la **testa vera** rimessa sopra (volto da MediaPipe in locale + sagoma RVM) (~10,5 crediti);
- **trasformazione** (alieno, robot): Genjutsu Lite, la persona è quella dell'AI (~10,5 crediti).
Le qualità manuali restano in *Avanzate*.

Con la qualità *Migliore sul piano Starter* la clip AI a 720p viene portata a 1080p con
l'upscaler ByteDance di Higgsfield (preset `aigc`, ~1-2 crediti) prima del composito.
*Elimina* sposta i file della clip nel cestino del progetto (`work/vfx/_cestino/`), non li
cancella.

Poi *Metti in timeline*: la clip compare nella traccia ✦, si vede nell'anteprima e il render la
cuce dentro il video (la voce è sempre l'originale). *Rigenera corretta* usa il prompt sistemato
da Claude. Costo tipico: ~12 crediti a tentativo con la ricetta Starter 720p + upscale (*Bozza 480p*: ~4). Studio e regole in
`knowledge/higgsfield-vfx.md`. File in `projects/<nome>/vfx.json` e `work/vfx/<id>/`.

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
