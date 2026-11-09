# Writing the Seedance video-edit prompt (official format)

Sources, in order of authority:
- BytePlus "Dreamina Seedance 2.0 series prompt guide" (ByteDance, video editing section);
- Higgsfield blog "AI VFX Just Got Insane — Seedance 2.0 in 4K" and "VFX with Seedance 4K";
- Higgsfield Academy "Add AI VFX to Real Footage" lessons;
- community skill OSideMedia/higgsfield-seedance-vfx (MIT);
- our own tests on the creator's footage (2026-11-09).

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

## Repairing a take

Keep every line that worked; for each defect write what went wrong and what you want instead;
change only the lines that caused it; re-read so every line agrees (beat, light, lock-down).
If the same defect returns across takes, change the input (reference image, free space, exit),
not luck. Seedance 2.0 has no seed: to pin the look, pin the inputs.
