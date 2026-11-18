"""Riquadro del volto fotogramma per fotogramma (MediaPipe Face Detection).

Gira in un ambiente separato (Python 3.12 + mediapipe), non nel progetto:
    uv run --no-project --python 3.12 --with mediapipe==0.10.14 --with opencv-python-headless \
        python face_worker.py <video.mp4> <uscita.json>
Scrive una lista con un elemento per fotogramma: [x, y, larghezza, altezza] in frazioni
dell'immagine, oppure null se il volto non c'è. Serve a «Genera AI» per rimettere sopra SOLO la
testa vera quando l'AI cambia i vestiti. Tutto in locale, gratis.
"""

import json
import sys

import cv2
import mediapipe as mp


def main(src: str, dest: str) -> None:
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"non riesco ad aprire {src}")
    boxes = []
    det = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.4)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        found = det.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).detections
        if found:
            b = max(found, key=lambda d: d.score[0]).location_data.relative_bounding_box
            boxes.append([round(v, 5) for v in (b.xmin, b.ymin, b.width, b.height)])
        else:
            boxes.append(None)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(boxes, fh)
    print(len(boxes))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
