"""Render an Inventory to HTML (always) and PDF (when WeasyPrint can run)."""

from __future__ import annotations

import logging
import shutil
from dataclasses import asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import Inventory

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"


def _export_photos(inv: Inventory, capture_dir: Path, out_dir: Path,
                   max_dim: int = 1400) -> dict[str, str]:
    """Copy (downscaled) report photos to out_dir/photos; return id -> rel path."""
    from PIL import Image

    photos_dir = out_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    src_map: dict[str, str] = {}
    for room in inv.rooms:
        for p in room.photos:
            src = Path(p.path)
            if not src.is_absolute():
                src = capture_dir / p.path
            dest = photos_dir / f"{p.id}.jpg"
            try:
                with Image.open(src) as im:
                    im = im.convert("RGB")
                    if max(im.size) > max_dim:
                        im.thumbnail((max_dim, max_dim))
                    im.save(dest, quality=88)
            except Exception as e:
                log.warning("could not re-encode %s (%s); copying as-is — the "
                            "report image may not render", src, e)
                shutil.copyfile(src, dest)
            src_map[p.id] = f"photos/{p.id}.jpg"
    return src_map


def render(inv: Inventory, capture_dir: Path, out_dir: Path,
           pdf: bool = True) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    photo_src = _export_photos(inv, capture_dir, out_dir)

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        inv=inv,
        photo_src=photo_src,
        total_items=inv.item_count(),
        total_photos=inv.photo_count(),
        reviewed_items=inv.reviewed_count(),
        # embedded for the in-report review layer (Level 1)
        payload={"inventory": asdict(inv), "photo_src": photo_src},
    )

    outputs: dict[str, Path] = {}
    html_path = out_dir / "inventory.html"
    html_path.write_text(html, encoding="utf-8")
    outputs["html"] = html_path

    json_path = out_dir / "inventory.json"
    json_path.write_text(inv.to_json(), encoding="utf-8")
    outputs["json"] = json_path

    if pdf:
        try:
            from weasyprint import HTML
            pdf_path = out_dir / "inventory.pdf"
            HTML(string=html, base_url=str(out_dir)).write_pdf(str(pdf_path))
            outputs["pdf"] = pdf_path
        except Exception as e:
            log.warning("PDF generation unavailable (%s); HTML report is complete "
                        "— print it to PDF from a browser if needed.", e)
    return outputs
