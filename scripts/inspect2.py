import json
from pathlib import Path

data = json.loads(Path("data/MCR_extract.json").read_text(encoding="utf-8"))

# Chaves de nivel superior
print("Chaves top-level:", list(data.keys()))
print()

# artifacts
artifacts = data.get("artifacts", [])
print("Total artifacts:", len(artifacts))
print()
print("Primeiros 5 artifacts:")
for a in artifacts[:5]:
    print(json.dumps(a, ensure_ascii=False, indent=2))
    print()

# H1 elements
print("=== Elementos H1 (primeiros 5) ===")
count = 0
elements = data.get("elements", [])
for el in elements:
    p = el.get("Path", "")
    if p.endswith("/H1") or "/H1[" in p:
        print("Page", el["Page"], "| Path:", p, "| Text:", el.get("Text",""))
        count += 1
        if count >= 5:
            break
