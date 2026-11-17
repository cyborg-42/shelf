import os
from ultralytics import YOLO
m = YOLO("shelf_detector.pt")
print("detector classes:", m.names)
folder = r"testset\Banana"
for f in sorted(os.listdir(folder)):
    r = m.predict(os.path.join(folder, f), conf=0.05, verbose=False)[0]
    boxes = sorted([(float(b.conf), m.names[int(b.cls)]) for b in r.boxes], reverse=True)[:3]
    print(f, "->", [(n, round(c, 2)) for c, n in boxes])
