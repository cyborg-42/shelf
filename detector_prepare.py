"""
detector_prepare.py  (step 1 of 3 for your own fruit detector)
Turns your photos in backend\\dataset\\<fruit>\\*.jpg into a YOLO training set:
  - boxes come from your current YOLO-World model (the folder name is the class - you already sorted the photos)
  - 20% of the photos per fruit are held back as a TEST set that the detector never trains on
  - writes review pictures so you can eyeball the boxes before training
Run from E:\\SHELF:   python detector_prepare.py
Output: detector_data\\ (images, labels, data.yaml, review\\*.jpg, needs_review.txt)
"""
import random, shutil, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

DATA = Path("backend") / "dataset"
WORLD = Path("backend") / "shelf_fruit_world.pt"
OUT = Path("detector_data")
VAL_FRAC = 0.20
MIN_CONF = 0.05      # smallest box score kept as a label
REL_CONF = 0.40      # also drop boxes much weaker than the best one in the same photo


def pick_boxes(boxes, rel=REL_CONF):
    """boxes: list of (x1,y1,x2,y2,conf). Keep the best, plus others at least REL_CONF x as strong."""
    if not boxes:
        return []
    top = max(b[4] for b in boxes)
    thr = max(MIN_CONF, rel * top)
    kept = [b for b in boxes if b[4] >= thr]
    return kept or [max(boxes, key=lambda b: b[4])]


def to_yolo(b, W, H):
    x1, y1, x2, y2 = b[:4]
    return ((x1 + x2) / 2 / W, (y1 + y2) / 2 / H, (x2 - x1) / W, (y2 - y1) / H)


def split(files, seed=0):
    f = sorted(files)
    random.Random(seed).shuffle(f)
    nv = max(2, int(round(len(f) * VAL_FRAC)))
    return f[nv:], f[:nv]


def suspicious(boxes, W, H):
    if not boxes:
        return "no box"
    if len(boxes) > 6:
        return "%d boxes" % len(boxes)
    for b in boxes:
        a = (b[2] - b[0]) * (b[3] - b[1]) / (W * H)
        if a < 0.03:
            return "tiny box"
        if a > 0.85:
            return "box covers the whole photo"
    return ""


def sheet(items, path, cols=6, cell=220):
    rows = (len(items) + cols - 1) // cols
    S = Image.new("RGB", (cols * cell, rows * cell), "white")
    for k, (img, boxes) in enumerate(items):
        t = img.copy(); W, H = t.size
        d = ImageDraw.Draw(t)
        for b in boxes:
            d.rectangle(b[:4], outline=(255, 0, 0), width=max(3, W // 150))
        t.thumbnail((cell - 6, cell - 6))
        S.paste(t, ((k % cols) * cell + 3, (k // cols) * cell + 3))
    S.save(path, quality=85)


def main():
    if not DATA.exists() or not WORLD.exists():
        sys.exit("STOP: run from E:\\SHELF (need backend\\dataset and backend\\shelf_fruit_world.pt).")
    classes = sorted(d.name for d in DATA.iterdir() if d.is_dir() and any(d.glob("*.jpg")))
    from ultralytics import YOLOWorld
    world = YOLOWorld(str(WORLD))
    if OUT.exists():
        shutil.rmtree(OUT)
    for s in ("train", "val"):
        (OUT / "images" / s).mkdir(parents=True)
        (OUT / "labels" / s).mkdir(parents=True)
    (OUT / "review").mkdir()
    flagged, skipped, counts = [], [], {}
    for ci, c in enumerate(classes):
        tr, va = split(list(( DATA / c).glob("*.jpg")))
        sheet_items = []
        for sname, files in (("train", tr), ("val", va)):
            for f in files:
                img = Image.open(f).convert("RGB")
                W, H = img.size
                r = world.predict(np.array(img), conf=MIN_CONF, iou=0.5, agnostic_nms=True, verbose=False)[0]
                boxes = [tuple(float(v) for v in xy) + (float(cf),)
                         for xy, cf in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist())]
                boxes = pick_boxes(boxes, 0.15 if c == "Orange" else REL_CONF)
                why = suspicious(boxes, W, H)
                if why:
                    flagged.append("%s | %s | %s" % (c, f.name, why))
                if not boxes:
                    skipped.append(str(f)); continue
                name = "%s_%s" % (c, f.stem)
                img.save(OUT / "images" / sname / (name + ".jpg"), quality=95)
                with open(OUT / "labels" / sname / (name + ".txt"), "w") as fh:
                    for b in boxes:
                        fh.write("%d %.6f %.6f %.6f %.6f\n" % ((ci,) + to_yolo(b, W, H)))
                sheet_items.append((img, boxes))
                counts.setdefault(c, [0, 0])[0 if sname == "train" else 1] += 1
        sheet(sheet_items, OUT / "review" / (c + ".jpg"))
    yaml = "path: %s\ntrain: images/train\nval: images/val\nnames:\n" % OUT.resolve().as_posix()
    yaml += "".join("  %d: %s\n" % (i, c) for i, c in enumerate(classes))
    (OUT / "data.yaml").write_text(yaml)
    (OUT / "needs_review.txt").write_text("\n".join(flagged + ["", "SKIPPED (no box found):"] + skipped))
    print("\nphotos per fruit  (train / test):")
    for c in classes:
        print("  %-12s %3d / %d" % (c, *counts.get(c, [0, 0])))
    print("\nflagged for a look: %d   skipped (no box): %d" % (len(flagged), len(skipped)))
    print("Open detector_data\\review\\*.jpg - red boxes should sit on the fruit. Bad ones are listed in needs_review.txt.")
    print("Next: python detector_train.py")


if __name__ == "__main__":
    main()
