# Brand pack

Un brand pack descrive lo stile coerente di un creator o di un cliente. Una cartella per brand:

```
brands/<id>/
  brand.json      # palette, font, sottotitoli, lower third, grafiche, transizioni, sound
  fonts/          # (opzionale) font locali con "source": "local", "file": "fonts/x.otf"
  logo/           # (opzionale) loghi
```

- **palette**: 7 colori (`background`, `surface`, `text`, `muted`, `accent`, `accent_2`, `highlight`).
- **fonts**: chiavi libere (`sans`, `serif`, `display`, …) usate dagli altri campi. Google Fonts
  si caricano da soli nell'editor; per font commerciali usa `"source": "local"` e controlla la
  licenza (uso video/social).
- **captions**: stile per verticale e orizzontale. `emphasis` = la parola chiave di ogni frase
  (numeri o parola più lunga) con un altro font/colore, come nelle reference "podcast premium".
- **lower_third**: nome e ruolo all'inizio del video.
- **graphics.style**: descrizione che Claude riceve quando propone o genera con Higgsfield.
- **transitions.presets**: transizioni del brand, ognuna con il suono da usare.
- **sound**: livelli in dB e regole (skill `autocut-sound-design`, libreria in `library/sfx`).

Nell'editor il brand si sceglie dal menu in alto; la scelta è salvata per progetto.
