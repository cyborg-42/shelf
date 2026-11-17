import os
from datasets import load_dataset

OUT = r"E:\SHELF\hf_fruitveg"

ds = load_dataset("SunnyAgarwal4274/Food_and_Vegetables")
print(ds)

for split, d in ds.items():
    img_col = next(c for c, f in d.features.items() if f.__class__.__name__ == "Image")
    lab_col = next(c for c, f in d.features.items() if f.__class__.__name__ == "ClassLabel")
    names = d.features[lab_col].names
    counts = {}
    for i, row in enumerate(d):
        name = names[row[lab_col]]
        folder = os.path.join(OUT, split, name)
        os.makedirs(folder, exist_ok=True)
        row[img_col].convert("RGB").save(os.path.join(folder, f"{i:05d}.jpg"), quality=95)
        counts[name] = counts.get(name, 0) + 1
    print(split, counts)

print("Done. Images are in", OUT)