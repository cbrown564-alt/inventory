"""Extract timestamped, SDR reconstruction frames without changing the MOV.

Run with the isolated reconstruction Python. Frames keep encoded orientation:
rotating some images upright would silently change the shared camera intrinsics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np


def hlg_to_sdr(bgr16):
    """BT.2100 inverse HLG OETF, 2020→709 primaries, Reinhard, sRGB OETF.

    A viewing transform, not a colorimetric material measurement. Decode at
    16-bit precision before applying it; never infer defect colors from this.
    """
    e = bgr16[..., ::-1].astype(np.float32) / 65535
    a, b, c = .17883277, .28466892, .55991073
    linear = np.where(e <= .5, e * e / 3, (np.exp((e-c)/a)+b)/12)
    linear = linear @ np.array([[1.6605,-.5876,-.0728],[-.1246,1.1329,-.0083],[-.0182,-.1006,1.1187]], np.float32).T
    linear = np.maximum(linear, 0) * 4
    linear = linear / (1 + linear)
    srgb = np.where(linear <= .0031308, 12.92*linear, 1.055*linear**(1/2.4)-.055)
    return (np.clip(srgb[..., ::-1], 0, 1)*255).astype(np.uint8)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('video', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--start', type=float, default=30)
    p.add_argument('--end', type=float, default=155)
    p.add_argument('--fps', type=float, default=1)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.output / 'frames'
    raw.mkdir(exist_ok=True)
    if list(raw.glob('*.jpg')):
        raise SystemExit('Use a new output directory; existing evidence is never overwritten.')
    meta = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(args.video)
    ]))
    vs = next(s for s in meta['streams'] if s['codec_type'] == 'video')
    hdr = vs.get('color_transfer') in ('arib-std-b67', 'smpte2084')
    filters = [f'fps={args.fps}']
    filters += ['scale=1280:-2:in_color_matrix=bt2020' if hdr else 'scale=1280:-2',
                'format=rgb48be' if hdr else 'format=rgb24', 'showinfo']
    command = ['ffmpeg', '-v', 'info', '-ss', str(args.start), '-noautorotate',
               '-i', str(args.video), '-t', str(args.end - args.start), '-vf', ','.join(filters),
               '-start_number', '0', str(raw / 'f%05d.png')]
    with (args.output / 'extraction.log').open('w') as log:
        subprocess.run(command, check=True, stdout=log, stderr=log)
    records = []
    for i, source in enumerate(sorted(raw.glob('*.png'))):
        decoded = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
        im = hlg_to_sdr(decoded) if hdr else decoded
        path = source.with_suffix('.jpg')
        cv2.imwrite(str(path), im, [cv2.IMWRITE_JPEG_QUALITY, 94])
        source.unlink()
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        records.append(dict(file=str(path.relative_to(args.output)),
                            timestamp_s=round(args.start + i / args.fps, 4),
                            timestamp_basis='nominal fps sampling time after input seek; extraction.log retains filter PTS',
                            sha256=sha256(path), sharpness=round(score, 3),
                            role='held_out' if i % 9 == 4 else 'reconstruction'))
    result = dict(source=str(args.video.resolve()), source_sha256=sha256(args.video),
                  metadata=meta, command=command, hdr_to_sdr=hdr,
                  viewing_transform='inverse HLG, BT2020→709, exposure 4, Reinhard, sRGB' if hdr else 'SDR',
                  orientation='encoded, without autorotation', frames=records)
    (args.output / 'manifest.json').write_text(json.dumps(result, indent=2))
    print(f'Extracted {len(records)} frames to {args.output}')


if __name__ == '__main__':
    main()
