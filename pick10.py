import os, shutil

SRC = r"E:\SHELF\hf_fruitveg"
DST = r"E:\SHELF\fruitveg10"
CLASSES = ["apple", "orange", "pomegranate", "banana", "mango",
           "pear", "tomato", "potato", "onion", "carrot"]

for split_src, split_dst in [("train", "train"), ("validation", "val")]:
    for c in CLASSES:
        s = os.path.join(SRC, split_src, c)
        d = os.path.join(DST, split_dst, c)
        if not os.path.isdir(s):
            print("MISSING", s)
            continue
        os.makedirs(d, exist_ok=True)
        files = [f for f in os.listdir(s) if f.lower().endswith(".jpg")]
        for f in files:
            shutil.copy2(os.path.join(s, f), os.path.join(d, f))
        print(f"{split_dst}/{c}: {len(files)}")

print("Done. Output in", DST)