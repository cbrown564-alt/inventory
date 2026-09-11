"""Meaningful artifact checks, run after reopening the packaged .blend."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
import bmesh
from mathutils import Vector

p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
scene=next(s for s in bpy.data.scenes if s.name.startswith('01'))
issues=[];checked=0;cube_count=0
for ob in scene.objects:
    if ob.type!='MESH':continue
    checked+=1
    if not all(math.isfinite(c) for v in ob.data.vertices for c in v.co):issues.append(ob.name+': nonfinite geometry')
    if not ob.get('source_video') or not ob.get('evidence_seconds'):issues.append(ob.name+': missing source references')
    if len(ob.data.vertices)==8 and len(ob.data.polygons)==6:
        bm=bmesh.new();bm.from_mesh(ob.data);volume=bm.calc_volume(signed=True);bm.free();cube_count+=1
        if volume<=0:issues.append(ob.name+': nonpositive signed volume')
for cam in [o for o in scene.objects if o.type=='CAMERA' and o.name.startswith('View /')]:
    for ob in [o for o in scene.objects if o.type=='MESH' and len(o.data.vertices)==8 and len(o.data.polygons)==6]:
        # Convex box half-space test catches viewpoints inside furniture or walls.
        local=ob.matrix_world.inverted()@cam.matrix_world.translation
        if all((local-face.center).dot(face.normal)<-.005 for face in ob.data.polygons):
            issues.append(cam.name+' is inside '+ob.name)
packed=sum(bool(i.packed_file) for i in bpy.data.images if i.source=='FILE')
missing=[i.name for i in bpy.data.images if i.source=='FILE' and not i.packed_file and not Path(bpy.path.abspath(i.filepath)).exists()]
if missing:issues.append('Missing image files: '+str(missing))
result=dict(status='passed' if not issues else 'failed',issues=issues,mesh_objects_checked=checked,solid_boxes_checked=cube_count,packed_images=packed,scenes=len(bpy.data.scenes),source_references='present on every architectural mesh',metric_accuracy='not established; no measurements',visual_acceptance='separate rendered review')
args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if issues:raise RuntimeError('Artifact verification failed')
