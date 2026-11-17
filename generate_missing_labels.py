#!/usr/bin/env python3
"""Generate YOLO‑v8 label files for any training images that currently lack them.
It scans ``detector_data/images/train`` and creates a ``.txt`` file next to each image
in ``detector_data/labels/train``.
If a label already exists we skip it.
For missing labels we write a *full‑image* box (center=0.5,0.5 width=1, height=1)
using the class index defined in ``detector_data/data.yaml``.
This allows the detector to see all classes during training – the boxes will be
coarse but sufficient for a quick functional model.
"""
import os
from pathlib import Path
import json

# Load class mapping from data.yaml (the file is small and simple)
DATA_YAML = Path("E:/SHELF/detector_data/data.yaml")
# Parse the yaml manually (avoid external deps)
class_map = {}
with open(DATA_YAML) as f:
    for line in f:
        line = line.strip()
        if line.startswith("0:") or line.startswith("1:") or line.startswith("2:") or line.startswith("3:") or line.startswith("4:") or line.startswith("5:") or line.startswith("6:"):
            # e.g. "0: Apple"
            idx, name = line.split(":", 1)
            class_map[name.strip()] = int(idx.strip())

# Directories
IMG_TRAIN = Path("E:/SHELF/detector_data/images/train")
LBL_TRAIN = Path("E:/SHELF/detector_data/labels/train")
LBL_TRAIN.mkdir(parents=True, exist_ok=True)

# Helper to write a full‑image box
BOX_LINE = "{cls} 0.5 0.5 1.0 1.0\n"

# Walk through all jpg files
for img_path in IMG_TRAIN.rglob("*.jpg"):
    base = img_path.stem
    label_path = LBL_TRAIN / f"{base}.txt"
    if label_path.exists():
        continue  # already has a label
    # Determine class from filename (we assume the fruit name appears in the filename)
    fruit = None
    for name in class_map:
        if name.lower() in base.lower():
            fruit = name
            break
    if fruit is None:
        # fallback to Apple (index 0) – you can edit manually later
        fruit = "Apple"
    cls_idx = class_map[fruit]
    with open(label_path, "w") as out:
        out.write(BOX_LINE.format(cls=cls_idx))
print(f"Generated missing label files in {LBL_TRAIN}")

