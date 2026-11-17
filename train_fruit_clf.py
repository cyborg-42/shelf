"""
Trains the fruit classifier from your collected photos (backend\\dataset\\<fruit>\\*.jpg).
Run from E:\\SHELF:   .\\.venv\\Scripts\\python.exe train_fruit_clf.py
Writes backend\\fruit_clf.npz  (then restart uvicorn). Needs >= 8 photos per fruit (20-40 is good).
"""
import sys
from pathlib import Path

import numpy as np
import torch
import clip
from PIL import Image
from ultralytics import YOLOWorld

DATA = Path("backend") / "dataset"
OUT = Path("backend") / "fruit_clf.npz"
WORLD = Path("backend") / "shelf_fruit_world.pt"
if not DATA.exists():
    sys.exit("STOP: backend\\dataset not found. Collect photos first (run from E:\\SHELF).")

classes = sorted(d.name for d in DATA.iterdir() if d.is_dir() and len(list(d.glob("*.jpg"))) > 0)
if len(classes) < 2:
    sys.exit("STOP: need photos for at least 2 fruits in backend\\dataset.")
for c in classes:
    n = len(list(( DATA / c).glob("*.jpg")))
    print(f"  {c}: {n} photos")
    if n < 8:
        sys.exit(f"STOP: only {n} photos for '{c}'. Collect at least 8 (20-40 is better).")

world = YOLOWorld(str(WORLD))
model, pre = clip.load("ViT-B/32", device="cpu")
model.eval()


def crop_of(img):
    r = world.predict(np.array(img), conf=0.05, verbose=False)[0]
    if len(r.boxes) == 0:
        return img
    i = int(r.boxes.conf.argmax())
    x1, y1, x2, y2 = [float(v) for v in r.boxes.xyxy[i]]
    w, h = x2 - x1, y2 - y1
    pad = 0.08
    return img.crop((max(0, int(x1 - pad * w)), max(0, int(y1 - pad * h)),
                     min(img.width, int(x2 + pad * w)), min(img.height, int(y2 + pad * h))))


def embed(img):
    with torch.no_grad():
        e = model.encode_image(pre(img).unsqueeze(0)).float()
        e = e / e.norm(dim=-1, keepdim=True)
    return e[0].numpy()


feats = {}
for c in classes:
    feats[c] = []
    files = sorted((DATA / c).glob("*.jpg"))
    for k, f in enumerate(files):
        feats[c].append(embed(crop_of(Image.open(f).convert("RGB"))))
        if (k + 1) % 10 == 0:
            print(f"    {c}: embedded {k + 1}/{len(files)}")
    feats[c] = np.array(feats[c])

# leave-one-out accuracy (honest estimate)
print("\nLeave-one-out accuracy:")
tot = ok = 0
for c in classes:
    good = 0
    for i in range(len(feats[c])):
        cents = []
        for c2 in classes:
            X = feats[c2] if c2 != c else np.delete(feats[c2], i, axis=0)
            m = X.mean(axis=0)
            cents.append(m / np.linalg.norm(m))
        pred = classes[int(np.argmax(np.array(cents) @ feats[c][i]))]
        good += pred == c
    print(f"  {c}: {good}/{len(feats[c])}")
    tot += len(feats[c])
    ok += good
print(f"  overall: {100 * ok / tot:.0f}%")

cent = []
for c in classes:
    m = feats[c].mean(axis=0)
    cent.append(m / np.linalg.norm(m))
np.savez(OUT, centroids=np.array(cent, dtype=np.float32), labels=np.array(classes))
print(f"\nOK  saved {OUT} for: {', '.join(classes)}\nNow restart uvicorn.")
