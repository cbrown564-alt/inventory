"""Render an actual animated-camera room tour, with cuts between rooms."""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector

p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--frames-per-room',type=int,default=24);p.add_argument('--save-only',action='store_true');args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=4;scene.cycles.use_denoising=True
office=scene.objects['View / office'];office.location=(-1.0,4.87,4.45);office.rotation_euler=(Vector((-1.75,.9,3.9))-office.location).to_track_quat('-Z','Y').to_euler()
# CPU Cycles is supported on the M1 without a display; a small preview keeps the
# expensive part bounded. Still renders remain available at higher quality.
scene.render.resolution_x=720;scene.render.resolution_y=520;scene.render.resolution_percentage=100;scene.render.fps=12
scene.render.image_settings.file_format='PNG'
data=bpy.data.cameras.new('Tour camera');cam=bpy.data.objects.new('Tour camera',data);scene.collection.objects.link(cam);scene.camera=cam
order=['hall','living','kitchen','study','bathroom','bedroom','ensuite','stairs','office','loft_bedroom','loft_bathroom']
segments=[]
for i,room in enumerate(order):
    ref=scene.objects['View / '+room];a=i*args.frames_per_room+1;b=(i+1)*args.frames_per_room
    direction=ref.rotation_euler.to_quaternion()@Vector((0,0,-1));position=ref.location.copy()
    for frame,distance in [(a,0),(b,.12)]:
        cam.location=position+direction*distance;cam.rotation_euler=ref.rotation_euler;cam.keyframe_insert('location',frame=frame);cam.keyframe_insert('rotation_euler',frame=frame)
        data.lens=ref.data.lens;data.keyframe_insert('lens',frame=frame)
    scene.timeline_markers.new(room,frame=a)
    segments.append(dict(room=room,start_frame=a,end_frame=b,start_s=(a-1)/12,end_s=b/12))
scene.frame_start=1;scene.frame_end=len(order)*args.frames_per_room;scene.frame_set(1)
scene['tour_status']='Animated editorial room views; cuts between rooms; approximate dimensions and camera positions'
scene.render.filepath=str(out/'frames'/'frame_');(out/'frames').mkdir(exist_ok=True)
blend=out/'property_animated.blend'
if blend.exists():raise RuntimeError('Choose a new output directory; existing animation is preserved.')
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
(out/'tour.json').write_text(json.dumps(dict(fps=12,width=720,height=520,frames=scene.frame_end,segments=segments,status=scene['tour_status']),indent=2))
if not args.save_only:bpy.ops.render.render(animation=True)
