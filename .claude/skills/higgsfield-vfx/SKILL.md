---
name: higgsfield-vfx
description: Add AI visual effects to REAL footage of the creator with Higgsfield (Seedance video-to-video) so the result blends into the timeline - a creature behind them, fire, a new object, a changed background, a morph - while their face, voice, lip sync and camera stay exactly the real ones. Use it whenever the autocut editor's "Genera con Higgsfield" button (or the creator) asks to put something generated INTO an existing clip ("mettimi un drago dietro", "fai comparire...", "trasforma la mano", "cambia lo sfondo"), when writing a Seedance/Kling video-edit prompt from a timeline frame, or when reviewing a generated take before it goes in the timeline. Not for standalone AI videos, thumbnails, product shots or Soul training (use higgsfield-generate / higgsfield-youtube-thumbnail / higgsfield-soul-id).
---

# Higgsfield VFX on real footage

The editor cuts a short piece (max 3 s, sent as a 4 s clip because Seedance needs >= 4 s) of the
creator's real video and asks you for one of two jobs. Read the request block you are given: it says
which job, and gives you the paths and numbers you need. Answer with JSON only, in the exact shape
of that job, because the editor parses it.

Why this skill exists: the first attempt generated a dragon from a still frame with image-to-video.
The model re-animated the whole shot, so the creator's face drifted and he started speaking invented
English. Everything below is about never letting that happen again: edit the real clip, change only
the one thing asked, keep the person and the voice real, and look at the result before calling it done.

## The pipeline you are part of (the editor runs it, you don't run commands)

1. Editor exports the real clip + its first frame + the transcript of those seconds.
2. **plan** (you): write the video-edit prompt; decide whether a reference image is needed and
   whether the person can be protected (composited back on top).
3. Editor: optional reference image (Soul 2.0) -> Seedance 2.0 video edit (480p draft, or the
   1080p/4K final that Higgsfield recommends because faces and lip-sync hold there), no generated
   audio -> aligns frames, matches color, measures how faithful the AI person is: faithful = the
   AI clip is used as is (no cut-out, like Higgsfield's own workflow); redrawn = the real person
   is matted (Robust Video Matting) back on top. Auto-extends to where the effect ends, crossfades.
4. **review** (you): look at the before/after sheet and say if the take is usable.
5. Creator clicks "Metti in timeline". The original voice is always kept.

## Job: plan

Choosing the model: `references/router.md` says which Higgsfield model or preset fits each kind
of request (creature/background = Seedance edit; outfit, object or character swap = Genjutsu
replace object; whole-video look = Genjutsu Styles) and what it costs on the Starter plan.

Look at the frame with Read before writing anything: where the person is, how much free space there
is around them (the effect must live there), the light direction and color temperature, whether the
camera is handheld. A prompt that ignores the actual frame is the main cause of slop.

Then decide:

- **protect_person** - true when the effect lives around/behind the person (creature behind, sky,
  explosion in the background, objects on the desk, background swap). The editor then pastes the
  real person back on top, so face and mouth are 100% real. false only when the effect must touch or
  cover the person (fire on the head, hand morph, outfit change, object in hand, something passing
  in front of them). When false, the prompt's locks carry all the weight - say so in `risk`.
- **reference_image** - ask for one when the look of the new thing matters and is hard to say in
  words (a specific creature, a branded object, a character). "Show, don't describe": a clean
  reference gives far more control than adjectives. Skip it for fire, smoke, weather, light, simple
  objects. The image prompt must describe the thing alone, three-quarter view, neutral grey
  background, matching the clip's light (direction + warmth) and realism.

Answer the director's five questions first (camera, tone, who/what/why, light, texture and
interaction - see the top of `references/prompting.md`), both for the video prompt and for the
reference image prompt. Then write the video prompt in English following
`references/prompting.md` (read it every time - it has the official ByteDance/Higgsfield edit format: "strictly edit Video 1", never "reference
Video 1"; preserve list, one change, double-anchored timed beats, physical exit, lock-down).
Roughly 150-280 words: the first sentences (what the model weighs most) are the edit verb, the
preserve list and the single change; the lock-down closes it.

In AUTOMATIC mode (the request block says so) you are the router: pick `recipe` -
`effect` (something added around/behind him: creature, fire, sky, objects in the room),
`outfit` (his clothes, accessories or an object he holds change; his face stays real) or
`transform` (he himself becomes something else: alien, robot, statue). The editor then uses the
right model, the right protection (whole person / head only / none) and the upscale. For
`outfit` (Genjutsu) the reference image of the garment/object is REQUIRED and the prompt follows
the Genjutsu format in `references/prompting.md`. For `transform` (Seedance, with his real first
and last frames pinned, so he starts and ends as himself) the reference image is REQUIRED and
is HIS OWN FRAME EDITED (Seedream): write its `prompt` as a photo-edit instruction - "Edit this
photo: turn the man's face and neck into <original design>... Keep exactly the same pose,
framing, glasses (and their lens tint), hair, beard shape, clothes, room and window light; ONLY the
face and neck change, his hands and forearms keep their natural skin" (the first Seedream edit also
turned his forearms green and Seedance copied it) - so the character keeps
his identity cues and the room's light. The video prompt follows the Seedance format: real face at the start, the change on the
words, the return to his real face by the end of the window, then the room and him exactly as
in Video 1.

Names: NEVER write the name of a protected character, film, franchise, brand or famous person
in any prompt (video or reference). Higgsfield's filter closes the job as "nsfw" (credit
refunded, nothing generated) - it happened with "Hulk". Describe an original design with the
same visual traits instead: "Hulk" -> "a towering green-skinned rage giant of original design,
heavy brow, broad jaw, visible veins"; "Spider-Man" -> "a red and blue masked hero suit with a
web-line pattern, original design". If the block says the previous attempt was blocked, rewrite
everything that way.

Questions: only in automatic mode and only the first time. If something ESSENTIAL for an
excellent result is missing and you cannot decide it well from the frame or the speech (which
jacket: colour, material, style? what kind of alien?), return 1-3 short Italian questions in
`questions` and nothing will be spent. Prefer deciding yourself when a good director would; a
question costs the creator a click. When the block says the questions were already asked,
use the answers and return `"questions": []`.

Output:

```json
{"recipe": "effect", "questions": [], "prompt": "...", "protect_person": true,
 "reference_image": null, "risk": "one short Italian sentence on what could go wrong",
 "title": "max 5 parole in italiano"}
```

`reference_image` is either `null` or `{"prompt": "...", "why": "frase breve in italiano"}`.
When you return questions, the other fields may be a draft.

If the request is impossible in this clip (e.g. the effect needs more than 3 s, or needs a camera
move the creator didn't film and protection is on), still return the best feasible plan and explain
the compromise in `risk`.

## Job: review

You get a sheet: top row = original frames, bottom row = the composited AI take, same timestamps.
Check, in this order (details in `references/review.md`):

1. **Identity & voice-related motion** - same face, glasses, beard, mouth shapes as the original.
   Any difference = `fail` when protection was off (it means the model regenerated him).
2. **The change happened** - the requested element is visible, in the right place, for the right
   seconds, and nothing else was invented (extra people, text, logos, changed furniture).
3. **Blend** - light direction and color match, no halo/cut-out edges around the person, no
   flicker, no plastic/over-sharp textures, no jump at the first or last frame.

```json
{"verdict": "ok|retry|fail", "issues": ["frasi brevi in italiano"],
 "fix_prompt": "full revised English prompt if verdict is retry, else empty"}
```

`retry` = inputs were fine but the take has a fixable defect: rewrite the prompt with the
Academy repair method (keep what works, change only the lines that caused the defect, make every
affected line agree). `fail` = the approach can't work for this request (say why in issues).
Be honest: a mediocre take marked `ok` ends up in the creator's video.
