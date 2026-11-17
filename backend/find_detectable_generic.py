"""Find which photos YOLO actually detects, for any dataset class folder.
Usage: python find_detectable_generic.py <ClassName>
"""
import pathlib, urllib.request, json, sys

BASE = "http://127.0.0.1:8000"
cls = sys.argv[1] if len(sys.argv) > 1 else "Apple"
FOLDER = pathlib.Path("dataset") / cls

boundary = b"findtest"

for img_path in sorted(FOLDER.glob("*.jpg")):
    jpeg = img_path.read_bytes()
    body  = b"--" + boundary + b"\r\n"
    body += b'Content-Disposition: form-data; name="file"; filename="b.jpg"\r\n'
    body += b"Content-Type: image/jpeg\r\n\r\n"
    body += jpeg + b"\r\n"
    body += b"--" + boundary + b"--\r\n"
    req = urllib.request.Request(
        f"{BASE}/api/v1/scan-item", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
        method="POST"
    )
    try:
        r    = urllib.request.urlopen(req, timeout=30)
        resp = json.loads(r.read())
        label = resp["detected_item"]
        conf  = resp["confidence"]
        tag   = "OK " if label == cls else "   "
        print(f"{tag} {img_path.name:<45} -> {label} {conf}")
    except Exception as e:
        print(f"  ERR {img_path.name}: {e}")
