# Writing the Seedance video-edit prompt (official format)

Sources, in order of authority:
- BytePlus "Dreamina Seedance 2.0 series prompt guide" (ByteDance, video editing section);
- Higgsfield blog "AI VFX Just Got Insane — Seedance 2.0 in 4K" and "VFX with Seedance 4K";
- Higgsfield Academy "Add AI VFX to Real Footage" lessons;
- community skill OSideMedia/higgsfield-seedance-vfx (MIT);
- our own tests on the creator's footage (2026-11-09).

## Think like the director first (the creator's rule for every image and video)

Before writing a single line, answer these five questions. Every answer must end up in the prompt
as concrete words, not as a mood. A prompt that skips one of them is how slop starts.

1. **Camera** - what shot this, and how: iPhone handheld vertical, locked tripod, cinema camera
   with a 35 mm lens, drone, GoPro; framing (close-up, medium, wide), angle (eye level, low,
   high), movement (static, slow push-in, orbit, handheld sway), depth of field. In a video edit
   the camera is ALWAYS the one of Video 1: describe it so the model copies it ("vertical iPhone
   footage, locked-off, medium close-up at eye level, shallow depth of field").
2. **Tone** - the single emotion the shot must give: awe, threat, joy, irony, tension, wonder.
   It decides pace and energy of the new element ("slow, majestic, menacing" vs "playful, quick").
3. **Who, what, why** - who is in the frame, what happens, in what order, and why it happens
   (the motivation makes the motion believable: the dragon rises *because* he names it; it
   looks at him *because* he is speaking). Use the creator's own words as anchors.
4. **Light** - the kind and its source: natural window light, warm practical lamp, cinematic
   low-key, golden hour, neon cyberpunk, overcast. Say direction, warmth and contrast. In an
   edit, the light is the room's: name it, then say how the new element is lit by it and what
   light the element itself adds (fire = warm flicker on wall, ceiling, skin).
5. **Texture and interaction** - materials described exactly (matte scales, wet stone, worn
   leather, film grain, lens softness) and how every element touches the scene: contact
   shadows, occlusion behind the head, reflections, dust, air displacement, hair moved by wind.
   Interaction with the context is what makes it credible.

Keywords that work (use the real terms): shot types ("medium close-up", "over-the-shoulder"),
lens ("35mm", "85mm", "anamorphic"), movement ("dolly-in", "orbit", "handheld"), light
("Rembrandt lighting", "rim light", "practical light", "volumetric haze", "golden hour"),
texture ("film grain", "subsurface scattering", "matte", "weathered"), realism ("photoreal",
"shot on iPhone", "documentary footage"). Avoid empty hype words ("epic", "ultra 8K
masterpiece") - they add nothing.

For a video edit the five answers go inside the template below (camera and light in the first
line and the preserve list, tone and who/what/why in the change and the beats, texture and
interaction in the physics line). For a reference image they go in the image prompt.

## The two rules that matter most

1. **Edit, don't reference.** Call the real clip **Video 1** and the reference image **Image 1**.
   Write "strictly edit Video 1". NEVER write "reference Video 1" or "@video1 is the real
   footage / use it as reference": ByteDance warns it gets treated as a *reference task*, and the
   model then regenerates the whole shot. This is exactly how our first takes redrew the creator
   ~20 px wider. "Parts not mentioned remain unchanged by default" - so name the one change and
   explicitly say everything else stays as in Video 1.
2. **Preserve list first, one change, lock-down last.** The change gets one sentence; what stays
   gets the rest. End with the lock-down that repeats face/identity/lip-sync.

## Template (plain English, no markdown in the prompt)

```
Strictly edit Video 1: <one line of what the clip is - who, where, framing, handheld/locked>.
Preserve exactly as in Video 1: his identity and face, glasses, beard, hair, wardrobe, hands,
expression, every gesture, his exact lip movements and lip-sync, the room, the light, the framing
and the camera motion frame-for-frame. Change only one thing: <the change>.
Image 1: reference of <the element> - <material/anatomy notes>; appearance and texture only,
ignore its background, framing and lighting.
Photoreal. <9:16>. <4>s. <look: match the footage's exposure, colour temperature, lens softness
and grain>. NON-IP - generic <creature/design>, not based on any existing character.
<Timed beats with DOUBLE anchors: semantic + numeric, e.g. "On the words 'staying consistent',
at about 0.6 seconds, ...">. <Physics and plate interaction: where it enters, what it touches,
contact shadow on the wall, the warm light its fire casts on the wall and ceiling>.
<Exit: physical and complete - "it slides down behind his right shoulder and is fully out of
frame by about 2.6 seconds; it never fades, dissolves or turns transparent". Then: "From 2.6
seconds to the end of Video 1 the room is exactly as in Video 1.">
Lock-down: his face, identity, expression, wardrobe and gestures are unchanged, lips matching
Video 1 exactly; the camera identical to Video 1; do not re-frame, re-time, re-angle or re-cut;
no extra people, no text, no subtitles, no logos, no watermark. No music, no dialogue, no
generated voice.
```

## Timing (why our dragon was cut mid-fire)

- ByteDance: "the model's support for precise timing (such as 0-3 seconds) is unstable". Seedance
  stretches the action over the whole clip. So: anchor every beat twice (the spoken words + "at
  about T seconds"), put the exit early (~0.5-1 s before the end of the requested window), and
  state the empty room after it. The editor also auto-extends the clip to where the effect really
  ends (max 4 s) - but a clean physical exit inside the window is the goal.
- Quote the creator's words from the transcript you are given for the semantic anchors.

## Start and end frames (the editor always passes them)

Seedance gets Video 1's own first and last frames (the real room, no effect) as the pinned start
and end frame. Say it in the prompt: "The clip begins exactly on the start frame and ends exactly
on the end frame: the room as in Video 1, with no <element>." Two 720p takes without this kept the
dragon on screen at frame 0 and its tail at the last frame, whatever the beats said.

## Creatures and elements

- Match the creature the creator named, culturally: a "dragone cinese" is a long serpentine loong
  (snake-like body coiling through the air, small limbs, whiskers, antlers, mane), NOT a
  standing four-legged western/Godzilla dragon. Say what it is not, and make the reference image
  show exactly that silhouette.

- Never CG, plastic, glossy or cartoonish: ask for matte, wrinkled, asymmetric, weathered
  surfaces, real weight and inertia, soft-edged contact shadows, subtle motion blur.
- Say the scale against the plate ("its head about the size of his torso") and keep it in the
  free space you saw in the frame, beside/above the head - never covering the face or mouth.
- Light: the element is lit by the room's light (say direction + warmth); its own fire/glow lights
  the wall and ceiling behind him.
- Reference image (Image 1): photographic, matte, three-quarter view, neutral grey background,
  same light direction as the room. Show, don't describe.

## Resolution and person protection (decided by the editor, explain risks in `risk`)

- Higgsfield: faces, lip-sync and fine detail hold at 4K, warp at 1080p; at 480p (our drafts)
  Seedance redraws the person. The editor measures how faithful the AI person is: if faithful it
  uses the AI clip as is (no cut-out, no edges, like everyone else does); otherwise it puts the
  real person back on top. Write the prompt so the person never needs replacing.

## Genjutsu format (recipes outfit and transform)

Higgsfield rewrites every Genjutsu prompt into these sections (seen in `enhanced_prompt` of
our 2026-11-10 jacket test); write it in this shape so our direction reaches the model intact.
Plain text, section names in capitals:

```
TASK
Edit Video 1. Replace <what he wears/holds now, as seen in the frame> with <the thing> from
Image 1. He stays himself: same face, glasses, beard, hair, skin, build, expression, hands and
fingers as in Video 1. <fit: how it sits on his shoulders/arms, where sleeves end, what stays
visible (bracelet, t-shirt)>. Video 1 controls the performance, blocking, camera, framing and
timing; everything outside the replacement keeps its look from Video 1.
REFERENCES
Image 1: <material, colour, details>; use <the garment/object/character> only.
SOURCE VIDEO
<one line: who, framing, what he does, one continuous shot>.
SHOTS
Shot 1 (0.0-4.0s, continuous): <camera: iPhone front camera, locked-off, angle, framing>.
<how the new thing moves with his gestures: folds at the elbows, light on zips>.
PROPS
<the new thing as one physical object: material, texture, how light hits it>.
SETTING
Keep the original location from Video 1: <room, window light direction and temperature,
exposure, lens softness, grain> unchanged.
NEGATIVE
no identity or face change, no altered lips or lip-sync, no altered hands or fingers, no
leftover of the old garment, no warped details, no extra people, no text, no logos, no
watermark, no cuts, no reframing, no new camera moves, no slow motion.
```

The reference image is a product-style photo of the garment or object alone: three-quarter
view, neutral light-grey seamless background, soft light from the same side as the room's
window, photoreal, no person.

## Transform format (recipe transform: Seedance, he changes and comes back)

Use the Seedance template above, with the change being HIM: "Strictly edit Video 1 ... Change
only one thing: on the words '<x>', at about T1 seconds, his face and head turn into the
creature of Image 1, keeping his exact head motion, mouth movements and lip-sync, glasses,
gestures and timing; on the words '<y>', at about T2 seconds, it turns back into his own real
face, fully himself by T3." Then: "The clip begins exactly on the start frame and ends exactly
on the end frame, his real face." Describe the transition physically (skin colour spreading
from the neck, veins rising, then draining) - never a fade or dissolve. The reference image is
a head-and-shoulders portrait of the character alone (three-quarter view, neutral grey, room's
light direction). Never the protected name: describe an original design with the same traits.

## Repairing a take

Keep every line that worked; for each defect write what went wrong and what you want instead;
change only the lines that caused it; re-read so every line agrees (beat, light, lock-down).
If the same defect returns across takes, change the input (reference image, free space, exit),
not luck. Seedance 2.0 has no seed: to pin the look, pin the inputs.
