"""Render the saved 12 fps animation at 6 fps using EEVEE for a bounded preview."""
import argparse
import json
from pathlib import Path
import sys
import bpy
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.output.resolve();(out/'frames').mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;s.render.engine='BLENDER_EEVEE';s.eevee.taa_render_samples=32;s.frame_step=2;s.render.filepath=str(out/'frames'/'frame_')
(out/'preview.json').write_text(json.dumps(dict(engine='EEVEE',samples=32,source_fps=12,frame_step=2,encoded_fps=6,expected_frames=132,duration_s=22,status='Animated room views with cuts, approximate geometry'),indent=2))
bpy.ops.render.render(animation=True)
