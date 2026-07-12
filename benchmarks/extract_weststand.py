"""Extract per-area photos and source text from the Weststand gold report.

The PDF's printed page numbers match its zero-based physical page indexes because
the unnumbered cover is physical page 0. Inventory areas and printed page ranges:

    Entrance/Hallway          9-11
    Reception/Kitchen        12-16
    Kitchen and appliances   17-19
    Bathroom                 20-22
    Office room              23-24
    Bedroom                  25-29
    En-suite bathroom        30-34

Outputs:
    benchmarks/eoin/capture/<Area>/pNN_iMM.jpg
    benchmarks/eoin/ground-truth.txt
"""

from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader


HERE = Path(__file__).parent / "eoin"
PDF = next(HERE.glob("*.pdf"))

AREA_PAGES = {
    "Entrance Hallway": range(9, 12),
    "Reception Kitchen": range(12, 17),
    "Kitchen and Appliances": range(17, 20),
    "Bathroom": range(20, 23),
    "Office Room": range(23, 25),
    "Bedroom": range(25, 30),
    "En-suite Bathroom": range(30, 35),
}
MIN_DIM = 300


def main() -> None:
    reader = PdfReader(PDF)
    total = 0
    for area, pages in AREA_PAGES.items():
        area_dir = HERE / "capture" / area
        area_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for page_number in pages:
            for image_number, image in enumerate(reader.pages[page_number].images):
                pil = Image.open(BytesIO(image.data))
                if min(pil.size) < MIN_DIM:
                    continue
                if pil.mode != "RGB":
                    pil = pil.convert("RGB")
                destination = area_dir / f"p{page_number:02d}_i{image_number:02d}.jpg"
                pil.save(destination, "JPEG", quality=92)
                count += 1
        total += count
        print(f"{area}: {count} photos")
    print(f"total: {total}")

    text_pages = []
    for page_number in range(6, 35):
        text = reader.pages[page_number].extract_text() or ""
        text_pages.append(f"--- page {page_number} ---\n{text}")
    (HERE / "ground-truth.txt").write_text(
        "\n\n".join(text_pages), encoding="utf-8"
    )
    print("ground-truth.txt written")


if __name__ == "__main__":
    main()
