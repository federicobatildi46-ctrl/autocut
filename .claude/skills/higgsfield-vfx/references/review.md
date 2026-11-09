# Reviewing a take

Three questions from the Academy, adapted to real footage:

1. **Who / identity** - is it still him? Compare glasses frame shape, beard line, face width,
   eyes, mouth opening on the same timestamp. With protection on the person is the real one, so
   look instead at the EDGE: halos, cut hair, missing ears/fingers, background showing through
   the body, a ghost of the AI-rendered person peeking out around the real one (means the AI moved
   him - flag it, the editor can grow the mask).
2. **Action** - did the requested element appear, where and when asked, and leave on time? Nothing
   else invented (people, text, logos, furniture changes, a different room)?
3. **Blend / anti-slop**
   - light direction and warmth agree between element and room;
   - no plastic skin/scales, no over-sharpened texture, no repeating pattern, no smeared frames;
   - no flicker or brightness jump at the first/last frame (crossfade should hide the seams);
   - the 480p draft is softer than the real footage: that's expected for a draft, don't fail it
     for resolution alone, but mention it if the element looks mushy.

Verdicts:
- `ok`: usable as is (small softness from 480p is fine).
- `retry`: inputs fine, isolated defect -> give the full revised prompt.
- `fail`: approach can't work (effect needs the person regenerated but protection must stay on,
  creature keeps covering the face, etc.) -> explain in Italian what to change in the request.
