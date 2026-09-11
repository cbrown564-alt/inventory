"""Export recovered geometry and undistorted camera references for Blender."""
import argparse
import json
from pathlib import Path
import numpy as np
import pycolmap as pc

p=argparse.ArgumentParser();p.add_argument('capture',type=Path);args=p.parse_args();root=args.capture
result=json.loads((root/'result.json').read_text());components=[]
times={Path(x['file']).name:x['timestamp_s'] for x in json.loads((root/'manifest.json').read_text())['frames']}
for metric in result['components']:
    k=metric['component'];out=root/'undistorted'/str(k);out.mkdir(parents=True,exist_ok=True)
    pc.undistort_images(out,root/'sparse'/str(k),root/'frames',num_threads=3)
    r=pc.Reconstruction(out/'sparse')
    points=[dict(xyz=v.xyz.tolist(),rgb=v.color.tolist(),error=float(v.error),id=int(key)) for key,v in r.points3D.items()]
    cams=[]
    for im in r.images.values():
        c=r.cameras[im.camera_id]
        cams.append(dict(name=im.name,seconds=times[im.name],matrix=im.cam_from_world().inverse().matrix().tolist(),K=c.calibration_matrix().tolist(),width=c.width,height=c.height,image=str((out/'images'/im.name).resolve())))
    components.append(dict(id=k,metrics=metric,points=points,cameras=cams))
(root/'blender_evidence.json').write_text(json.dumps(components))
allnames=set(x['name'] for c in components for x in c['cameras'])
summary=dict(unique_registered_frames=len(allnames),selected=result['selected_frames'],components=len(components),global_alignment='not established',metric_scale='not established',architecture_alignment='not established; independent scenes',distortion='camera backgrounds undistorted by COLMAP; encoded roll retained')
(root/'evidence_summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
