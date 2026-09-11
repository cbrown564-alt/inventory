"""Build editable, provenance-tagged rooms; run with Blender 5.2's Python.

Writes a new revision only. Manual edits belong in a saved copy or the reserved
USER_EDITS collection; a regeneration never loads or deletes that working file.
"""
import argparse
import json
import math
from pathlib import Path
import random
import sys

import bpy
from mathutils import Vector

random.seed(5677)
M = {}
ROOT = None
ROOM = None
COL = None
CEILINGS = None


def mat(name, rgb, rough=.65, metal=0, texture=False):
    m=bpy.data.materials.new(name);m.diffuse_color=(*rgb,1);m.use_nodes=True
    n=m.node_tree.nodes;bs=n.get('Principled BSDF')
    bs.inputs['Base Color'].default_value=(*rgb,1)
    bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal
    if texture:
        noise=n.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=65
        bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.025
        m.node_tree.links.new(noise.outputs['Fac'],bump.inputs['Height'])
        m.node_tree.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
    M[name]=m
    return m


def tag(obj):
    obj['source_video']='IMG_5677.MOV'
    obj['evidence_seconds']=json.dumps(ROOM.get('refs',[]) if ROOM else [])
    obj['geometry_status']='estimated from video; no measured scale'
    if ROOM: obj['room_id']=ROOM['id']
    return obj


def put(obj, material, collection=None):
    for c in list(obj.users_collection):c.objects.unlink(obj)
    (collection or COL).objects.link(obj)
    if material:obj.data.materials.append(M[material])
    if ROOT:obj.parent=ROOT
    tag(obj)
    return obj


def box(name, loc, size, material='white', bevel=0, collection=None):
    # Data API avoids context/selection dependence for the repeated operation.
    x,y,z=[v/2 for v in size]
    verts=[(-x,-y,-z),(-x,-y,z),(-x,y,-z),(-x,y,z),(x,-y,-z),(x,-y,z),(x,y,-z),(x,y,z)]
    faces=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
    me=bpy.data.meshes.new(name);me.from_pydata(verts,[],[tuple(reversed(f)) for f in faces]);me.update()
    obj=bpy.data.objects.new(name,me);obj.location=loc;put(obj,material,collection)
    if bevel:
        mod=obj.modifiers.new('Soft edges','BEVEL');mod.width=bevel;mod.segments=3
        obj.modifiers.new('Corner normals','WEIGHTED_NORMAL')
    return obj


def cylinder(name,loc,radius,depth,material='chrome',vertices=24,rotation=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices,radius=radius,depth=depth,location=(0,0,0))
    obj=bpy.context.object;obj.name=name;put(obj,material);obj.location=loc
    if rotation:obj.rotation_euler=rotation
    for p in obj.data.polygons:p.use_smooth=True
    mod=obj.modifiers.new('Rim','BEVEL');mod.width=.008;mod.segments=2
    return obj


def ball(name,loc,size,material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12)
    obj=bpy.context.object;obj.name=name;put(obj,material);obj.location=loc;obj.scale=size
    for p in obj.data.polygons:p.use_smooth=True
    return obj


def line(name,a,b,r=.012,material='chrome'):
    a,b=Vector(a),Vector(b);v=b-a
    ob=cylinder(name,(a+b)/2,r,v.length,material)
    ob.rotation_euler=v.to_track_quat('Z','Y').to_euler();return ob


def wall_piece(side,start,end,z0,z1,w,d,material,collection=None):
    if end-start<.005 or z1-z0<.005:return
    thick=.12 if z1==.12 else .10
    if side in ('N','S'):
        loc=((start+end)/2,d-thick/2 if side=='N' else thick/2,(z0+z1)/2)
        size=(end-start,thick,z1-z0)
    else:
        loc=(w-thick/2 if side=='E' else thick/2,(start+end)/2,(z0+z1)/2)
        size=(thick,end-start,z1-z0)
    box(f'{ROOM["id"]} / {side} wall',loc,size,material,collection=collection)


def wall_rect(side,u,z,width,height,w,d,material,depth=.05):
    if side in ('N','S'):
        return box('Frame', (u,d-.09 if side=='N' else .09,z), (width,depth,height),material,.008)
    return box('Frame',(w-.09 if side=='E' else .09,u,z),(depth,width,height),material,.008)


def shell(room):
    w,d,h=room['size'];floor=room['floor']
    box('Floor',(w/2,d/2,-.08),(w,d,.16),floor)
    if floor=='oak':
        for ix in range(int(w/.20)):
            x=.1+ix*.2
            for iy in range(int(d/1.1)+1):
                y=.55+iy*1.1+(ix%2)*.55
                a=max(.01,y-.545);b=min(d-.01,y+.545)
                if b>a:box('Oak plank',(x,(a+b)/2,.007),(.196,b-a,.012),'oak_light' if random.random()>.5 else 'oak')
    for side,length in [('N',w),('S',w),('E',d),('W',d)]:
        if side in room.get('open_walls',[]):continue
        holes=[]
        for s,u,ww in room.get('doors',[]):
            if s==side:holes.append((u-ww/2,u+ww/2,0,2.08,'door'))
        for s,u,ww,base in room.get('upper_doors',[]):
            if s==side:holes.append((u-ww/2,u+ww/2,base,base+2.08,'door'))
        for s,u,ww,z0,z1 in room.get('windows',[]):
            if s==side:holes.append((u-ww/2,u+ww/2,z0,z1,'window'))
        us=sorted(set([0,length]+[max(0,min(length,v)) for q in holes for v in q[:2]]))
        zs=sorted(set([0,h]+[v for q in holes for v in q[2:4]]))
        material='bluewall' if room.get('accent')==side else 'white'
        if room['id'] in ('bathroom','ensuite'):material='tilewhite'
        if room['id']=='loft_bathroom':material='stone'
        for a,b in zip(us,us[1:]):
            for z0,z1 in zip(zs,zs[1:]):
                if not any(q[0]<(a+b)/2<q[1] and q[2]<(z0+z1)/2<q[3] for q in holes):
                    wall_piece(side,a,b,z0,z1,w,d,material)
        for a,b,z0,z1,kind in holes:
            trim='oak_light' if kind=='window' else 'white'
            for u in (a-.025,b+.025):wall_rect(side,u,(z0+z1)/2,.065,z1-z0+.05,w,d,trim)
            wall_rect(side,(a+b)/2,z1+.025,b-a+.12,.065,w,d,trim)
            if kind=='window':
                wall_rect(side,(a+b)/2,z0,b-a+.15,.075,w,d,trim)
                wall_rect(side,(a+b)/2,(z0+z1)/2,b-a-.03,z1-z0-.04,w,d,'glass',.018)
                wall_rect(side,(a+b)/2,(z0+z1)/2,.045,z1-z0,w,d,trim)
                wall_rect(side,(a+b)/2,z0+(z1-z0)*.45,b-a,.045,w,d,trim)
            elif room['id'] in ('hall','bedroom','landing','loft_bedroom') and z0==0:
                # One owner per shared doorway. Leaves open away from this room.
                global ROOT
                old_root=ROOT;hinge=bpy.data.objects.new('Door hinge',None);COL.objects.link(hinge);hinge.parent=old_root
                if side in ('N','S'):
                    hinge.location=(a,d if side=='N' else 0,0)
                    hinge.rotation_euler.z=math.radians(75 if side=='N' else -75)
                    ROOT=hinge;box('Oak door leaf',((b-a)/2,0,1.01),(b-a-.03,.035,2.02),'oak_light',.008)
                    line('Door lever',(b-a-.19,-.04,1.02),(b-a-.07,-.04,1.02),.014)
                else:
                    hinge.location=(w if side=='E' else 0,a,0)
                    hinge.rotation_euler.z=math.radians(-75 if side=='E' else 75)
                    ROOT=hinge;box('Oak door leaf',(0,(b-a)/2,1.01),(.035,b-a-.03,2.02),'oak_light',.008)
                    line('Door lever',(-.04,b-a-.19,1.02),(-.04,b-a-.07,1.02),.014)
                if room['id']=='hall' and side=='S':hinge.rotation_euler.z=0
                ROOT=old_root
        # Skirting is segmented at doors so the openings remain traversable.
        for a,b in zip(us,us[1:]):
            if not any(q[0]<(a+b)/2<q[1] and q[2]==0 for q in holes):
                wall_piece(side,a,b,.01,.12,w,d,'white')
    if room['id']=='stairs':return
    slope=room.get('slope')
    if not slope:
        box('Ceiling',(w/2,d/2,h+.03),(w,d,.06),'white',collection=CEILINGS)
    else:
        # Continuous roof plane with actual apertures at the listed rooflights.
        def roof_z(x,y):
            distance={'W':x,'E':w-x,'S':y,'N':d-y}[slope]
            return min(h,1.05+distance*.85)
        holes=room.get('skylights',[])
        xx=sorted(set([0,w]+[v for x,y,sx,sy in holes for v in (x-sx/2,x+sx/2)] + ([min(w,(h-1.05)/.85)] if slope=='W' else [max(0,w-(h-1.05)/.85)] if slope=='E' else [])))
        yy=sorted(set([0,d]+[v for x,y,sx,sy in holes for v in (y-sy/2,y+sy/2)] + ([min(d,(h-1.05)/.85)] if slope=='S' else [max(0,d-(h-1.05)/.85)] if slope=='N' else [])))
        for a,b in zip(xx,xx[1:]):
            for c,e in zip(yy,yy[1:]):
                if any(abs((a+b)/2-x)<sx/2 and abs((c+e)/2-y)<sy/2 for x,y,sx,sy in holes):continue
                me=bpy.data.meshes.new('Ceiling panel');me.from_pydata([(a,c,roof_z(a,c)),(b,c,roof_z(b,c)),(b,e,roof_z(b,e)),(a,e,roof_z(a,e))],[],[(3,2,1,0)])
                obj=bpy.data.objects.new('Sloped ceiling',me);put(obj,'white',CEILINGS)
        for x,y,sx,sy in holes:
            points=[(x-sx/2,y-sy/2),(x+sx/2,y-sy/2),(x+sx/2,y+sy/2),(x-sx/2,y+sy/2)]
            verts=[(a,b,roof_z(a,b)+.035) for a,b in points]
            me=bpy.data.meshes.new('Rooflight pane');me.from_pydata(verts,[],[(0,1,2,3)])
            obj=bpy.data.objects.new('Rooflight',me);put(obj,'glass',CEILINGS)
            for i in range(4):
                ob=line('Rooflight frame',verts[i],verts[(i+1)%4],.035,'oak_light')
                for coll in list(ob.users_collection):coll.objects.unlink(ob)
                CEILINGS.objects.link(ob)
    # Ceiling fittings remain optional to make the cutaway legible.
    for x in (w*.3,w*.7):
        ob=cylinder('Recessed light',(x,d*.5,h-.015),.055,.025,'chrome')
        for coll in list(ob.users_collection):coll.objects.unlink(ob)
        CEILINGS.objects.link(ob)


def cabinet(x,y,w=.6,d=.6,h=.88,material='navy',face='S',base=0):
    box('Cabinet carcass',(x,y,base+h/2),(w,d,h),material,.014)
    yy=y-d/2-.012 if face=='S' else y+d/2+.012
    box('Cabinet door',(x,yy,base+h*.52),(w-.045,.025,h-.1),material,.009)
    line('Cabinet handle',(x+w*.28,yy-.025,base+h*.3),(x+w*.28,yy-.025,base+h*.75),.009)
    return box('Worktop',(x,y,base+h+.022),(w+.012,d+.035,.045),'counter',.008)


def radiator(x,y,width=1.0,rot=0):
    # Default lies on the XZ plane.
    ob=box('Radiator',(x,y,.46),(width,.08,.58),'white',.018);ob.rotation_euler.z=rot
    for i in range(int(width/.06)):
        u=-width/2+.04+i*.06
        p=(x+u*math.cos(rot),y+u*math.sin(rot),.46)
        ob=box('Radiator flute',p,(.018,.016,.51),'white',.005);ob.rotation_euler.z=rot


def sofa(x,y,width=2.2,rot=0,material='fabric'):
    # Build in a temporary local furniture root, then rotate as one editable assembly.
    global ROOT
    old=ROOT;root=bpy.data.objects.new('Sofa assembly',None);COL.objects.link(root);root.parent=old;root.location=(x,y,0);root.rotation_euler.z=rot;ROOT=root
    box('Sofa plinth',(0,0,.23),(width,.87,.22),material,.06)
    for i in range(3):
        xx=(i-1)*(width-.3)/3
        box('Seat cushion',(xx,-.05,.45),((width-.3)/3-.025,.74,.18),material,.07)
        ob=box('Back cushion',(xx,.30,.78),((width-.3)/3-.025,.20,.59),material,.07);ob.rotation_euler.x=.1
    for s in (-1,1):
        box('Sofa arm',(s*(width/2-.1),0,.59),(.22,.91,.47),material,.065)
        for yy in (-.32,.31):cylinder('Sofa foot',(s*(width/2-.18),yy,.10),.03,.20,'chrome')
    for xx,col in [(-width*.25,'navy'),(width*.25,'cream')]:
        ob=box('Loose cushion',(xx,.12,.70),(.40,.15,.39),col,.07);ob.rotation_euler.y=.18
    ROOT=old


def bed(x,y,width=1.5,length=2.0,striped=False,rot=0):
    global ROOT
    old=ROOT;root=bpy.data.objects.new('Bed assembly',None);COL.objects.link(root);root.parent=old;root.location=(x,y,0);root.rotation_euler.z=rot;ROOT=root
    box('Bed base',(0,0,.24),(width,length,.30),'fabric',.05)
    box('Mattress',(0,0,.47),(width,length,.23),'cream',.09)
    box('Duvet',(0,-.18,.61),(width+.12,length-.25,.16),'linen',.07)
    box('Upholstered headboard',(0,length/2,.67),(width+.12,.13,1.12),'fabric',.045)
    for s in (-1,1):box('Pillow',(s*width*.25,length*.31,.67),(width*.45,.42,.16),'linen',.07)
    if striped:
        for i in range(10):box('Duvet stripe',(0,-.9+i*.14,.696),(width+.12,.075,.006),'plum' if i%2 else 'taupe',.004)
    ROOT=old


def basin(x,y,vanity=False):
    if vanity:
        cabinet(x,y,.85,.48,.76,'oak_light')
        box('Black vanity top',(x,y,.81),(.88,.52,.04),'black',.015)
    else:box('Basin pedestal',(x,y,.41),(.22,.24,.65),'ceramic',.04)
    box('Basin',(x,y,.89),(.54,.42,.17),'ceramic',.07)
    box('Basin recess',(x,y-.025,.982),(.40,.28,.012),'basin_shadow',.06)
    line('Tap',(x,y+.13,.98),(x,y+.13,1.16),.021)
    line('Spout',(x,y+.13,1.15),(x,y+.01,1.15),.018)
    cylinder('Drain',(x,y,.993),.022,.005,'chrome')


def wc(x,y):
    box('WC cistern',(x,y+.2,.7),(.43,.19,.64),'ceramic',.055)
    ball('WC bowl',(x,y-.08,.39),(.25,.34,.20),'ceramic')
    box('WC pedestal',(x,y,.2),(.28,.36,.4),'ceramic',.07)
    ball('WC seat',(x,y-.08,.56),(.245,.32,.035),'white')
    ball('WC seat inset',(x,y-.10,.584),(.145,.205,.012),'basin_shadow')


def shower(x,y,w=.9,d=.9):
    box('Shower tray',(x,y,.065),(w,d,.13),'ceramic',.035)
    for xx in (x-w/2,x+w/2):line('Shower upright',(xx,y-d/2,.13),(xx,y-d/2,2.08),.022)
    line('Shower top',(x-w/2,y-d/2,2.08),(x+w/2,y-d/2,2.08),.025)
    panel=box('Shower screen',(x,y-d/2,1.1),(w,.014,1.96),'screen')
    panel['simplification']='Planar screen approximates curved enclosure where present'
    line('Shower rail',(x,y+d*.36,1),(x,y+d*.36,2.06),.014)
    cylinder('Shower head',(x,y+d*.2,2.08),.12,.025,'chrome')
    line('Shower mixer',(x-.15,y+d*.34,1.04),(x+.15,y+d*.34,1.04),.024)


def picture(x,y,z,width,height,side='N',material='art'):
    w,d,h=ROOM['size']
    wall_rect(side,x if side in ('N','S') else y,z,width+.05,height+.05,w,d,'black')
    obj=wall_rect(side,x if side in ('N','S') else y,z,width,height,w,d,material,.065)
    obj['appearance_status']='Simplified decorative panel, not copied artwork'


def furnish(room):
    id=room['id'];w,d,h=room['size']
    if id=='living':
        sofa(.63,2.3,2.7,-math.pi/2)
        box('Living rug',(1.63,1.8,.028),(1.55,2.5,.023),'rug')
        # Fireplace on the window end, white surround and black hearth.
        box('Hearth',(.77,.4,.05),(1.45,.67,.1),'black',.015)
        box('Fireplace inset',(.77,.15,.66),(.93,.15,1.12),'black')
        for x in (.17,1.37):box('Fireplace pilaster',(x,.29,.68),(.14,.22,1.24),'white',.02)
        box('Mantel',(.77,.28,1.33),(1.5,.34,.13),'white',.025)
        box('Fire surround brass',(.77,.255,.56),(.75,.025,.68),'brass',.01)
        box('Fire dark centre',(.77,.28,.57),(.66,.025,.58),'black')
        picture(.77,0,1.91,1.12,.76,'S','mirror')
        # TV and dining table are on the blue side wall.
        box('Media console',(w-.33,3.45,.39),(.50,1.50,.66),'taupe',.015)
        box('TV',(w-.13,3.45,1.47),(.055,1.25,.72),'black',.015)
        cylinder('Glass dining table',(3.13,3.8,.77),.72,.035,'screen',48)
        cylinder('Table pedestal',(3.13,3.8,.39),.15,.74,'chrome')
        for a in (0,math.pi/2,math.pi,math.pi*1.5):
            xx=3.13+.93*math.cos(a);yy=3.8+.93*math.sin(a)
            box('Dining chair seat',(xx,yy,.47),(.43,.44,.09),'cream',.04)
            back=box('Dining chair back',(xx+.2*math.cos(a),yy+.2*math.sin(a),.78),(.08,.43,.64),'cream',.03);back.rotation_euler.z=a
            for dx in (-.16,.16):line('Chair leg',(xx+dx,yy-.14,.05),(xx+dx,yy+.13,.43),.012)
        picture(0,2.3,1.78,1.15,.58,'W')
        radiator(3.1,.16,1.45)
    elif id=='kitchen':
        for i in range(6):
            x=.35+i*.60
            if i not in (1,2):cabinet(x,d-.37)
            else:
                box('Appliance body',(x,d-.37,.44),(.58,.60,.88),'white' if i==2 else 'chrome',.012)
                box('Appliance worktop',(x,d-.37,.915),(.60,.64,.045),'counter',.008)
                if i==2:
                    cylinder('Washer door',(x,d-.685,.46),.205,.045,'black',rotation=(math.pi/2,0,0))
                    cylinder('Washer glass',(x,d-.715,.46),.157,.02,'mirror',rotation=(math.pi/2,0,0))
                else:
                    box('Oven glass',(x,d-.685,.46),(.48,.035,.43),'black',.015)
                    line('Oven handle',(x-.23,d-.72,.73),(x+.23,d-.72,.73),.014)
                    box('Hob',(x,d-.37,.938),(.58,.51,.024),'black',.012)
                    for dx in (-.16,.16):
                        for dy in (-.14,.14):cylinder('Gas burner',(x+dx,d-.37+dy,.963),.075,.018,'chrome')
        # Return cabinets, integrated tall unit, and upper cupboards.
        for y in (.42,1.03,1.64):
            cabinet(4.18,y,.64,.60)
        cabinet(3.85,d-.37,.65,.61,2.30)
        for i in (0,2,3,4):
            cabinet(.35+i*.66,d-.24,.62,.34,.65,base=1.51)
        box('White tiled splashback',(1.96,d-.11,1.2),(3.77,.025,.54),'tilewhite')
        for x in [i*.20 for i in range(20)]:
            line('Tile joint',(x,d-.13,.97),(min(x+.5,3.8),d-.13,1.48),.003,'grout')
        box('Extractor hood',(.95,d-.34,1.67),(.65,.51,.12),'chrome',.02)
        box('Extractor chimney',(.95,d-.22,2.04),(.27,.28,.65),'chrome',.012)
        box('Sink rim',(2.80,d-.38,.947),(.64,.46,.015),'chrome',.015)
        box('Sink bowl',(2.80,d-.38,.959),(.51,.34,.018),'black',.02)
        line('Sink tap',(2.80,d-.18,.97),(2.80,d-.18,1.32),.017)
        line('Sink tap spout',(2.80,d-.18,1.32),(2.80,d-.38,1.32),.017)
        cylinder('Kitchen bin',(.27,.73,.33),.19,.65,'chrome')
        box('Spice shelf',(.12,1.15,1.8),(.18,.93,.07),'black')
    elif id=='hall':
        box('Hall runner',(.90,2.6,.025),(.76,2.1,.024),'rug')
        cabinet(1.40,4.8,.65,.48,.83,'oak_light')
        radiator(.75,.16,1.05)
        box('Shoe rack',(.23,2.75,.25),(.37,1.0,.5),'black',.01)
        cylinder('Plant pot',(.28,3.28,.61),.14,.25,'taupe')
        line('Plant trunk',(.28,3.28,.7),(.28,3.28,1.72),.02,'oak')
        for i in range(12):
            a=i*2.4;ball('Plant foliage',(.28+.18*math.cos(a),3.28+.2*math.sin(a),1.12+i*.05),(.12,.12,.15),'green')
        box('Storage cupboard',(.34,7.2,1.16),(.66,1.0,2.3),'oak_light',.014)
        picture(.74,0,1.55,.8,.5,'S')
    elif id=='study':
        radiator(w-.15,2.10,1.0,math.pi/2)
        box('Small desk',(.57,2.63,.74),(.94,.5,.04),'white',.008)
        for x in (.15,.99):line('Desk leg',(x,2.64,0),(x,2.64,.74),.016)
        box('Vacuum dock',(.23,.59,.45),(.16,.20,.90),'black',.035)
        cylinder('Robot vacuum',(.56,.5,.065),.17,.13,'black')
    elif id in ('bathroom','ensuite','loft_bathroom'):
        if id=='bathroom':
            box('Bath panel',(.46,1.24,.30),(.76,1.7,.60),'ceramic',.025)
            box('Bath rim',(.46,1.24,.61),(.81,1.76,.07),'ceramic',.04)
            box('Bath recess',(.46,1.24,.654),(.59,1.51,.014),'basin_shadow',.08)
            line('Bath shower riser',(.43,2.06,1.05),(.43,2.06,2.1),.016)
            line('Bath shower arm',(.43,2.06,2.1),(.43,1.87,2.1),.016)
            cylinder('Bath shower head',(.43,1.87,2.09),.065,.025,'chrome')
            basin(1.60,1.92);wc(1.52,.59)
        elif id=='ensuite':
            shower(.58,1.58,.9,.95);basin(1.52,1.90)
            cabinet(1.52,.34,.60,.28,1.05,'white')
        else:
            shower(1.60,2.23,.95,1.18);wc(.51,2.55);basin(.51,1.1,True)
            for i in range(9):line('Towel rail rung',(1.95,.56,.45+i*.10),(1.95,1.11,.45+i*.10),.011)
        if id!='loft_bathroom':
            # A visible mosaic band, with a repeatable unmeasured tile pattern.
            for i in range(int(w/.095)):
                for j in range(5):box('Mosaic tile',(.05+i*.095,d-.115,.73+j*.095),(.09,.014,.09),['black','stone','taupe','tilewhite'][(i*7+j*3)%4])
            cylinder('Round mirror',(w-.50,d-.15,1.64),.29,.027,'mirror',48,(math.pi/2,0,0))
        else:picture(.52,0,1.57,.68,.66,'W','mirror')
        box('Bath mat',(w*.55,d*.45,.023),(.65,.82,.023),'fabric')
    elif id=='bedroom':
        bed(1.42,2.32,1.45,1.96,True)
        cabinet(2.86,3.28,.79,.48,.84,'white')
        radiator(.55,3.64,.77)
        cylinder('Pendant shade',(1.8,1.9,2.20),.22,.29,'taupe')
    elif id=='stairs':
        # Turned flight: upper landing bridges to the loft corridor. The compact
        # run is an unmeasured layout assumption, not a building-code design.
        rise=2.9/14;run=1.4/7
        box('Stair bottom landing',(1.56,.3,.01),(.98,.6,.04),'carpet')
        box('Stair half landing',(1.05,2.35,1.40),(2.0,.70,.10),'carpet')
        box('Stair top landing',(1.05,.3,2.85),(2.0,.6,.10),'carpet')
        for i in range(7):
            y=.6+(i+.5)*run;z=(i+1)*rise
            box('Lower stair tread',(1.57,y,z/2),(.94,run,z),'carpet')
            y2=2-(i+.5)*run;z2=1.45+(i+1)*rise
            box('Upper stair tread',(.53,y2,z2-.08),(.94,run,.16),'carpet')
            line('Baluster',(1.04,y2,z2),(1.04,y2,z2+.86),.016,'white')
        line('Upper stair rail',(1.04,1.9,2.51),(1.04,.7,3.76),.032,'white')
    elif id=='office':
        sofa(1.6,.57,2.15,math.pi)
        # Desk at opposite end below the slope, with chair.
        box('Office desk',(1.16,4.2,.76),(1.5,.68,.05),'white',.012)
        for x in (.47,1.84):
            for y in (3.96,4.46):line('Desk leg',(x,y,.02),(x,y,.74),.019,'black')
        box('Monitor',(1.12,4.40,1.18),(.71,.055,.43),'black',.016)
        line('Monitor stand',(1.12,4.42,.78),(1.12,4.42,1.01),.024,'black')
        box('Office chair seat',(1.22,3.3,.53),(.51,.48,.13),'charcoal',.06)
        box('Office chair back',(1.22,3.10,.90),(.49,.11,.65),'charcoal',.06)
        cylinder('Chair pedestal',(1.22,3.3,.28),.04,.50,'chrome')
        for a in range(5):line('Chair base',(1.22,3.3,.10),(1.22+.31*math.cos(a*1.257),3.3+.31*math.sin(a*1.257),.06),.022)
        cylinder('Office round mirror',(1.87,.14,1.56),.33,.025,'mirror',48,(math.pi/2,0,0))
        picture(0,1.8,1.60,.66,.98,'W','plum')
    elif id=='loft_bedroom':
        bed(3.34,2.34,1.65,2.04,False,-math.pi/2)
        for x in (.40,1.10):cabinet(x,4.5,.67,.58,2.27,'white')
        cabinet(.42,2.73,.65,.46,.94,'taupe')
        for x in (.62,3.73):radiator(x,.15,.75)
        cabinet(1.13,.63,.74,.4,.72,'white')
    elif id=='landing':
        picture(.8,0,1.65,.70,.50,'N')


def camera(name,loc,target,lens=22):
    data=bpy.data.cameras.new(name);obj=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(obj)
    obj.location=loc;obj.rotation_euler=(Vector(target)-Vector(loc)).to_track_quat('-Z','Y').to_euler();data.lens=lens;data.clip_start=.03
    obj['camera_status']='Approximate editorial viewpoint; not a solved camera'
    return obj


def light(name,loc,energy,size=3):
    data=bpy.data.lights.new(name,'AREA');data.energy=energy;data.shape='DISK';data.size=size
    obj=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(obj);obj.location=loc
    return obj


def main():
    global ROOT,ROOM,COL,CEILINGS
    p=argparse.ArgumentParser();p.add_argument('--spec',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--pilot',action='store_true');p.add_argument('--render',action='store_true');p.add_argument('--walkthrough',action='store_true')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);spec=json.loads(args.spec.read_text());out=args.output;out.mkdir(parents=True,exist_ok=True)
    blend=out/('pilot.blend' if args.pilot else 'property.blend')
    if blend.exists():raise RuntimeError('Output exists; choose a new revision directory to preserve manual edits.')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for n,c in {'white':(.81,.80,.76),'tilewhite':(.87,.87,.83),'oak':(.37,.23,.10),'oak_light':(.52,.36,.18),'navy':(.047,.079,.18),'bluewall':(.21,.24,.32),'slate':(.18,.20,.22),'charcoal':(.10,.11,.12),'black':(.012,.015,.019),'carpet':(.48,.46,.40),'fabric':(.49,.50,.49),'linen':(.85,.83,.76),'cream':(.73,.71,.66),'plum':(.27,.12,.22),'taupe':(.30,.27,.23),'stone':(.44,.41,.34),'counter':(.78,.77,.69),'chrome':(.53,.56,.58),'brass':(.55,.39,.10),'glass':(.54,.72,.85),'screen':(.54,.66,.70),'mirror':(.33,.39,.42),'ceramic':(.92,.92,.89),'basin_shadow':(.53,.58,.56),'rug':(.16,.15,.13),'green':(.09,.19,.06),'art':(.20,.32,.37),'grout':(.45,.44,.40)}.items():
        mat(n,c,.25 if n in ('chrome','ceramic','counter','glass','screen','mirror') else .68,.85 if n in ('chrome','brass','mirror') else 0,n in ('fabric','carpet','stone','oak','oak_light'))
    screen=M['screen'].node_tree.nodes.get('Principled BSDF');screen.inputs['Transmission Weight'].default_value=.5;screen.inputs['Alpha'].default_value=.22
    M['screen'].surface_render_method='DITHERED';M['screen'].diffuse_color=(.54,.66,.70,.22)
    for n in ('glass',):
        bs=M[n].node_tree.nodes.get('Principled BSDF');bs.inputs['Emission Color'].default_value=(.53,.68,.82,1);bs.inputs['Emission Strength'].default_value=.45
    CEILINGS=bpy.data.collections.new('CEILINGS • toggle for cutaway');bpy.context.scene.collection.children.link(CEILINGS)
    user=bpy.data.collections.new('USER_EDITS • save your working copy');bpy.context.scene.collection.children.link(user)
    rooms=[r for r in spec['rooms'] if not args.pilot or r['id'] in ('living','kitchen','hall')]
    for room in rooms:
        ROOM=room;COL=bpy.data.collections.new(room['name']);bpy.context.scene.collection.children.link(COL)
        ROOT=bpy.data.objects.new(room['name']+' • approximate',None);COL.objects.link(ROOT);ROOT.location=room['origin'];tag(ROOT);ROOT['coverage']=room['coverage']
        shell(room);furnish(room)
        x,y,z=room['origin'];w,d,h=room['size']
        light(room['name']+' soft light',(x+w*.5,y+d*.5,z+min(h,2.5)-.1),max(35,w*d*6),min(w,d)*.65)
    ROOT=ROOM=COL=None
    scene=bpy.context.scene;scene.unit_settings.system='METRIC';scene.unit_settings.length_unit='METERS'
    scene['status']=spec['status'];scene['source']='IMG_5677.MOV';scene['unmeasured_scale']=True
    world=bpy.data.worlds.new('Daylight');scene.world=world;world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.68,.76,.88,1);world.node_tree.nodes['Background'].inputs[1].default_value=.35
    scene.render.engine='CYCLES';scene.cycles.samples=20;scene.cycles.use_denoising=True
    scene.render.resolution_x=1100;scene.render.resolution_y=800;scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'
    scene.render.image_settings.file_format='PNG'
    views={
      'living':((3.62,4.93,1.62),(4.20,.6,1.15),22),
      'kitchen':((3.65,4.3,1.62),(4.16,7.60,1.25),22),
      'hall':((.87,.6,1.62),(.87,6.7,1.3),20),
      'study':((-.27,1.45,1.6),(-2.30,1.5,1.0),19),
      'bathroom':((-.22,4.11,1.60),(-1.49,4.6,.95),17),
      'bedroom':((.95,8.90,1.6),(1.85,10.7,1.0),20),
      'ensuite':((4.45,8.60,1.6),(4.45,9.72,1.05),18),
      'stairs':((-.48,5.83,1.4),(-.52,7.4,2.2),20),
      'office':((-1.0,4.87,4.45),(-1.75,.9,3.9),20),
      'loft_bedroom':((3.50,7.25,4.45),(4.70,4.50,3.8),20),
      'loft_bathroom':((2.88,8.30,4.4),(2.90,10.42,3.95),18)}
    cameras={k:camera('View / '+k,*v) for k,v in views.items() if k in {r['id'] for r in rooms}}
    overview=camera('Overview • layout hypothesis',(17,-17,22),(1.5,5.7,1.4),45);overview.data.type='ORTHO';overview.data.ortho_scale=21
    scene.camera=cameras['living']
    note=bpy.data.texts.new('START HERE — reconstruction status');note.write(spec['status']+'\n\n'+ '\n'.join(spec['uncertainties'])+'\n\nRoom roots can be moved. Edit the JSON dimensions and regenerate into a new revision.\nSave manual changes as a separate working copy.\nCEILINGS collection hides the roof for inspection.\nView cameras are approximate, not COLMAP poses.\n')
    script=bpy.data.texts.new('scene_spec.json');script.write(json.dumps(spec,indent=2))
    # Opening view: use material colors and a useful global perspective.
    for screen_ in bpy.data.screens:
        for area in screen_.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.shading.type='MATERIAL'
                area.spaces.active.region_3d.view_distance=22
                area.spaces.active.region_3d.view_location=(1.5,5.5,1.6)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    if args.render:
        render_dir=out/'renders';render_dir.mkdir(exist_ok=True)
        for k,cam in cameras.items():
            scene.camera=cam;scene.render.filepath=str(render_dir/f'{k}.png');bpy.ops.render.render(write_still=True)
        # All upper rooms remain intact in the file; individual floor cutaways are renders only.
        for level,label in [(0,'main_level'),(2.9,'loft_level')]:
            saved=[]
            for obj in scene.objects:
                if obj.type=='MESH':
                    saved.append((obj,obj.hide_render))
                    if obj.parent:
                        root=obj
                        while root.parent:root=root.parent
                        obj.hide_render=abs(root.location.z-level)>.1 or obj.name.startswith('Ceiling') or obj.name.startswith('Sloped ceiling') or obj.name.startswith('Rooflight')
                    if any(c==CEILINGS for c in obj.users_collection):obj.hide_render=True
                    if obj.get('room_id')=='stairs' and 'wall' in obj.name:obj.hide_render=True
            scene.camera=overview;overview.location.z=22+level;overview.rotation_euler=(Vector((1.5,5.7,level)) - overview.location).to_track_quat('-Z','Y').to_euler()
            scene.render.filepath=str(render_dir/f'{label}.png');bpy.ops.render.render(write_still=True)
            for ob,v in saved:ob.hide_render=v
        scene.camera=cameras['living']
    stats=dict(blender=bpy.app.version_string,rooms=len(rooms),objects=len(scene.objects),mesh_objects=sum(o.type=='MESH' for o in scene.objects),cameras=list(cameras),scale='unmeasured',source_spec=str(args.spec.resolve()))
    (out/'build.json').write_text(json.dumps(stats,indent=2))
    print(json.dumps(stats))


if __name__=='__main__':main()
