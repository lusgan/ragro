import json
from pathlib import Path

data = json.loads(Path("data/MCR_extract.json").read_text(encoding="utf-8"))
elements = data["elements"]

# Tipos de Path distintos (ultimo segmento)
segs = sorted(set(el.get("Path","").split("/")[-1] for el in elements))
print("Tipos de Path encontrados:")
for s in segs:
    print(" ", s)

print()

# Headers/footers de artefato
print("=== ARTIFACT Headers/Footers (primeiros 10) ===")
count = 0
for el in elements:
    p = el.get("Path","")
    if "Artifact" in p:
        print("Page", el["Page"], "|", repr(el.get("Text","")))
        count += 1
        if count >= 10:
            break

print()

# H1/H2/H3
print("=== H1/H2/H3 (primeiros 10) ===")
count = 0
for el in elements:
    p = el.get("Path","")
    if "/H1" in p or "/H2" in p or "/H3" in p:
        print("Page", el["Page"], "| Path:", p, "|", repr(el.get("Text","")))
        count += 1
        if count >= 10:
            break
