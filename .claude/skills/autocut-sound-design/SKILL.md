---
name: autocut-sound-design
description: Sound design professionale per i video di autocut (Remotion). Usala quando devi aggiungere whoosh, pop, click, riser, hit o musica a un montaggio, preparare un cue sheet dei suoni o scegliere suoni dalla libreria library/sfx rispettando livelli e brand pack.
---

# Sound design per autocut

Fonte completa delle regole: `UE-Sound-Design-Claude-Training-COMPLETE.md` (nella radice del repo).
Leggila per intero prima del primo lavoro di sound design in una sessione. Questa skill la
adatta alla pipeline di autocut.

## Principi (sintesi)

1. Il suono sottolinea il movimento: se sullo schermo non succede niente, non c'è suono.
2. Tre famiglie, tre lavori:
   - **whoosh** → movimento (slide, pan, zoom, transizioni di scena);
   - **texture** → eventi senza scorrimento (pop, click, reveal, scrittura lettera per lettera, UI);
   - **riser + hit** → attesa (costruire verso il segmento successivo e rilasciare).
3. Un solo momento più forte per scena. La voce è sempre la regina: niente sopra la voce.
4. Musica solo sotto il parlato, mai sotto grafiche o animazioni.
5. Il picco del whoosh cade sul frame più veloce del movimento; le texture sul frame dell'evento;
   i riser finiscono sul frame di transizione con l'hit sotto.

## Livelli

Prendi i livelli dal brand pack (`brands/<id>/brand.json` → `sound.levels_db`). Default:
whoosh −12 dB (max −10), texture −6/−7 dB, riser −5 dB, musica −19 dB, voce 0 (mai toccata).
Se lo stack più forte rischia il clipping abbassa l'hit, mai la voce.

## Libreria

`library/sfx/` (non versionata), una cartella per famiglia:

```
library/sfx/whooshes/  library/sfx/textures/  library/sfx/risers/
library/sfx/hits/      library/sfx/music/
```

Usa solo suoni della libreria. Quando una cartella ha più varianti dello stesso suono, ascoltale
(durata, ritmo, peso) e scegline una; dichiara quale e perché. Non generare suoni se la libreria
ne ha uno adatto. Controlla la licenza del pacchetto da cui arrivano (uso commerciale).

## Procedura (l'ordine non si cambia)

0. Conferma: progetto/composizione, brand pack, libreria presente, audio originale (muto ciò
   che non è voce, non cancellare).
1. **Analisi**: scorri il montato (timeline.json + override effettivi, grafiche, transizioni del
   brand) e scrivi un cue sheet con i tempi: ogni momento è MOVIMENTO, EVENTO o BUILD.
   Mostralo all'utente prima di piazzare suoni. Fai al massimo 2-3 domande.
2. **Passo 1 — whoosh** (traccia WHOOSHES).
3. **Passo 2 — texture** (traccia TEXTURES, sotto-tracce se si sovrappongono).
4. **Passo 3 — riser e hit** (tracce RISERS e HITS): primo riser ~5 s dopo l'hook con hit sotto;
   almeno 2 riser "sharp bass" e 2 "metallic" nel video; ogni cambio di segmento e A-roll→B-roll.
5. Segnala lo stack più forte e il rischio di clipping.
6. **Passo 4 — musica** solo dopo l'approvazione dei passi 1-3.

Una famiglia per traccia, clip intere (spostabili), transizioni con 2-3 frame di anticipo
(salvo texture e picchi dei whoosh). Dopo ogni passo riporta cosa hai piazzato, dove e quale
variante. Quando l'utente corregge a mano, applica la stessa logica ai momenti simili.

## Formato del cue sheet

```
| tempo (montato) | evento sullo schermo | tipo | suono (cartella/file) | livello |
| 00:05.20        | titolo scorre da sx  | MOVIMENTO | whooshes/hollow_02.wav | -12 dB |
```

I tempi del montato si ottengono dalla vista effettiva (segmenti tenuti dopo gli override);
riporta anche il tempo raw della camera per ritrovarli nell'editor.
