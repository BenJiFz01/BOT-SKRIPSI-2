"""
Test HealthServer: /health merespons OK, lalu berhenti dengan aman.
"""
import sys
import urllib.request
sys.path.insert(0, r"D:\BOT SKRIPSI 2")

from src.infra.health_server import HealthServer

print("=== TEST HEALTH ENDPOINT ===\n")

hs = HealthServer(host="127.0.0.1", port=8100)
hs.start()

import time
time.sleep(0.8)

try:
    with urllib.request.urlopen("http://127.0.0.1:8100/health", timeout=3) as resp:
        body = resp.read().decode()
        status = resp.status
    ok = status == 200 and body == "OK"
    print(f"GET /health -> status={status}, body='{body}' -> {'PASS' if ok else 'FAIL'}")
except Exception as e:
    print(f"FAIL: {e}")
    hs.stop()
    sys.exit(1)

# Root path juga merespons
try:
    with urllib.request.urlopen("http://127.0.0.1:8100/", timeout=3) as resp:
        body = resp.read().decode()
    print(f"GET / -> status=200, body='{body}' -> {'PASS' if body == 'OK' else 'FAIL'}")
except Exception as e:
    print(f"FAIL: {e}")
    hs.stop()
    sys.exit(1)

hs.stop()
print("\nHealth endpoint ok.")
sys.exit(0)
