"""
train_fruit_clf_v2.py - same job as train_fruit_clf.py, but it TRIES 4 ways of naming a fruit,
measures each with leave-one-out on YOUR photos, and saves the best one. No change to main.py needed.

  centroid   : one average fingerprint per fruit            (what you have now)
  kmeans2/3  : 2 or 3 average fingerprints per fruit (e.g. red apple / green apple / apple from the side)
  1-NN       : every photo is its own fingerprint; the closest photo wins

Run from E:\\SHELF:   python train_fruit_clf_v2.py        then restart uvicorn.
First run embeds every photo (a few minutes) and caches them in backend\\emb_cache.npz;
later runs are fast and only embed new photos.
"""
import sys
from pathlib import Path
import numpy as np

DATA = Path("backend") / "dataset"
OUT = Path("backend") / "fruit_clf.npz"
WORLD = Path("backend") / "shelf_fruit_world.pt"
CACHE = Path("backend") / "emb_cache.npz"


# ---------------------------------------------------------------- methods
def unit(v):
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-12)


def kmeans_unit(X, k, seed=0, iters=25):
    k = min(k, len(X))
    rng = np.random.RandomState(seed)
    C = X[rng.choice(len(X), k, replace=False)]
    for _ in range(iters):
        a = np.argmax(X @ C.T, axis=1)
        for j in range(k):
            if np.any(a == j):
                C[j] = unit(X[a == j].mean(axis=0))
    return C


def build_rows(feats, classes, method):
    rows, labels = [], []
    for c in classes:
        X = feats[c]
        if method == "centroid":
            R = unit(X.mean(axis=0))[None, :]
        elif method.startswith("kmeans"):
            R = kmeans_unit(X, int(method[-1]))
        else:                                   # 1nn
            R = X
        rows.append(R)
        labels += [c] * len(R)
    return np.vstack(rows).astype(np.float32), labels


def predict(rows, labels, x):
    return labels[int(np.argmax(rows @ x))]


def loo(feats, classes, method):
    per = {}
    for c in classes:
        good = 0
        for i in range(len(feats[c])):
            f2 = dict(feats)
            f2[c] = np.delete(feats[c], i, axis=0)
            rows, labels = build_rows(f2, classes, method)
            good += predict(rows, labels, feats[c][i]) == c
        per[c] = (good, len(feats[c]))
    tot = sum(g for g, _ in per.values()); n = sum(n for _, n in per.values())
    return per, tot / n


def choose_and_save(feats, classes, out):
    methods = ["centroid", "kmeans2", "kmeans3", "1nn"]
    res = {}
    for m in methods:
        per, acc = loo(feats, classes, m)
        res[m] = (per, acc)
    print("\nLeave-one-out accuracy (measured on your photos):")
    print("  %-12s" % "" + "".join("%10s" % m for m in methods))
    for c in classes:
        print("  %-12s" % c + "".join("%10s" % ("%d/%d" % res[m][0][c]) for m in methods))
    print("  %-12s" % "OVERALL" + "".join("%9.1f%%" % (100 * res[m][1]) for m in methods))
    best = max(methods, key=lambda m: (res[m][1], -methods.index(m)))   # ties -> simpler method
    rows, labels = build_rows(feats, classes, best)
    np.savez(out, centroids=rows, labels=np.array(labels))
    print("\nBest method: %s (%.1f%%). Saved %s with %d fingerprints for: %s"
          % (best, 100 * res[best][1], out, len(rows), ", ".join(classes)))
    return best, res


# ---------------------------------------------------------------- embedding (heavy part)
def embed_all(classes):
    import torch, clip
    import os
    os.environ["ULTRALYTICS_RUNS_DIR"] = r"E:\\SHELF\\runs"
    from PIL import Image
    from ultralytics import YOLOWorld
    world = YOLOWorld(str(WORLD))
    model, pre = clip.load("ViT-B/32", device="cpu"); model.eval()

    def crop_of(img):
        r = world.predict(np.array(img), conf=0.05, verbose=False)[0]
        if len(r.boxes) == 0:
            return img
        i = int(r.boxes.conf.argmax())
        x1, y1, x2, y2 = [float(v) for v in r.boxes.xyxy[i]]
        w, h = x2 - x1, y2 - y1; pad = 0.08
        return img.crop((max(0, int(x1 - pad * w)), max(0, int(y1 - pad * h)),
                         min(img.width, int(x2 + pad * w)), min(img.height, int(y2 + pad * h))))

    def embed(img):
        with torch.no_grad():
            e = model.encode_image(pre(img).unsqueeze(0)).float()
            e = e / e.norm(dim=-1, keepdim=True)
        return e[0].numpy()

    cache = {}
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=True)
        cache = dict(zip([str(k) for k in z["keys"]], z["vecs"]))
    feats = {}
    new = 0
    for c in classes:
        vs = []
        files = sorted((DATA / c).glob("*.jpg"))
        for k, f in enumerate(files):
            key = "%s|%d|%d" % (f.as_posix(), f.stat().st_size, int(f.stat().st_mtime))
            if key not in cache:
                cache[key] = embed(crop_of(Image.open(f).convert("RGB"))); new += 1
            vs.append(cache[key])
            if (k + 1) % 10 == 0:
                print("    %s: %d/%d" % (c, k + 1, len(files)))
        feats[c] = np.array(vs)
    keys = list(cache.keys())
    np.savez(CACHE, keys=np.array(keys), vecs=np.array([cache[k] for k in keys]))
    print("  embedded %d new photo(s); cache saved to %s" % (new, CACHE))
    return feats


def main():
    if not DATA.exists():
        sys.exit("STOP: backend\\dataset not found (run from E:\\SHELF).")
    classes = sorted(d.name for d in DATA.iterdir() if d.is_dir() and len(list(d.glob("*.jpg"))) > 0)
    if len(classes) < 2:
        sys.exit("STOP: need photos for at least 2 fruits.")
    for c in classes:
        n = len(list((DATA / c).glob("*.jpg")))
        print("  %s: %d photos" % (c, n))
        if n < 8:
            sys.exit("STOP: only %d photos for '%s' (need 8+)." % (n, c))
    feats = embed_all(classes)
    choose_and_save(feats, classes, OUT)
    print("Now restart uvicorn.")


if __name__ == "__main__":
    main()
