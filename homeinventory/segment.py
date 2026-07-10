"""Room segmentation of a single walkthrough video — the primary journey.

One continuous phone video in; contiguous, named room segments out. A cheap
VLM pass over a timestamped thumbnail strip places the boundaries and names
the rooms; the segments then feed the existing per-room keyframe pipeline
(ingest), so everything downstream — describe, merge, review, compare — is
unchanged. This replaces the folder-per-room capture convention as the way
rooms come into existence.

Spike CLI (validation artifacts: segments.json + a contact sheet to eyeball):

    python -m homeinventory.segment VIDEO -o OUT_DIR [--every 5] [--model ...]
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Claude accepts up to 100 images per request; stay under it with margin.
_MAX_IMAGES_PER_CALL = 90

DEFAULT_MODEL = "gemini-3.5-flash"

SYSTEM_PROMPT = """\
You segment a continuous walkthrough video of a residential property into
rooms. You are shown a strip of frames sampled at a fixed interval, each
labelled with its timestamp in seconds. Return contiguous, non-overlapping
segments covering the whole strip.

Rules:
- A segment is one continuous stay in one room. If the camera returns to a
  room seen earlier, that is a NEW segment reusing EXACTLY the same room
  name as before.
- Name rooms the way a UK inventory clerk would: Kitchen, Living Room,
  Dining Room, Bathroom, En-suite Shower Room, Bedroom 1, Bedroom 2,
  Hallway, Stairs and Landing, Loft Room, Utility Room, WC, Garden,
  Balcony, Garage. Number repeated room types (Bedroom 1, Bedroom 2) in
  order of first appearance. Distinguish rooms of the same type by an
  honest qualifier when obvious (e.g. "Loft Bedroom", "Loft Shower Room").
- Frames taken while passing through a doorway belong to the room being
  entered.
- Connecting spaces (hallway, stairs, landing) get their own segment only
  when the camera actually documents them for several seconds; a single
  blurred walking-through frame belongs to the destination room.
- The first segment starts at 0. Every segment's start equals the previous
  segment's end. The last segment ends at the strip's final timestamp.
- Judge the room from what the frames show (fittings, furniture, purpose),
  not from an assumed floor plan.
"""

SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "room": {
                        "type": "string",
                        "description": "Clerk-style room name; revisits reuse "
                                       "the earlier name exactly.",
                    },
                    "start_s": {"type": "number"},
                    "end_s": {"type": "number"},
                },
                "required": ["room", "start_s", "end_s"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["segments"],
    "additionalProperties": False,
}


@dataclass
class Segment:
    room: str
    start_s: float
    end_s: float


@dataclass
class SampledFrame:
    t_s: float
    jpeg: bytes


def video_duration_s(video: Path) -> float:
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return n / fps if n else 0.0
    finally:
        cap.release()


def sample_strip(video: Path, every_s: float = 5.0, width: int = 448,
                 quality: int = 72) -> list[SampledFrame]:
    """A timestamped thumbnail every ``every_s`` seconds, small enough that a
    whole property walkthrough costs pennies to look at."""
    import cv2

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    frames: list[SampledFrame] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(round(every_s * fps)))
        for fidx in range(0, n, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, int(h * width / w)))
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok:
                frames.append(SampledFrame(t_s=round(fidx / fps, 2),
                                           jpeg=bytes(buf)))
    finally:
        cap.release()
    return frames


def _chunk_content(chunk: list[SampledFrame], duration_s: float,
                   every_s: float, prior_rooms: list[str],
                   prior_end_room: Optional[str],
                   audio_cues: Optional[dict] = None,
                   provider: str = "anthropic") -> list[dict]:
    import base64
    content: list[dict] = []
    intro = (f"Walkthrough video, total duration {duration_s:.0f}s; frames "
             f"sampled every {every_s:.0f}s. This strip covers "
             f"t={chunk[0].t_s:.0f}s to t={chunk[-1].t_s:.0f}s.")
    if prior_end_room is not None:
        intro += (
            f"\nThis strip CONTINUES an earlier one. Rooms named so far, in "
            f"order of first appearance: {', '.join(prior_rooms)}. The "
            f"previous strip ended inside: {prior_end_room}. The first "
            f"frames here may still be in that room — if so, start the first "
            f"segment with that exact name. Reuse earlier names exactly for "
            f"any room the camera returns to."
        )
    if audio_cues:
        from .audio_cues import segmentation_hint
        intro += segmentation_hint(audio_cues, chunk[0].t_s, chunk[-1].t_s)
    content.append({"type": "text", "text": intro})
    for f in chunk:
        content.append({"type": "text", "text": f"t={f.t_s:.0f}s:"})
        b64 = base64.b64encode(f.jpeg).decode()
        if provider == "anthropic":
            content.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": "image/jpeg",
                                       "data": b64}})
        else:
            content.append({"type": "image_url", "image_url":
                            {"url": f"data:image/jpeg;base64,{b64}"}})
    content.append({"type": "text", "text":
                    "Segment this strip into rooms. Timestamps in seconds."})
    return content


def _normalise(segments: list[Segment], duration_s: float) -> list[Segment]:
    """Force contiguity (model output can drift), then merge same-room
    neighbours. Boundary corrections beat gaps: downstream keyframe
    extraction tolerates a boundary being a second or two off, but a gap
    would silently drop footage from the schedule."""
    duration_s = max(float(duration_s), 0.0)
    segs: list[Segment] = []
    for source in segments:
        if not (math.isfinite(source.start_s) and math.isfinite(source.end_s)):
            continue
        start = min(max(float(source.start_s), 0.0), duration_s)
        end = min(max(float(source.end_s), 0.0), duration_s)
        room = source.room.strip()
        if not room or end <= start:
            continue
        segs.append(Segment(room, start, end))
    segs.sort(key=lambda s: s.start_s)
    if not segs:
        return [Segment("Property", 0.0, duration_s)]

    # Build a monotonic seam sequence from the raw interval pairs. Model
    # chunks can overlap wildly or return boundaries outside the video; using
    # monotonic seams guarantees that repair cannot create a negative span.
    seams = [0.0]
    for prev, cur in zip(segs, segs[1:]):
        seam = prev.end_s if abs(cur.start_s - prev.end_s) <= 0.01 \
            else round((prev.end_s + cur.start_s) / 2, 2)
        seams.append(min(max(seam, seams[-1]), duration_s))
    seams.append(duration_s)

    repaired = [Segment(seg.room, seams[i], seams[i + 1])
                for i, seg in enumerate(segs)
                if seams[i + 1] > seams[i]]
    if not repaired:
        return [Segment("Property", 0.0, duration_s)]
    merged: list[Segment] = []
    for s in repaired:
        if merged and merged[-1].room.strip().lower() == s.room.strip().lower():
            merged[-1].end_s = s.end_s
        else:
            merged.append(s)
    return merged


def _call_anthropic(client, model: str, content: list[dict],
                    usage: dict) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema",
                                  "schema": SEGMENT_SCHEMA}},
    )
    u = getattr(response, "usage", None)
    if u is not None:
        usage["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
        usage["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
    texts = [b.text for b in response.content if b.type == "text"]
    if not texts:
        raise RuntimeError(
            f"no text in response (stop_reason={response.stop_reason!r}, "
            f"blocks={[b.type for b in response.content]!r})")
    return texts[-1]


def _call_openai(backend, content: list[dict], usage: dict) -> str:
    """One chat-completions call via the shared OpenAI-compat plumbing
    (gemini-* models are routed to Google's endpoint automatically)."""
    resp = backend._post({
        "model": backend.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "video_segments", "strict": True,
            "schema": SEGMENT_SCHEMA}},
    })
    u = resp.get("usage") or {}
    usage["input_tokens"] += int(u.get("prompt_tokens") or 0)
    usage["output_tokens"] += int(u.get("completion_tokens") or 0)
    choice = resp["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("segmentation output truncated at token limit")
    return choice["message"]["content"]


def segment_frames(frames: list[SampledFrame], duration: float,
                   every_s: float, model: str = DEFAULT_MODEL,
                   width: int = 448,
                   audio_cues: Optional[dict] = None) -> tuple[list[Segment], dict]:
    """Return (segments, meta) for a pre-sampled strip. meta carries
    sampling params and token usage so runs are comparable across models."""
    if not frames:
        raise RuntimeError("no frames sampled from the video")

    provider = "anthropic" if model.startswith("claude") else "openai"
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
    else:
        from .describe import OpenAICompatBackend
        client = OpenAICompatBackend(model=model)
    segments: list[Segment] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    rooms_so_far: list[str] = []
    calls = 0
    for i in range(0, len(frames), _MAX_IMAGES_PER_CALL):
        chunk = frames[i:i + _MAX_IMAGES_PER_CALL]
        prior_end_room = segments[-1].room if segments else None
        content = _chunk_content(chunk, duration, every_s, rooms_so_far,
                                 prior_end_room, audio_cues,
                                 provider=provider)
        if provider == "anthropic":
            text = _call_anthropic(client, model, content, usage)
        else:
            text = _call_openai(client, content, usage)
        calls += 1
        for seg in json.loads(text)["segments"]:
            segments.append(Segment(room=str(seg["room"]).strip(),
                                    start_s=float(seg["start_s"]),
                                    end_s=float(seg["end_s"])))
            room = segments[-1].room
            if room.lower() not in {r.lower() for r in rooms_so_far}:
                rooms_so_far.append(room)

    segments = _normalise(segments, duration)
    meta = {"duration_s": round(duration, 2),
            "every_s": every_s, "width": width, "model": model,
            "api_calls": calls, "frames": len(frames), "usage": usage}
    if audio_cues:
        meta["audio_cues_sha256"] = audio_cues["sha256"]
    return segments, meta


def segment_video(video: Path, every_s: float = 5.0,
                  model: str = DEFAULT_MODEL,
                  width: int = 448,
                  audio_cues: Optional[dict] = None) -> tuple[list[Segment], dict]:
    duration = video_duration_s(video)
    frames = sample_strip(video, every_s=every_s, width=width)
    log.info("sampled %d frames over %.0fs", len(frames), duration)
    segments, meta = segment_frames(frames, duration, every_s,
                                    model=model, width=width,
                                    audio_cues=audio_cues)
    return segments, {**meta, "video": video.name}


# ---------------------------------------------------------------------------
# Spike validation artifacts


def write_contact_sheet(frames: list[SampledFrame], segments: list[Segment],
                        meta: dict, out_dir: Path) -> Path:
    """One HTML page: the sampled strip grouped by assigned room, boundary
    frames flagged — the eyeball test for whether segmentation can carry
    the primary journey."""
    strip = out_dir / "strip"
    strip.mkdir(parents=True, exist_ok=True)
    names: dict[float, str] = {}
    for f in frames:
        p = strip / f"t{int(round(f.t_s)):05d}.jpg"
        p.write_bytes(f.jpeg)
        names[f.t_s] = f"strip/{p.name}"

    def clock(t: float) -> str:
        return f"{int(t) // 60}:{int(t) % 60:02d}"

    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>Segmentation — {meta['video']}</title>",
        "<style>body{font:14px system-ui;margin:24px;background:#fafafa}"
        "h2{margin:28px 0 8px}.meta{color:#666}"
        ".row{display:flex;flex-wrap:wrap;gap:6px}"
        "figure{margin:0;width:150px}img{width:150px;border-radius:4px;"
        "display:block}figcaption{font-size:11px;color:#555;text-align:center}"
        ".boundary img{outline:3px solid #d33}"
        ".boundary figcaption{color:#d33;font-weight:600}</style>",
        f"<h1>{meta['video']}</h1>",
        f"<p class='meta'>{meta['duration_s']:.0f}s · {meta['frames']} frames "
        f"@ every {meta['every_s']:.0f}s · {meta['model']} · "
        f"{meta['usage']['input_tokens']} in / "
        f"{meta['usage']['output_tokens']} out tokens</p>",
    ]
    for seg in segments:
        seg_frames = [f for f in frames if seg.start_s <= f.t_s < seg.end_s]
        parts.append(f"<h2>{seg.room}</h2><p class='meta'>"
                     f"{clock(seg.start_s)}–{clock(seg.end_s)} "
                     f"({seg.end_s - seg.start_s:.0f}s, "
                     f"{len(seg_frames)} frames)</p><div class='row'>")
        for j, f in enumerate(seg_frames):
            cls = " class='boundary'" if j == 0 else ""
            parts.append(f"<figure{cls}><img src='{names[f.t_s]}' "
                         f"loading='lazy'><figcaption>{clock(f.t_s)}"
                         f"</figcaption></figure>")
        parts.append("</div>")
    out = out_dir / "contact_sheet.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Spike: segment a walkthrough video into rooms")
    parser.add_argument("video")
    parser.add_argument("-o", "--out", default="segment-spike")
    parser.add_argument("--every", type=float, default=5.0)
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="model id, or a comma-separated list to compare "
                             "(sampling runs once; one output dir per model)")
    parser.add_argument("--width", type=int, default=448)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from .dotenv import load_dotenv
    load_dotenv()

    video, out_base = Path(args.video), Path(args.out)
    models = [m.strip() for m in args.model.split(",") if m.strip()]
    duration = video_duration_s(video)
    frames = sample_strip(video, every_s=args.every, width=args.width)
    log.info("sampled %d frames over %.0fs", len(frames), duration)

    def clock(t: float) -> str:
        return f"{int(t) // 60}:{int(t) % 60:02d}"

    failures = 0
    for model in models:
        out_dir = out_base if len(models) == 1 else \
            out_base / model.replace(":", "_").replace("/", "_")
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            segments, meta = segment_frames(frames, duration, args.every,
                                            model=model, width=args.width)
        except Exception as e:
            failures += 1
            print(f"\n== {model}: FAILED — {e}")
            continue
        meta["video"] = video.name
        (out_dir / "segments.json").write_text(json.dumps(
            {**meta, "segments": [asdict(s) for s in segments]},
            indent=2, ensure_ascii=False), encoding="utf-8")
        sheet = write_contact_sheet(frames, segments, meta, out_dir)
        print(f"\n== {model}: {len(segments)} segments "
              f"({meta['usage']['input_tokens']} in / "
              f"{meta['usage']['output_tokens']} out tokens, "
              f"{meta['api_calls']} calls)")
        for s in segments:
            print(f"  {clock(s.start_s):>6}–{clock(s.end_s):<6} {s.room}")
        print(f"  json  {out_dir / 'segments.json'}\n  sheet {sheet}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
