import sys, time, json, uuid, urllib.request

url   = "http://127.0.0.1:8000/api/v1/scan-item"
path  = sys.argv[1]
n     = int(sys.argv[2]) if len(sys.argv) > 2 else 20
data  = open(path, "rb").read()

def one():
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"x.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST",
          headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    t = time.perf_counter()
    r = urllib.request.urlopen(req, timeout=60).read()
    return time.perf_counter() - t, r.decode()

t0, r0 = one()
print(f"warm-up (model load, not counted): {t0:.2f} s")
print("result:", r0[:200])
ts = []
for i in range(n):
    t, _ = one()
    ts.append(t)
    print(f"scan {i+1:2d}: {t:.2f} s")
ts.sort()
print(f"\nn={n}  mean={sum(ts)/n:.2f} s  median={ts[n//2]:.2f} s  min={ts[0]:.2f}  max={ts[-1]:.2f}")
