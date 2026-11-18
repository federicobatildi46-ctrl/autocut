"""Sagoma della persona fotogramma per fotogramma (MediaPipe Selfie Segmentation).

Gira in un ambiente separato (Python 3.12 + mediapipe), non nel progetto:
    uv run --no-project --python 3.12 --with mediapipe==0.10.14 --with opencv-python-headless \
        python matte_worker.py <video.mp4> <cartella>
Per ogni fotogramma scrive <cartella>/00001.jpg ... : bianco = sfondo, nero = persona.
Il render la usa come maschera delle grafiche "dietro": si vedono solo dove non ci sei tu.
Mezza risoluzione (il bordo è morbido comunque): file piccoli. Tutto in locale, gratis.
"""

import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


def main(src: str, dest: str) -> None:
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"non riesco ad aprire {src}")
    seg = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=0)
    prev = None
    frames = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        mask = seg.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).segmentation_mask
        # media mobile: il bordo non "trema" da un fotogramma all'altro
        prev = mask if prev is None else 0.55 * mask + 0.45 * prev
        soft = np.clip((prev - 0.35) / 0.3, 0.0, 1.0)  # bordo netto ma morbido
        h, w = soft.shape
        small = cv2.resize(soft, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 1.2)
        frames += 1
        cv2.imwrite(str(out / f"{frames:05d}.jpg"), ((1.0 - small) * 255).astype(np.uint8),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])  # fmt: skip
    (out / "done.txt").write_text(str(frames))
    print(frames)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
