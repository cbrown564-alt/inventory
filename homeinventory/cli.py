"""homeinventory CLI.

  homeinventory guide                          # print the photo capture checklist
  homeinventory build CAPTURE_DIR -o OUT_DIR   # run the full pipeline
  homeinventory curate-only CAPTURE_DIR -o OUT_DIR
                                               # re-run hero curation + render
                                               # from existing inventory.json
  homeinventory review CAPTURE_DIR -o OUT_DIR  # local review web app (--share
                                               # adds a tenant link)
  homeinventory check CAPTURE_DIR              # detector-only coverage check
  homeinventory compare CHECKIN CHECKOUT -o DIR  # check-in vs check-out
                                               # delta report (docs/08)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .schema import Inventory

log = logging.getLogger("homeinventory")

DETECT_MODE_CHOICES = ("text", "prompt_free")


def _detector_from_args(args) -> "Detector | None":
    from .detect import Detector, default_model

    if getattr(args, "no_detect", False):
        return None
    mode = getattr(args, "detect_mode", "text")
    model = getattr(args, "detect_model", None) or default_model(mode)
    return Detector(
        model_name=model,
        mode=mode,
        conf=args.det_conf,
        device=getattr(args, "device", None),
    )


def _add_detect_args(p):
    p.add_argument("--detect-mode", choices=DETECT_MODE_CHOICES, default="text",
                   help="YOLOE mode: text (household vocabulary) or prompt_free "
                        "(built-in LVIS/Objects365 vocab)")
    p.add_argument("--detect-model", default=None,
                   help="override YOLOE weights (default follows --detect-mode)")
    p.add_argument("--device", default=None,
                   help="torch device for YOLOE (cpu, cuda, 0, …)")


def cmd_guide(args) -> int:
    from .guide import guide_text
    print(guide_text(args.use_case))
    return 0


def cmd_build(args) -> int:
    from .pipeline import BuildOptions, run_build
    return run_build(BuildOptions.from_args(args)).exit_code


def cmd_curate_only(args) -> int:
    """Re-run frame curation on an existing build (no describe/detect cost).

    Reloads inventory.json, re-scores every frame path, re-elects hero ranks,
    saves inventory.json, and re-renders HTML — same post-curate path as build.
    """
    from .curate import curate
    from .report import render
    from .schema import Inventory

    capture_dir = Path(args.capture_dir)
    out_dir = Path(args.out)
    if not capture_dir.is_dir():
        print(f"error: capture dir not found: {capture_dir}", file=sys.stderr)
        return 2
    inv_path = out_dir / "inventory.json"
    if not inv_path.is_file():
        print(f"error: no inventory.json at {inv_path} — run build first",
              file=sys.stderr)
        return 2
    work_dir = out_dir / "work"
    inv = Inventory.from_json(inv_path.read_text(encoding="utf-8"))
    if not inv.rooms:
        print("error: inventory has no rooms", file=sys.stderr)
        return 2
    rooms = {r.name: r.photos for r in inv.rooms}
    curate(rooms, capture_dir, work_dir)
    outputs = render(inv, capture_dir, out_dir, pdf=not args.no_pdf,
                     use_case=args.use_case)
    print(f"re-curated {inv.photo_count()} photos across {len(inv.rooms)} rooms.")
    for kind, path in outputs.items():
        print(f"  {kind:5} {path}")
    return 0


def cmd_render(args) -> int:
    """Re-render the report from an edited inventory.json (review loop)."""
    from .report import render
    out_dir = Path(args.out)
    inv = Inventory.from_json((out_dir / "inventory.json").read_text(encoding="utf-8"))
    render(inv, Path(args.capture_dir), out_dir, pdf=not args.no_pdf,
           use_case=args.use_case)
    print(f"re-rendered {out_dir / 'inventory.html'}")
    return 0


def cmd_review(args) -> int:
    """Serve the local review app (Level 2); --share adds the tenant link
    (Level 3). See docs/05-review-experience.md."""
    from .review import serve

    try:
        httpd = serve(Path(args.capture_dir), Path(args.out), port=args.port,
                      share=args.share, backend=args.backend, model=args.model,
                      base_url=args.base_url, open_browser=not args.no_open,
                      no_detect=args.no_detect, use_case=args.use_case)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: could not bind port {args.port}: {e}", file=sys.stderr)
        return 2
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped — edits are already saved in inventory.json")
    finally:
        httpd.server_close()
    return 0


def cmd_check(args) -> int:
    """Detector-only capture coverage check — flags per-room gaps before the
    (paid) describe step. Cannot hallucinate items; only prompts a second look."""
    from .coverage import check_capture
    from .ingest import ingest

    capture_dir = Path(args.capture_dir)
    if not capture_dir.is_dir():
        print(f"error: capture dir not found: {capture_dir}", file=sys.stderr)
        return 2
    work_dir = Path(args.out) / "work" if args.out else capture_dir / ".check-work"
    rooms = ingest(capture_dir, work_dir)
    if not rooms:
        print("error: no photos or videos found (see `homeinventory guide`)",
              file=sys.stderr)
        return 2
    if args.room:
        only = {r.strip().lower() for r in args.room.split(",")}
        rooms = {k: v for k, v in rooms.items() if k.lower() in only}
        if not rooms:
            print("error: --room matched nothing", file=sys.stderr)
            return 2

    report = check_capture(capture_dir, rooms, conf=args.det_conf,
                           device=getattr(args, "device", None))
    if report is None:
        print("error: detector unavailable — install the detect extra:\n"
              "  pip install homeinventory[detect]", file=sys.stderr)
        return 2
    gaps_total = 0
    for room, gaps in report.items():
        if gaps:
            gaps_total += len(gaps)
            for g in gaps:
                print(f"  GAP  {room}: no {g} seen — photograph it or mark N/A")
        else:
            print(f"  ok   {room}: expected items all covered")
    if gaps_total:
        print(f"\n{gaps_total} coverage gap(s). The detector only checks "
              "presence — it cannot judge photo quality.")
        return 1
    print("\nNo coverage gaps against the per-room checklist.")
    return 0


def _parse_context_kv(pairs: list[str]) -> dict:
    out: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"context entry must be KEY=VALUE, got {pair!r}")
        key, val = pair.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def cmd_compare(args) -> int:
    """Baseline vs follow-up comparison: lexical alignment (no API calls),
    use-case rubric for gated changes, paired-photo delta report.
    See docs/08-compare.md."""
    from .compare import (compare_inventories, get_rubric_backend, _item_ages,
                          load_inventory_arg, render_comparison)
    from .describe import FatalBackendError
    from .usecases import get_use_case, use_case_for

    try:
        checkin, checkin_dir, checkin_raw = load_inventory_arg(Path(args.checkin))
        checkout, checkout_dir, _ = load_inventory_arg(Path(args.checkout))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.use_case:
        uc = get_use_case(args.use_case)
    else:
        ci_uc, co_uc = use_case_for(checkin), use_case_for(checkout)
        if ci_uc.key != co_uc.key:
            print(f"error: use_case mismatch — check-in has {ci_uc.key!r}, "
                  f"check-out has {co_uc.key!r}; pass --use-case explicitly.",
                  file=sys.stderr)
            return 2
        uc = ci_uc
    spec = uc.comparison
    if spec is None:
        print(f"error: use case {uc.key!r} has no comparison profile",
              file=sys.stderr)
        return 2

    try:
        context = _parse_context_kv(args.context)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.tenancy_months is not None:
        context.setdefault("tenancy_months", args.tenancy_months)
    if args.occupancy:
        context.setdefault("occupancy", args.occupancy)

    try:
        rubric = get_rubric_backend(args.backend, spec, model=args.model,
                                    base_url=args.base_url)
    except FatalBackendError as e:
        print(f"error: {e}\nhint: --backend offline compares without "
              "classification (changes stay 'unclassified').", file=sys.stderr)
        return 2

    try:
        result = compare_inventories(
            checkin, checkout, rubric=rubric, use_case=uc, context=context,
            item_ages=_item_ages(checkin_raw))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    outputs = render_comparison(result, checkin, checkout, checkin_dir,
                                checkout_dir, Path(args.out),
                                pdf=not args.no_pdf)
    labels = result["labels"]
    t = result["totals"]
    print(f"\n{t['matched']} items matched ({t['changed']} changed, "
          f"{t['unchanged']} unchanged), {t['removed']} not located at "
          f"{labels['followup'].lower()}, {t['added']} new at "
          f"{labels['followup'].lower()}.")
    if result["usage"].get("prompt_tokens"):
        u = result["usage"]
        print(f"classification tokens: {u['prompt_tokens']} in / "
              f"{u['completion_tokens']} out ({result['params']['model']})")
    for kind, path in outputs.items():
        print(f"  {kind:5} {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from .usecases import REGISTRY
    use_cases = sorted(REGISTRY)

    parser = argparse.ArgumentParser(prog="homeinventory",
                                     description="AI property inventory reports")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("guide", help="print the photo capture checklist")
    g.add_argument("--use-case", choices=use_cases, default=None,
                   help="use-case profile (default: tenancy)")
    g.set_defaults(func=cmd_guide)

    b = sub.add_parser("build", help="build a report from a capture folder")
    b.add_argument("capture_dir")
    b.add_argument("-o", "--out", default="report")
    b.add_argument("--backend", choices=["claude", "openai", "local", "offline"],
                   default="openai")
    b.add_argument("--model", default=None,
                   help="model id for the backend: openai default "
                        "gemini-3.5-flash (via Google compat endpoint); "
                        "claude default claude-opus-4-8 (expensive backup for "
                        "hard items); local default qwen3.5:9b (any Ollama "
                        "vision model)")
    b.add_argument("--base-url", default=None,
                   help="override the API base URL for --backend openai "
                        "(any OpenAI-compatible server)")
    b.add_argument("--address", help="property address for the cover page")
    b.add_argument("--inspector", help="name of the person attesting the report")
    b.add_argument("--agent-name", help="clerk / letting agent company name for the cover")
    b.add_argument("--agent-phone", help="agent contact phone for the PDF footer")
    b.add_argument("--property-type",
                   help="e.g. '1 Bedroom furnished apartment' for Schedule of Condition")
    b.add_argument("--tenant", help="tenant name(s) for the cover page")
    b.add_argument("--landlord", help="landlord or agent name for the cover page")
    b.add_argument("--report-ref", help="report reference number")
    b.add_argument("--use-case", choices=use_cases, default=None,
                   help="use-case profile (default: prior inventory's use_case "
                        "when rebuilding, else tenancy)")
    b.add_argument("--party", action="append", default=[], metavar="KEY=NAME",
                   help="party name for cover/signing (repeatable; e.g. "
                        "customer_name=Jane Doe)")
    b.add_argument("--notes", help="general notes for the report front matter")
    b.add_argument("--room", help="only (re)build these rooms, comma-separated; "
                                  "other rooms are kept from the existing inventory.json")
    b.add_argument("--from-json", nargs="?", const="", metavar="PATH",
                   help="preserve hand-edits from inventory.json when rebuilding "
                        "(default: OUT_DIR/inventory.json when the flag is given alone)")
    b.add_argument("--resume", action="store_true",
                   help="reuse per-room checkpoints from a previous run "
                        "(retries only rooms that failed or were not described)")
    b.add_argument("--trim-lead", type=float, default=0.0, metavar="SECONDS",
                   help="skip the first SECONDS of each room video — use ~2.0 "
                        "when room segments were cut from one continuous "
                        "walkthrough, so the previous room's tail frames don't "
                        "bleed into this room's schedule")
    b.add_argument("--no-segment", action="store_true",
                   help="skip VLM room segmentation for root walkthrough videos "
                        "(treat as one General room)")
    b.add_argument("--segment-model", default="gemini-3.5-flash",
                   help="VLM for walkthrough segmentation (default: "
                        "gemini-3.5-flash)")
    b.add_argument("--segment-every", type=float, default=5.0,
                   help="thumbnail strip interval in seconds for segmentation")
    b.add_argument("--segments-json", default=None,
                   help="reuse a pre-computed segments.json (skips the VLM "
                        "segmentation call)")
    b.add_argument("--progress-file", default=None,
                   help="write staged build progress JSON for the web UI")
    b.add_argument("--no-detect", action="store_true",
                   help="skip YOLOE detection (no crops / hints)")
    _add_detect_args(b)
    b.add_argument("--det-conf", type=float, default=0.25)
    b.add_argument("--no-pdf", action="store_true")
    b.set_defaults(func=cmd_build)

    co = sub.add_parser("curate-only",
                        help="re-run hero curation on an existing build "
                             "(no describe/detect API cost)")
    co.add_argument("capture_dir")
    co.add_argument("-o", "--out", default="report")
    co.add_argument("--use-case", choices=use_cases, default=None,
                    help="override use-case profile when rendering")
    co.add_argument("--no-pdf", action="store_true")
    co.set_defaults(func=cmd_curate_only)

    r = sub.add_parser("render", help="re-render report from edited inventory.json")
    r.add_argument("capture_dir")
    r.add_argument("-o", "--out", default="report")
    r.add_argument("--use-case", choices=use_cases, default=None,
                   help="override use-case profile when rendering")
    r.add_argument("--no-pdf", action="store_true")
    r.set_defaults(func=cmd_render)

    rv = sub.add_parser("review",
                        help="serve the local review web app (edit, annotate, "
                             "sign; --share adds a tenant link)")
    rv.add_argument("capture_dir")
    rv.add_argument("-o", "--out", default="report")
    rv.add_argument("--port", type=int, default=8484)
    rv.add_argument("--share", action="store_true",
                    help="also serve a token-protected tenant link on the LAN "
                         "(comments + countersignature)")
    rv.add_argument("--backend", choices=["claude", "openai", "local", "offline"],
                    default="openai", help="backend used by 'Re-describe room'")
    rv.add_argument("--model", default=None)
    rv.add_argument("--base-url", default=None)
    rv.add_argument("--no-open", action="store_true",
                    help="don't open the browser automatically")
    rv.add_argument("--no-detect", action="store_true",
                    help="server-spawned builds (start-page build, "
                         "re-describe) skip YOLOE detection")
    rv.add_argument("--use-case", choices=use_cases, default=None,
                   help="use-case profile when no inventory.json yet (default: "
                        "tenancy; overridden by inventory.json or project.json)")
    rv.set_defaults(func=cmd_review)

    ck = sub.add_parser("check",
                        help="detector-only coverage check of a capture folder")
    ck.add_argument("capture_dir")
    ck.add_argument("-o", "--out", default=None,
                    help="reuse a report dir's work folder for video keyframes")
    ck.add_argument("--room", help="only check these rooms, comma-separated")
    _add_detect_args(ck)
    ck.add_argument("--det-conf", type=float, default=0.25)
    ck.set_defaults(func=cmd_check)

    c = sub.add_parser("compare",
                       help="baseline vs follow-up comparison: aligned item "
                            "deltas, use-case classification, paired photo "
                            "evidence")
    c.add_argument("checkin", metavar="BASELINE",
                   help="baseline report dir (or inventory.json path)")
    c.add_argument("checkout", metavar="FOLLOWUP",
                   help="follow-up report dir (or inventory.json path)")
    c.add_argument("-o", "--out", default="compare",
                   help="output dir for compare.json/.html/.pdf")
    c.add_argument("--use-case", choices=use_cases, default=None,
                   help="use-case profile (default: derived from inventories; "
                        "error if they disagree)")
    c.add_argument("--context", action="append", default=[], metavar="KEY=VALUE",
                   help="comparison context for the rubric (repeatable; e.g. "
                        "tenancy_months=12, scope='full deep clean')")
    c.add_argument("--backend", choices=["openai", "offline"], default="openai",
                   help="classification rubric backend; offline skips "
                        "classification (everything 'unclassified')")
    c.add_argument("--model", default=None,
                   help="rubric model for --backend openai "
                        "(default gpt-5.4-mini, the model the rubric's IMS "
                        "agreement was measured on — docs/08-compare.md)")
    c.add_argument("--base-url", default=None,
                   help="override the API base URL for --backend openai")
    c.add_argument("--tenancy-months", type=int, default=None,
                   help="tenancy length in months (tenancy use-case; folded "
                        "into --context; omitted = 'not provided')")
    c.add_argument("--occupancy", default=None,
                   help="occupancy description (tenancy use-case; folded into "
                        "--context; omitted = 'not provided')")
    c.add_argument("--no-pdf", action="store_true")
    c.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    from .dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
