"""
detector_train.py  (step 2 of 3)  Fine-tunes YOLOv8n on detector_data\\ and reports MEASURED scores on the held-out test photos.
Run from E:\\SHELF:   python detector_train.py        (CPU: roughly 20-60 min; stop with Ctrl+C is safe, re-run to restart)
Saves the result as backend\\shelf_detector.pt  (not used until you run patch_detector.py).
"""
import shutil, sys
from pathlib import Path

DATA = Path("detector_data") / "data.yaml"
OUT = Path("backend") / "shelf_detector.pt"


def main():
    if not DATA.exists():
        sys.exit("STOP: run detector_prepare.py first.")
    from ultralytics import YOLO
    start = Path("backend") / "yolov8n.pt"
    model = YOLO(str(start) if start.exists() else "yolov8n.pt")      # downloads ~6 MB once if missing
    model.train(data=str(DATA.resolve()), epochs=60, imgsz=640, batch=8, patience=15, workers=0,
                project="E:/SHELF/runs/detect", name="fruit", exist_ok=True, verbose=False)
    best = Path("detector_runs") / "fruit" / "weights" / "best.pt"
    if not best.exists():
        sys.exit("STOP: training did not produce best.pt - scroll up for the error.")
    m = YOLO(str(best)).val(data=str(DATA.resolve()), split="val", verbose=False)
    names = YOLO(str(best)).names
    print("\n=== MEASURED on the held-out test photos (never trained on) ===")
    print("precision %.1f%%   recall %.1f%%   mAP@0.5 %.1f%%" % (100 * m.box.mp, 100 * m.box.mr, 100 * m.box.map50))
    for i, ap in zip(m.box.ap_class_index, m.box.ap50):
        print("  %-12s AP@0.5 %.1f%%" % (names[int(i)], 100 * ap))
    print("Caveat: test photos come from the same scanning sessions as the training photos, so real-shelf results can be lower.")
    shutil.copy2(best, OUT)
    print("Saved", OUT, "\nNext: python patch_detector.py   then restart uvicorn.")


if __name__ == "__main__":
    main()
