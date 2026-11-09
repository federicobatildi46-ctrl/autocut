# Knowledge: VFX AI su riprese reali con Higgsfield (bozza)

Fonti: Enne Agency (3 short), Higgsfield YouTube (4), Academy AI Creation lezioni 1-5 + PDF,
Academy "Add AI VFX to Real Footage" / "Mix AI & Real Footage" (lezioni gratuite).

## Perché il dragone è venuto male (ai_0002, 2026-11-09)
- Kling 3.0 image-to-video dal frame: il modello ri-anima tutta l'inquadratura -> volto deriva, bocca e voce inventate (inglese).
- generate_audio acceso -> parlato nuovo; nessun "voice lock".
- Nessuna revisione del risultato ("non ho guardato il video").
- Seedance 2.5 non disponibile sul piano attuale (serve Pro).

## Regole d'oro
1. La persona non si rigenera mai se non serve: il soggetto originale va SOPRA la clip AI (scontorno), come in CapCut "duplica clip + rimuovi sfondo".
2. Audio sempre quello originale. generate_audio=false (o solo SFX, mixati da noi).
3. Video-to-video > image-to-video quando si parte da una ripresa reale (Seedance 2.5 mode=video_edit, Kling 3.0 Omni Edit).
4. Frame di partenza esatto, poi allineamento al frame e micro-color.
5. Camera ferma = composito facile; camera a mano = video_edit sul clip intero.
6. Bozza 480p (draft) -> scegli -> 1080p identico via draft_job_id (metà crediti).
7. Ogni take si rivede: azione, continuità, camera. Errore che ritorna = sistema asset/prompt, non ritentare a caso.

## Struttura prompt (Seedance / Academy)
Primo 20% del prompt pesa di più.
1. SCENE CONTEXT & STYLE - cosa succede, stile, fisica del mondo.
2. REFERENCES - ogni riferimento con un ruolo ("@video_1 = ripresa reale: tieni persona, camera, luce identiche";
   "@image_1 = aspetto del drago"). "Characters, environments and props must match the reference exactly."
3. SHOTS / TIMING - azioni in ordine con secondi (0-1 s, 1-3 s...). Dimensione/angolo/movimento separati.
4. LOCKS & CONSTRAINTS - non cambiare volto/espressione/bocca, niente parlato, niente musica, niente persone in più,
   camera come nell'originale, durata esatta.
5. SOUND - SFX diegetici o nessuno; la voce resta quella vera.
Riparazione: "Revise the tested prompt... What went wrong / What I want / keep what works / list changes".

## Modelli (CLI job_type)
- seedance_2_5: t2v | omni_reference | video_edit | video_extension; image/video/audio refs; draft; generate_audio; 480/720/1080p. (Pro)
- kling_video_edit (Kling 3.0 Omni Edit): video_references + image_references + prompt.
- kling_o3_flf: primo/ultimo frame.
- hf_mult_replace_object (Genjutsu): sostituire oggetti/vestiti nel video.
- sam_3_video / video_background_remover: scontorno video lato Higgsfield.
- Immagini: Soul 2.0 / Soul Cinema = realismo (economici); Seedream 5.0 Pro = edit mantenendo texture;
  GPT Image = testo/grafiche/layout precisi; Nano Banana = look AI più evidente.

## Lezioni Academy "Add AI VFX to Real Footage" (Seedance video-to-video)
- "The one move": clip grezza + UNA frase -> Seedance edita la ripresa vera; output pulito da mettere in timeline.
- Tre livelli: 1) cambiare il mondo attorno (sfondo); 2) cambiare UN elemento nel frame (fuoco sulla testa,
  mano che diventa serpente, creatura dietro); 3) showcase cinematografico a mano libera.
- Creatura (= il nostro dragone): genera PRIMA l'immagine della creatura (GPT Image / Soul) e passala come
  riferimento: "meglio mostrare che descrivere". Poi clip + riferimento + cosa deve fare.
  Si può chiedere anche un movimento di camera mai girato (zoom out/reveal) mantenendo il lip sync.
- Fuoco sulla testa: il modello blocca volto, espressione, luce e aggiunge solo l'effetto, con la luce
  dell'effetto che si riflette su pelle/vestiti (cosa che il composito puro NON fa).
- Mano-serpente: "change one thing" + aggancio al momento della frase ("quando dico X") +
  "keep talking like nothing happened till the end" -> blocca volto, voce, performance, camera; tocca solo il braccio.
- Aggiungere una persona: edit video + character sheet + "add an old man".
- Higgsfield ha un plugin per montare dentro Premiere sulla timeline (stessa idea del nostro bottone).

## Enne Agency (flusso CapCut, veloce)
- Annota l'idea mentre giri; in montaggio scegli il frame dove parte l'effetto, taglia, esporta.
- Libreria preset Higgsfield (es. effetti pronti) oppure prompt dettagliato scritto con Claude/ChatGPT.
- Importa in timeline, ALLINEA AL FRAME, micro-color, fatto.
- Elementi in movimento: camera ferma (cavalletto) per evitare tracking; piano vuoto senza soggetto;
  primo/ultimo frame (Runway/Kling FLF) per far "comparire" un oggetto; poi clip originale duplicata
  SOPRA + rimozione sfondo -> soggetto perfettamente integrato.
- Cambio outfit: Genjutsu (video + foto dei vestiti + prompt dettagliato).

## Short drama / voce (Higgsfield)
- Voce: descrivere l'accento nei dettagli (es. "soft uvular R" per il francese); dare a ogni personaggio una
  descrizione della voce e riportarla in ogni scena. Per noi: generate_audio=false e voce originale.
- Character sheet: sfondo grigio, 3 viste, cancellare il volto piccolo nella vista intera (un solo volto di riferimento).
- Location 3/4 per coerenza tra angoli; oggetti "àncora" (es. il boccale) per posizionare le azioni.

## Blender + AI (Higgsfield animation)
- "Assets first": la qualità delle immagini in ingresso decide la qualità del film.
- Previs in Blender (grigio, solo camera + movimento) come video di riferimento quando spiegarlo a parole è più lungo.
- Se il modello non capisce il riferimento: allarga l'inquadratura. Riferimenti incoerenti (cuffie mancanti) -> correggi l'asset.
- I dettagli fini di recitazione sono la cosa più difficile per l'AI: non affidarle il volto se non serve.

## Composito: cosa abbiamo imparato dai test (2026-11-09)
- Seedance video-to-video RIDISEGNA la persona un po' più larga (~20 px sulla testa) e disegna
  la creatura attorno a QUELLA sagoma. Rimettendo sopra la persona vera resta una striscia:
  se la riempi col muro vero esce un alone chiaro e la creatura sembra "tagliata" vicino a te.
- Soluzione: scontorno video Robust Video Matting (capelli precisi, stabile nel tempo) su clip
  vera e clip AI; la striscia "persona AI fuori dalla vera" (solo alpha AI > 0.5, entro 20 px)
  si ricostruisce: muro vero riilluminato dove dietro c'è muro, ricostruzione push-pull dove c'è
  la creatura. Lo scontorno vede in parte anche la creatura come primo piano a bassa confidenza:
  mai usarne la parte sfumata, se no si cancella la creatura vicino alla persona.
- MediaPipe (metà risoluzione, media mobile) è troppo morbido e in ritardo per questo lavoro.
- Seedance allunga l'azione su tutti i 4 s: la clip finale si allunga fin dove l'effetto finisce.
- Light wrap: il bordo della persona prende la luce della scena AI (fuoco = bordo caldo).

## Test sul piano Starter (2026-11-09, 720p Fast, ~10 crediti a tentativo)
- Il 4K/1080p (Seedance 2.0 std) e Seedance 2.5 richiedono il piano "Pro"/"Ultimate":
  rifiutati prima di generare, nessun credito scalato.
- 720p Fast: la persona viene ancora ridisegnata (fedeltà 6,2-7,4; identica ~4) -> serve la
  protezione; dietro la testa AI più larga va ricostruito a intuito: con la creatura dietro la
  testa resta una zona chiara.
- Senza vincoli il drago c'era già al primo fotogramma e restava all'ultimo (2 tentativi).
  Con start_image/end_image = primo e ultimo fotogramma veri: inizio e fine puliti, ma il modello
  Fast fa comparire/svanire la creatura in trasparenza.
- "Dragone cinese" va descritto come loong serpentino: senza, usciva un drago in piedi
  stile Godzilla.

## Test API (2026-11-10)
- API a consumo (chiave in .env, SDK higgsfield-client): Seedance 2.5 Video Edit
  "bytedance/seedance-2.5/video-edit" (vera modifica, max 1080p, niente start/end frame, durata
  dalla clip); si pagano secondi in ingresso + generati. 720p 9:16 4 s ≈ 2,22 $, 1080p ≈ 5,46 $.
  Seedance 2.0 4K via API esiste solo come "reference-to-video" (rigenera: sbagliato per noi).
- 2.5 Edit 720p: drago bellissimo e luce del fuoco sul viso, ma la bocca e la testa si muovono
  un po' diversamente (forma del volto 0,64 contro 0,39 del 720p Fast con fotogrammi vincolati).
- Metrica di fedeltà: confrontare forme (gradienti normalizzati sul volto), non colori: la luce
  del fuoco sul viso non è un cambiamento di identità.
- Composito: i pixel AI attaccati al contorno vero (~12 px) vanno LASCIATI (sono capelli e bordo
  che si fondono); sostituirli col muro creava l'alone chiaro. Si ricostruisce solo la persona AI
  staccata (testa fantasma). Il flusso ottico per deformare la scena AI è stato provato e scartato
  (linea chiara attorno alla testa).

- Entrata "trasparente" (segnalata dal creator): NON era il modello. La clip grezza aveva il
  drago solido; lo scontorno della clip AI vede la creatura che tocca la testa come "persona" e
  la ricostruzione la cancellava. Ora si ricostruisce solo nei fotogrammi dove la forma del volto
  AI si è davvero spostata (mediana su 5 fotogrammi > 0.8: i picchi isolati ogni 5 fotogrammi
  vengono dalla conversione 24 -> 30 fps). Verifica obbligatoria prima di accusare il modello:
  confrontare la clip grezza con il risultato negli stessi istanti.

## Anti-slop
Texture plastiche, nitidezza eccessiva, pattern ripetuti, riflessi distraenti, ombre nere senza dettaglio,
volti "medi" idealizzati. Profondità: elemento in primo piano sfocato. Luce leggibile (direzione coerente col frame).
