"""Extract per-room photos + ground-truth text from the InventoryFlex sample report.

Source: https://inventoryflex.co.uk/sample-of-report (Inventory Report sample,
downloaded to benchmarks/samples/inventoryflex-inventory.pdf).

The PDF's page labels ("Page N of 35") map to 0-indexed physical pages as N
(cover page is unnumbered physical page 0). Room sections per the contents page:

    Entrance Hall                     5-8
    Walk In Wardrobe                  9-11
    Bathroom                          12-16
    Bedroom                           17-20
    Reception & Open Plan Kitchen     21-32
    Balcony                           33

Outputs:
    benchmarks/inventoryflex/capture/<Room>/pNN_iMM.jpg   (photos >= 300px)
    benchmarks/inventoryflex/ground-truth.txt             (schedule + room tables)
"""
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

HERE = Path(__file__).parent
PDF = HERE / "samples" / "inventoryflex-inventory.pdf"
OUT = HERE / "inventoryflex"

ROOM_PAGES = {
    "Entrance Hall": range(5, 9),
    "Walk In Wardrobe": range(9, 12),
    "Bathroom": range(12, 17),
    "Bedroom": range(17, 21),
    "Reception & Open Plan Kitchen": range(21, 33),
    "Balcony": range(33, 34),
}
MIN_DIM = 300  # skip logos / icons

reader = PdfReader(PDF)

total = 0
for room, pages in ROOM_PAGES.items():
    room_dir = OUT / "capture" / room
    room_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for pno in pages:
        for ino, img in enumerate(reader.pages[pno].images):
            pil = Image.open(BytesIO(img.data))
            if min(pil.size) < MIN_DIM:
                continue
            dest = room_dir / f"p{pno:02d}_i{ino:02d}.jpg"
            if pil.mode != "RGB":
                pil = pil.convert("RGB")
            pil.save(dest, "JPEG", quality=92)
            count += 1
    total += count
    print(f"{room}: {count} photos")
print(f"total: {total}")

# Ground truth: text of schedule-of-condition + all room table pages (4-33).
text_pages = []
for pno in range(4, 34):
    text_pages.append(f"--- page {pno} ---\n" + (reader.pages[pno].extract_text() or ""))
(OUT / "ground-truth.txt").write_text("\n\n".join(text_pages), encoding="utf-8")
print("ground-truth.txt written")
