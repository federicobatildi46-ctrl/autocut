# Routing a request to the right Higgsfield model or preset

Checked 2026-11-10 on the Starter plan with `higgsfield model get`, `higgsfield generate cost`
(estimates only) and the preset catalog. Credits are for ~4-5 s, 9:16. A cost estimate does not
prove the plan allows the model; a refused create charges nothing. The full Italian table with
alternatives lives in `knowledge/higgsfield-router.md`.

## Decide in this order

1. Source: the creator's real clip (edit) / a photo of him (animate) / nothing (from scratch).
2. What changes: the world around him, one object or garment, his whole body/character, the
   style of every frame, the motion.
3. A ready preset that does exactly this? Prefer it (tuned prompt and chain). Search with the
   Higgsfield preset catalog (Viral, Genjutsu, Genjutsu Styles, Soul styles).
4. Must his face and voice stay real? Almost always: original audio, generated audio off,
   real face on top whenever the change does not touch the face.
5. Cheapest model that does it, then `bytedance_video_upscale` (aigc, 1080p, ~1-2 credits).
6. Write the prompt with the five director questions (`prompting.md`).

## Real-footage edits (this skill's job)

| request | model | credits | protection |
|---|---|---|---|
| creature / fire / object / background around him | `seedance_2_0` fast 720p edit + real start/end frames | 10 | whole real person on top |
| outfit, accessories, armour, glasses | `hf_mult_replace_object_flash` (Genjutsu Lite) 720p: exactly 1 video + >=1 garment image + detailed prompt | 8 | real HEAD only on top (body is the change) |
| object in his hand / product swap | `hf_mult_replace_object_flash` | 8 | real head on top |
| become a creature / character for a moment and come back (Hulk face for 3 s) | `seedance_2_0` fast 720p edit + real start/end frames + character image (recipe `transform`) | 10 (+2 upscale, +0.5 image) | none during the change; start/end frames are his real ones |
| become another character for the whole clip | `hf_mult_replace_object_flash` with a character image | 8 | none: the model must hold the lip-sync |
| restyle every frame (anime, toy CGI, clay, pixel art) | Genjutsu Styles preset `genjutsu-style:<id>`, 4-30 s, up to 5 refs | from preset | none |
| copy a motion/dance onto a character | `hf_mult_motion_control_flash` | 8 | none |
| cheaper alternatives for an edit | `kling_video_edit` std (6), `gemini_omni_flash_1_2` mode edit (9) | | |

Genjutsu prompt: name Video 1 and the garment image, say what replaces what, then the preserve
list and lock-down exactly as in `prompting.md` (face, identity, lip movements, hands, room,
light, camera frame-for-frame). Describe the garment's material, fit and how it moves with
his gestures (fur that shifts when he moves his arms, light on sunglasses).

Tested 2026-11-10: Genjutsu Lite runs on Starter (8 credits, 720x1280, 24 fps); the jacket was
convincing, the face was close but the mouth differed in a few frames, so the editor pastes the
real HEAD back (face box from MediaPipe -> ellipse from hair top to beard, times the real RVM
silhouette). Higgsfield rewrites the prompt into TASK / REFERENCES / SOURCE VIDEO / SHOTS / PROPS /
SETTING / NEGATIVE sections - writing it in that shape keeps our intent intact.

Not available on Starter: `seedance_2_0` std (1080p/4K), `seedance_2_5`.

Protected names (Hulk, Marvel/DC heroes, brands, celebrities) make Higgsfield close the job with
status "nsfw" (credit refunded): always describe an original design instead. The editor retries
once by itself, asking for a rewrite without names.
