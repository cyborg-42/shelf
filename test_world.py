"""
Compare how YOLO-World separates the fruits for different class NAMES.
Run from E:\\SHELF:
    .\\.venv\\Scripts\\python.exe test_world.py pom.jpg apple.jpg
Prints, for each photo and each naming style, the top detections (class + confidence).
Nothing is changed in your project.
"""
import sys
from ultralytics import YOLOWorld

if len(sys.argv) < 2:
    sys.exit("Usage: test_world.py photo1.jpg [photo2.jpg ...]")

VOCABS = {
    "A plain (what the server uses now)": ["apple", "orange", "guava", "pomegranate"],
    "B + word 'fruit'": ["apple fruit", "orange fruit", "guava fruit", "pomegranate fruit"],
    "C descriptive": ["a smooth shiny apple", "an orange citrus fruit",
                      "a green guava", "a pomegranate with a crown on top and rough skin"],
}

for vname, vocab in VOCABS.items():
    print("\n" + "=" * 70 + f"\n{vname}\n   {vocab}")
    m = YOLOWorld("yolov8s-worldv2.pt")
    m.set_classes(vocab)
    for img in sys.argv[1:]:
        r = m.predict(img, conf=0.01, verbose=False)[0]
        rows = []
        for b in r.boxes:
            rows.append((float(b.conf[0]), vocab[int(b.cls[0])]))
        rows.sort(reverse=True)
        print(f"  {img}:")
        if not rows:
            print("     (nothing found)")
        for c, n in rows[:5]:
            print(f"     {c:5.2f}  {n}")
