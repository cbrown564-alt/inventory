"""Bounded CPU COLMAP experiment; retains all components and actual metrics."""
import argparse
import json
from pathlib import Path
import time

import pycolmap as pc


def main():
    p = argparse.ArgumentParser()
    p.add_argument('capture', type=Path)
    args = p.parse_args()
    root = args.capture
    manifest = json.loads((root / 'manifest.json').read_text())
    selected = [Path(f['file']).name for f in manifest['frames']
                if f['role'] == 'reconstruction' and f['sharpness'] >= 18]
    db = root / 'colmap.db'
    if db.exists():
        raise SystemExit('Use a fresh capture directory to preserve the previous run.')
    started = time.time()
    pc.extract_features(database_path=db, image_path=root/'frames', image_names=selected,
                        camera_mode=pc.CameraMode.SINGLE,
                        reader_options={'camera_model': 'SIMPLE_RADIAL'},
                        extraction_options={'num_threads': 3, 'max_image_size': 1280,
                                            'sift': {'max_num_features': 4096}},
                        device=pc.Device.cpu)
    pc.match_sequential(db, matching_options={'num_threads': 3},
                        pairing_options={'overlap': 8, 'quadratic_overlap': True,
                                         'loop_detection': False}, device=pc.Device.cpu)
    models = pc.incremental_mapping(db, root/'frames', root/'sparse',
                                   options={'num_threads': 3, 'min_model_size': 8})
    metrics = []
    for key, rec in models.items():
        rec.write_text(root/'sparse'/str(key))
        rec.export_PLY(root/f'component_{key}.ply')
        cameras = []
        for im in rec.images.values():
            if not im.has_pose:
                continue
            pose = im.cam_from_world()
            cameras.append(dict(name=im.name, image_id=im.image_id,
                                camera_id=im.camera_id,
                                cam_from_world=pose.matrix().tolist(),
                                center=im.projection_center().tolist()))
        (root/f'cameras_{key}.json').write_text(json.dumps(cameras, indent=2))
        metrics.append(dict(component=key, registered=rec.num_reg_images(),
                            points=rec.num_points3D(), reprojection_error_px=rec.compute_mean_reprojection_error(),
                            track_length=rec.compute_mean_track_length(),
                            cameras=[dict(id=c.camera_id, model=c.model_name, width=c.width,
                                          height=c.height, params=c.params.tolist()) for c in rec.cameras.values()]))
    result = dict(pycolmap=pc.__version__, device='CPU', selected_frames=len(selected),
                  held_out=sum(f['role']=='held_out' for f in manifest['frames']),
                  elapsed_s=round(time.time()-started, 2), components=metrics,
                  scale='arbitrary; no metric reference supplied')
    (root/'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
