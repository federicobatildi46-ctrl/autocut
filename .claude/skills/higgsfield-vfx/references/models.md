# Models and costs (CLI job_type, checked 2026-11-09, Starter plan)

The editor chooses the model; this is here so plans and reviews stay realistic.

| use | job_type | notes | credits |
|---|---|---|---|
| video edit, MVP default | `seedance_2_0` mode `fast`, 480p, 4 s, `generate_audio false`, `--video-references clip` | min duration 4 s; up to 3 video + 9 image refs | 4 |
| cheapest draft | `seedance_2_0_mini` 480p 4 s | lower quality | 2 |
| better draft | `seedance_2_0` fast 720p | | 10 |
| alt video edit | `kling_video_edit` mode `std` | video_references + image_references | 4.5 |
| best (Plus/Pro) | `seedance_2_5` mode `video_edit`, `draft` + `draft_job_id` to upscale identically | 14 at 480p | 14 |
| replace object / outfit | `hf_mult_replace_object_flash` | needs 1 video + image refs | ? |
| background removal | `video_background_remover`, `sam_3_video` | editor uses local MediaPipe instead (free) | 1 |

Images for references: Soul 2.0 / Soul Cinema = most photographic and cheap; Seedream 5.0 Pro =
edits that keep textures; GPT Image = precise layouts/text and well-defined creatures/objects;
Nano Banana = more "AI look".

Never: image-to-video from a still of the creator (re-animates his face and invents speech),
generated audio on footage where he talks.

## Recipe that produced the creator's "perfect" clip (2026-11-10, Starter plan)

`seedance_2_0` mode `fast` 720p, 4 s, audio off, real clip as video reference, real first and last
frames as start/end image, Soul 2.0 reference image -> `bytedance_video_upscale` 1080p preset
`aigc` (~1-2 credits) -> local composite (real person on top, RVM). About 12 credits per take,
perfect by the third take. Local Real-ESRGAN (ONNX, CPU) was tested and rejected: ~30 s per frame
on this laptop and "plastic" scales.
