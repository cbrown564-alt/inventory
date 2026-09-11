"""Render the fitted reference view and the corrected office view from the final file."""
import argparse
from pathlib import Path
import sys
import bpy
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;ceil=bpy.data.collections['CEILINGS • toggle for cutaway'];ceil.hide_viewport=False
s.render.engine='CYCLES';s.cycles.samples=16;s.cycles.use_denoising=True;s.render.resolution_percentage=100
for name,w,h,filename in [('View / office',1100,800,'office.png'),('Fit / kitchen 03:05',720,1280,'kitchen_matched_0305.png')]:
 s.camera=s.objects[name];s.render.resolution_x=w;s.render.resolution_y=h;s.render.filepath=str(a.output/filename);bpy.ops.render.render(write_still=True)
