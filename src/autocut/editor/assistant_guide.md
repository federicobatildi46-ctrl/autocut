# Guida per Claude: montare con gli strumenti dell'editor autocut

Sei nella cartella di lavoro della chat «Chiedi a Claude». Qui ci sono COPIE dei file del
progetto: modificale con Edit/Write; l'editor le convalida e le applica tutte insieme (il
creator può annullare con un clic). Non creare altri file. Tutti i tempi sono in millisecondi
del RAW (la ripresa originale), come in context.json.

`context.json` contiene: la selezione, lo stile attivo (`style`: "viral" o "premium" o null),
le parole e le didascalie nella selezione, i pop-up e i punti di transizione lì vicino, i
cataloghi (animazioni, transizioni, font, preset di testo, suoni, filtri) e, se c'è, il
fotogramma `frame.jpg`.

Quasi tutti i file hanno una sezione per stile: lavora su `styles[<style>]` (crea la chiave se
manca). Senza stile (style null) testi ed effetti non si possono cambiare: dillo in "missing".

## Regole del montaggio (le regole del creator)
- Viral: velocità e dinamismo alti, ma senza esagerare; ogni ~3 s succede qualcosa (suono,
  scritta, grafica, transizione, cambio scena, b-roll). Premium: pulito, elegante, meno effetti.
- I primi 3 s sono l'hook: titoli forti in grassetto, emoji, grafiche.
- Rispetta lo stile: usa solo animazioni/transizioni del set dello stile (campo `sets`).
- Fai la cosa più bella possibile con gli strumenti che ci sono, poi spiega in breve.

## popups.json — sticker, emoji, scritte e immagini sopra il video
`items`: lista. Per aggiungerne uno: id nuovo `pop_NNNN` (4+ cifre, il numero più alto + 1).
Campi: `at_ms` (inizio), `duration_ms` (400-10000, di solito 1500-2500), `kind` ("emoji" |
"text" | "image"), `emoji` (es. "😭"), `title` (max 40, per kind "text" è la scritta),
`placement` ("side" accanto alla didascalia | "above" sopra il testo | "pair" due ai lati |
"center" grande al centro SOTTO il testo | "top" sopra la testa | "behind" dietro la persona,
solo premium | "free" con `x_pct`/`y_pct` 0-100), `size` ("small"|"medium"|"large"),
`side` ("left"|"right"), `scale` 0.2-5, `rotation` -180..180, `layer` ("under_text" |
"over_text" | "person"), `sound` (true = suono pop automatico), `status` (quello che chiede il
creator: "approved"), `origin`: "ai", `style`: lo stile attivo, `reason`: perché (breve).
«Sotto la frase» = placement "center" all'istante della didascalia (`at_ms` = inizio della
didascalia, `duration_ms` = sua durata o ~2000).

## text_style.json — le didascalie (sottotitoli)
`styles[<style>].base` = stile di tutte; `styles[<style>].scenes[<id didascalia>]` = una sola.
L'id di una didascalia è l'id della sua PRIMA parola (vedi `captions` in context.json, con
testo, inizio, fine e grandezza relativa). Campi: `font` (solo quelli in `fonts`), `bold`,
`italic`, `case` ("sentence"|"upper"|"lower"), `color` "#RRGGBB", `emph_color`, `emph_font`,
`preset` ("stroke"|"shadow"|"hard"|"glow"|"box"|"plain"; "glow" = bagliore), `fx_color`
(colore del bagliore/contorno/box), `scale` 0.3-3 (più grande), `x_pct` -60..60, `y_pct`
-80..80 (spostamento), `rotation`, `text` (testo riscritto, max 200).
«La scritta più grande della selezione»: la didascalia con `scale` più alto o, a parità, la
più lunga / quella con l'enfasi; se nessuna è più grande, quella principale del tratto.

## effects.json — animazioni e transizioni
`styles[<style>]`: `captions` {"in","out","loop"} = animazione di TUTTE le didascalie (non
esiste per una sola), `sticker_default` = di tutti gli sticker, `stickers[<pop id>]` = di un
solo sticker/pop-up, `transitions[<id punto>]` = transizione su un taglio (id in
`transition_points` di context.json; {"type": id da `transitions`, "ms": 100-1500,
"origin": "ai"}). Un'animazione è {"type": id da `anims` con la fase giusta, "ms": 0-3000,
"speed": 0.25-4}. Fade in/out di un pop-up = `stickers[<id>]` con in "fade" e out "fade".

## filters.json — colore del video
`styles[<style>]` = {"preset": id da `filter_presets`, "values": ritocchi su brightness,
contrast, saturation, warmth, vignette, hue, grayscale}. Vale per TUTTO il video: oggi non
esiste un filtro per un solo tratto. Se il creator lo chiede su una clip, NON cambiare il
filtro globale: scrivi in "missing" che serve il filtro per tratto.

## cuts.json — tagli a mano
`splits`: istanti in cui dividere (ms); `removed`: [[inizio, fine], ...] tratti tolti a mano.

## audio.json — suoni
`styles[<style>]`: `voice_db`, `sfx_db`, `sounds[<id suono automatico>]` {"muted", "gain_db",
"type", "shift_ms"}, `added`: [{"id": "snd_NNNN", "type": id da `sounds` del catalogo,
"at_ms", "gain_db"}]. Un suono su un pop-up/una scritta va all'istante in cui appare.

## music.json — musica di sottofondo (libreria gratuita Audio Library)
`items`: [{"id": "mus_NNNN", "track": id YouTube del brano, "start_ms"/"end_ms" (raw; null =
inizio/fine del video), "offset_ms" (punto del brano da cui parte), "gain_db" -30..12 (rispetto
al livello dello stile, già sotto la voce), "muted", "fade_in_ms", "fade_out_ms", "style",
"origin": "ai", "why"}]. Usa solo brani già scaricati: quelli in `suggestions[<style>].candidates`
(con il loro `offset_ms` consigliato) o già in `items`. «Musica solo in questa clip» = un item con
start_ms/end_ms della selezione; «più bassa» = gain_db -4/-6; «toglila qui» = dividi l'item in
due tratti. Per brani nuovi serve il pannello Audio (Claude li cerca e li scarica da lì).

## Cosa NON puoi fare da qui
Generare con Higgsfield (si fa dalla scheda Genera AI), cambiare il codice dell'editor,
cambiare stile o brand. Se serve, dillo in "missing": il creator può chiedere a Claude, in
modalità «Modifica l'editor», di aggiungere lo strumento.
