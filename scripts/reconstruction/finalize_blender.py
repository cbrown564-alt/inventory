"""Package the model, source-reference boards, sparse evidence scenes and GLB.

Blender 5.2: --background model.blend --python finalize_blender.py -- --root ...
This writes a NEW file, never over the model it opens.
"""
import argparse
import json
from pathlib import Path
import sys
import bpy
from mathutils import Matrix,Vector

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);root=args.root.resolve()
final=root/'deliverables';final.mkdir(exist_ok=True);target=final/'IMG_5677_property.blend'
if target.exists():raise RuntimeError('Refusing to replace an existing final working file.')
scene=bpy.context.scene;scene.name='01 • Editable property • approximate'
# A separately fitted view provides an inspectable photo/model comparison.
fit=json.loads((root/'camera_fit.json').read_text())
data=bpy.data.cameras.new('Fit / kitchen 03:05');cam=bpy.data.objects.new(data.name,data);scene.collection.objects.link(cam)
cam.matrix_world=Matrix(fit['cam_from_world']).inverted() @ Matrix.Diagonal((1,-1,-1,1));data.sensor_fit='HORIZONTAL';data.sensor_width=36;data.lens=36*fit['K'][0][0]/fit['width']
cam['camera_status']=fit['status'];cam['fitting_rms_px']=fit['rms_px'];cam['source_seconds']=185
im=bpy.data.images.load(str(root/fit['source']),check_existing=True);im.pack();bg=data.background_images.new();bg.image=im;bg.alpha=.5;data.show_background_images=True
# Hide ceilings on opening so that the entire property can be inspected.
ceil=bpy.data.collections.get('CEILINGS • toggle for cutaway');ceil.hide_viewport=True
for scr in bpy.data.screens:
    for area in scr.areas:
        if area.type=='VIEW_3D':
            sp=area.spaces.active;sp.shading.type='SOLID';sp.shading.light='STUDIO';sp.shading.color_type='MATERIAL';sp.shading.show_shadows=True;sp.shading.show_cavity=True
            sp.region_3d.view_distance=22;sp.region_3d.view_location=(1.5,5.4,1.5)
            sp.region_3d.view_rotation=scene.objects['Overview • layout hypothesis'].rotation_euler.to_quaternion()
# Source boards in a separate scene: useful images rather than hidden machine paths.
reference=bpy.data.scenes.new('02 • Video reference boards')
refs=bpy.data.collections.new('Timestamped source images');reference.collection.children.link(refs)
paths=sorted((root/'reference').glob('view_*.jpg'))
for i,path in enumerate(paths):
    im=bpy.data.images.load(str(path),check_existing=True);im.pack()
    obj=bpy.data.objects.new(f'IMG_5677 • {int(path.stem[5:])//60:02d}:{int(path.stem[5:])%60:02d}',None);obj.empty_display_type='IMAGE';obj.data=im;obj.empty_display_size=3.0;obj.location=((i%6)*3.5,0,-(i//6)*4.0);obj.rotation_euler=(1.5707963,0,0)
    obj['source_seconds']=int(path.stem[5:]);obj['viewing_transform']='ffmpeg auto-rotation, downscale; some views additionally rolled upright; original MOV unchanged';refs.objects.link(obj)
# Recovered fragments remain in independent coordinate systems and are never
# silently merged with the architectural model.
evidence=json.loads((root/'pilot'/'blender_evidence.json').read_text())
for component in evidence:
    k=component['id'];s=bpy.data.scenes.new(f'{k+3:02d} • COLMAP fragment {k} • arbitrary scale');s.unit_settings.system='NONE'
    s['status']='Recovered sparse geometry; not globally aligned or metrically scaled'
    s['metrics']=json.dumps(component['metrics'])
    coll=bpy.data.collections.new(f'Fragment {k} / recovered evidence');s.collection.children.link(coll)
    pts=component['points'];verts=[];faces=[];colors=[]
    import statistics
    xs=[v['xyz'][0] for v in pts];ys=[v['xyz'][1] for v in pts];zs=[v['xyz'][2] for v in pts]
    extent=max(max(xs)-min(xs),max(ys)-min(ys),max(zs)-min(zs));size=extent*.0007
    for pt in pts:
        x,y,z=pt['xyz'];a=len(verts)
        verts += [(x+size,y,z),(x-size,y,z),(x,y+size,z),(x,y-size,z),(x,y,z+size),(x,y,z-size)]
        faces += [tuple(a+j for j in q) for q in [(0,2,4),(2,1,4),(1,3,4),(3,0,4),(2,0,5),(1,2,5),(3,1,5),(0,3,5)]]
        colors += [tuple(c/255 for c in pt['rgb'])+(1,)]*6
    mesh=bpy.data.meshes.new('Recovered colored points');mesh.from_pydata(verts,[],faces);mesh.update();attr=mesh.color_attributes.new(name='EvidenceColor',type='FLOAT_COLOR',domain='POINT')
    for entry,color in zip(attr.data,colors):entry.color=color
    ob=bpy.data.objects.new(f'{len(pts)} reconstructed points',mesh);coll.objects.link(ob)
    material=bpy.data.materials.new(f'Fragment {k} / colors');material.use_nodes=True;nodes=material.node_tree.nodes;nodes.clear();out=nodes.new('ShaderNodeOutputMaterial');em=nodes.new('ShaderNodeEmission');vc=nodes.new('ShaderNodeVertexColor');vc.layer_name='EvidenceColor';material.node_tree.links.new(vc.outputs['Color'],em.inputs['Color']);material.node_tree.links.new(em.outputs[0],out.inputs['Surface']);mesh.materials.append(material)
    for rec in sorted(component['cameras'],key=lambda x:x['seconds']):
        data=bpy.data.cameras.new(f'Solved {rec["seconds"]:07.2f}s');cam=bpy.data.objects.new(data.name,data);coll.objects.link(cam)
        arr=rec['matrix'];matrix=Matrix([arr[0],arr[1],arr[2],[0,0,0,1]]) @ Matrix.Diagonal((1,-1,-1,1));cam.matrix_world=matrix
        data.sensor_fit='HORIZONTAL';data.sensor_width=36;data.lens=36*rec['K'][0][0]/rec['width'];data.shift_x=-(rec['K'][0][2]-rec['width']/2)/rec['width'];data.shift_y=(rec['K'][1][2]-rec['height']/2)/rec['width'];data.clip_start=.001;data.clip_end=10000;data.display_size=extent*.02
        im=bpy.data.images.load(rec['image'],check_existing=True);im.pack();bg=data.background_images.new();bg.image=im;bg.alpha=.65;data.show_background_images=True
        cam['source_seconds']=rec['seconds'];cam['source_frame']=rec['name'];cam['calibration']=json.dumps(rec['K']);cam['recovered']=True
        if s.camera is None:s.camera=cam;s.render.resolution_x=rec['width'];s.render.resolution_y=rec['height']
    s.world=scene.world;s.render.engine='BLENDER_WORKBENCH';s.display.shading.color_type='MATERIAL'
# Export editable mesh interchange from the architectural scene only.
bpy.context.window.scene=scene
ceil.hide_viewport=False
bpy.ops.export_scene.gltf(filepath=str(final/'IMG_5677_property.glb'),export_format='GLB',use_active_scene=True,export_cameras=False,export_lights=False,export_extras=True)
ceil.hide_viewport=True
bpy.ops.wm.save_as_mainfile(filepath=str(target))
print('PACKAGED',target)
