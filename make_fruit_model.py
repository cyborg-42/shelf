"""
Builds the Shelf fruit model ONCE: YOLO-World with a custom fruit/veg vocabulary
(includes guava, pomegranate, mango ... which the standard COCO model does not know).

Run from E:\\SHELF with the SAME python the server uses:
    .\\.venv\\Scripts\\python.exe make_fruit_model.py

Needs: internet, and git installed (it fetches the small CLIP text-encoder package once).
Output: backend\\shelf_fruit_world.pt   (the server does not need CLIP afterwards)
Edit CLASSES below to add/remove produce, then run it again.
"""
import subprocess
import sys
from pathlib import Path

CLASSES = ["apple", "orange", "guava", "pomegranate", "carrot", "ginger", "cucumber", "lemon", "tomato"]
OUT = Path("backend") / "shelf_fruit_world.pt"
if not OUT.parent.exists():
    sys.exit("STOP: run this from E:\\SHELF (folder 'backend' not found).")

try:
    import clip  # noqa: F401
except ImportError:
    print("Installing the CLIP text encoder (one time, needs git + internet)...")
    r = subprocess.call([sys.executable, "-m", "pip", "install", "git+https://github.com/ultralytics/CLIP.git"])
    if r != 0:
        sys.exit("STOP: pip could not install CLIP. Is git installed?  (run:  git --version)")

from ultralytics import YOLOWorld

print("Loading YOLO-World (downloads ~25 MB the first time)...")
m = YOLOWorld("yolov8s-worldv2.pt")
m.set_classes(CLASSES)          # downloads the CLIP text model (~350 MB) the first time
m.save(str(OUT))
print(f"\nOK  saved {OUT}  ({OUT.stat().st_size / 1e6:.0f} MB) with classes:\n   {', '.join(CLASSES)}")
print("Next: python patch_world_model.py   then restart uvicorn.")
