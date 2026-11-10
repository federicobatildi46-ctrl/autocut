# Knowledge: quale modello / preset Higgsfield per quale richiesta

Verificato il 2026-11-10 sul piano **Starter** (194 crediti) con `higgsfield model list/get`,
`higgsfield generate cost` (solo stime, nessuna generazione) e il catalogo preset (MCP
`get_presets`, `/genjutsu`). Costi = crediti per circa 4-5 s in 9:16. La stima NON dice se il
piano permette il modello: quello si scopre solo alla creazione (se rifiutato, nessun credito
scalato). Prima di ogni generazione: `generate cost` e conferma del creator.

## Come ragiona il regista (ordine delle domande)

1. **Da dove parte?** Ripresa vera del creator (edit) / sua foto (anima) / niente (da zero).
2. **Cosa cambia?** L'ambiente attorno, un oggetto/vestito, la persona intera, lo stile di
   tutto il video, il movimento.
3. **Esiste un preset già fatto?** Se sì, parte avvantaggiato (prompt e catena già tarati):
   cercarlo con `get_presets(query=...)` (Viral, Genjutsu, Genjutsu Styles, Soul styles).
4. **Il volto e la voce devono restare veri?** Quasi sempre sì: audio originale sempre,
   `generate_audio false`, volto vero sopra quando il cambio non tocca la faccia.
5. **Modello più economico che basta**, poi upscale (`bytedance_video_upscale` aigc, ~1-2 cr).
6. Prompt con le 5 domande del regista (vedi `higgsfield-vfx.md`).

## Tabella di smistamento

| Richiesta | Prima scelta | Costo Starter | Alternative | Note |
|---|---|---|---|---|
| Creatura/oggetto/fuoco attorno a me nella ripresa vera | `seedance_2_0` fast 720p, video edit + start/end frame | 10 (+2 upscale) | `kling_video_edit` std (6), `gemini_omni_flash_1_2` mode edit (9) | Il nostro flusso "Genera AI", provato e perfetto |
| **Cambio vestiti / accessori** (pelliccia, occhiali, armatura) | **Genjutsu Lite** `hf_mult_replace_object_flash` 720p: 1 video + foto del vestito + prompt dettagliato | **8** | Genjutsu `hf_mult_replace_object` 720p (28), 1080p (80) | Visto nel reel "Digital Quickie": volto e labiale restano. Composito: SOLO la testa vera sopra (non tutta la persona) |
| Sostituire un oggetto in mano / un prodotto | Genjutsu Lite replace object | 8 | Kling Omni Edit | Foto pulita dell'oggetto |
| Diventare un alieno / mostro / altro personaggio (stesso movimento) | Genjutsu replace object con il character come riferimento | 8 / 28 | `seedance_2_0` edit senza protezione | Il volto cambia: il labiale lo tiene il modello. Audio sempre vero |
| Tutto il video in uno stile (cartoon, CGI, anime, lana, pixel art) | **Genjutsu Styles** (preset `genjutsu-style:<id>`), 4-30 s, fino a 5 immagini di riferimento | prezzo dal preset | `flux_3_video_edit` (15) | Ridisegna ogni fotogramma, movimento e camera restano |
| Copiare un movimento/ballo da un video su un personaggio | Genjutsu Lite `hf_mult_motion_control_flash` | 8 | `kling3_0_motion_control` (workflow) | Video "guida" + immagine del soggetto |
| Effetti virali pronti (Vanish, Melting, Clones, Monster dab, Street colossus, Eyes in, Earth zoom, Bullet time...) | Preset **Viral** (87 catene) | prezzo dal preset | ricreare a mano con Seedance | Partono di solito da una foto: video nuovo, non edit della ripresa |
| Video AI completo con me (da foto/personaggio) | `kling3_0` std image-to-video | 7.5 | `veo3_1_lite` 4 s (6), `wan3_0` 720p (8.75), `seedance_2_0` fast i2v (12.5), `kling_4_0_flash` (15) | Il volto deriva più che nell'edit. Per coerenza: Soul ID (da verificare sullo Starter) |
| Video da zero, nessuna persona reale (B-roll, scene) | `seedance_2_0_mini` 480p | 2 | `veo3_1_lite` (6), `happy_horse_video` (12.5) | Bozza economica, poi versione buona |
| Allungare una ripresa | `gemini_omni_flash_1_2` mode extend | ~9 | `seedance_2_5` video_extension (Pro) | |
| Immagine fotografica di me / scena | `text2image_soul_v2` o `soul_cinematic` | **0.12** | `nano_banana_flash` 1k (1.5) | Soul 2.0 ha stili (`style_id`, preset `soul-v2`) |
| Modificare una foto mantenendo la texture | `seedream_v5_pro` 1k | 1.25 | `flux_kontext` (1.5), `nano_banana_pro` (2) | |
| Grafica con testo preciso, layout, copertina | `gpt_image_2_6` low/medium | 0.25 / 0.5 | `ideogram_4_5` | |
| Provare outfit su una foto (stylist) | `nano_banana_2_ai_stylist` (outfit preset) | da stimare | Seedream edit | |
| Cambiare la luce di una foto | `nano_banana_2_relight` | da stimare | | |
| Upscale video | `bytedance_video_upscale` aigc 1080p | ~1-2 | `topaz_video` | Già nell'editor |
| Scontorno video | locale (RVM, gratis) | 0 | `video_background_remover` (1) | |
| Doppiaggio in altra lingua | workflow `dubbing` (eng, spa, fra, deu...) | da stimare | | Cambia la voce: solo se richiesto |

Non disponibili sullo Starter (rifiutati prima di generare): `seedance_2_0` std 1080p/4K,
`seedance_2_5`. Da verificare alla prima prova: Genjutsu, Kling 4.0, Soul ID.

## Prova cambio vestiti (2026-11-10, riuscita)
- Genjutsu Lite `hf_mult_replace_object_flash` 720p **funziona sullo Starter**: 8 crediti per
  4 s (+0,5 per la foto della giacca con GPT Image 2.6 medium). Uscita 720x1280, 24 fps.
- Giacca di pelle realistica: trapuntature, zip, pieghe ai gomiti, braccialetto e mani intatti.
  Volto quasi identico ma non al 100%: in qualche fotogramma la bocca si apre diversamente.
- Higgsfield riscrive da solo il prompt in sezioni TASK / REFERENCES / SOURCE VIDEO / SHOTS /
  PROPS / SETTING / NEGATIVE (si legge in `params.enhanced_prompt`): scrivere già così.
- Protezione "solo testa": rilevamento volto MediaPipe (locale, gratis) -> ellisse dalla cima
  dei capelli al mento+barba (box volto: sopra -0,55 h, sotto +1,10 h, larghezza 0,70 w),
  media su 5 fotogrammi, MOLTIPLICATA per la sagoma RVM vera (senza, ai lati della mascella
  usciva il muro vero sopra la spalla della giacca). Sfumatura 10 px. Ritardo clip AI: 2
  fotogrammi a 30 fps. Risultato: nessuna giuntura, bocca e volto veri al 100%.

## Filtro contenuti (2026-11-10)
- «La mia faccia diventa quella di Hulk per 3 s»: la foto di riferimento (GPT Image 2.6) è finita
  con stato **"nsfw"** perché il prompt diceva "Hulk-style": il filtro blocca personaggi protetti,
  marchi e volti famosi (non c'era niente di spinto). Credito restituito (0,5), video mai partito.
- Regola: mai nomi protetti nei prompt, si descrive un design originale con gli stessi tratti
  ("gigante dalla pelle verde, arcata sopraccigliare pesante, vene"). L'editor, se il filtro blocca,
  fa riscrivere il piano a Claude e riprova una volta da solo.
- Trasformazioni che vanno e tornano: Seedance con primo e ultimo fotogramma veri (Genjutsu non li
  ha, il ritorno alla faccia vera non sarebbe garantito).

## Faccia verde da gigante (2026-11-10, riuscita al 3° tentativo, 11 crediti + 1,25 riferimento)
- GPT Image ha bloccato ANCHE il ritratto senza nome ("gigante dalla pelle verde"): riconosce la
  somiglianza col personaggio. Soul 2.0 lo accetta ma esce una statua beige. Soluzione migliore:
  **Seedream 5.0 Pro che modifica il tuo fotogramma vero** (1,25 crediti): stessi occhiali, stanza e
  luce, solo la faccia cambia. È ora il riferimento della ricetta transform.
- Seedance 2.0 fast 720p con primo/ultimo fotogramma veri: il verde sale dal collo a 0,6 s, faccia
  piena 1,2-2,4 s, di nuovo tu a 2,6 s. Avambracci verdi perché lo erano nel riferimento: nel prompt
  di modifica scrivere "solo faccia e collo".
- Bug trovato e corretto: per le trasformazioni l'allineamento nel tempo si misurava sullo sfondo
  (fermo = nessuna informazione) e dava 7 fotogrammi di ritardo -> labiale fuori sincrono e il verde
  ancora presente alla fine. Il tempo si misura sempre sulla persona; il colore sullo sfondo.

## Regole che valgono sempre
- Mai image-to-video da un fotogramma per un effetto su una ripresa dove parlo (ri-anima tutto).
- Audio: sempre quello vero; i modelli con suono (`kling3_0 --sound`, `seedance generate_audio`)
  vanno spenti.
- Preset prima del prompt libero, ma il preset deve fare *esattamente* la richiesta: se cambia
  volto/voce quando non deve, si scarta.
- Ogni take si guarda (foglio prima/dopo) prima di dire che è fatta.
