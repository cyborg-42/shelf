import sys, os, json, uuid, urllib.request, urllib.error
url = "http://127.0.0.1:8000/api/v1/scan-item"
root = "testset"
def scan(path):
    data = open(path, "rb").read(); b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"x.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return r.get("detected_item") if r.get("success") else None
    except urllib.error.HTTPError:
        return None
classes = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
pred = {}   # true class -> list of predicted
for c in classes:
    pred[c] = []
    for f in sorted(os.listdir(os.path.join(root, c))):
        if f.lower().endswith((".jpg", ".jpeg", ".png")):
            p = scan(os.path.join(root, c, f)); pred[c].append(p)
            print(f"{c:<12} {f:<28} -> {p}")
print("\nclass        n   TP  FP  FN  precision  recall")
tot_tp = tot_n = 0
for c in classes:
    n = len(pred[c]); tp = sum(1 for p in pred[c] if p and p.lower() == c.lower())
    fp = sum(1 for k in classes if k != c for p in pred[k] if p and p.lower() == c.lower())
    fn = n - tp
    prec = tp / (tp + fp) if tp + fp else 0; rec = tp / n if n else 0
    tot_tp += tp; tot_n += n
    print(f"{c:<12} {n:>3} {tp:>3} {fp:>3} {fn:>3}   {prec*100:6.1f}%  {rec*100:6.1f}%")
print(f"\noverall accuracy: {tot_tp}/{tot_n} = {tot_tp/tot_n*100:.1f}%")
