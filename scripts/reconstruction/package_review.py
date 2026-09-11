"""Create the local evidence report, reference manifest and labelled overview."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
from PIL import Image,ImageDraw,ImageFont,ImageOps

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('output/reconstruction/IMG_5677'));p.add_argument('--model',default='model_v4');p.add_argument('--extract-reference-views',action='store_true');p.add_argument('--references-only',action='store_true');a=p.parse_args();root=a.root.resolve();root.mkdir(parents=True,exist_ok=True);out=root/'deliverables';out.mkdir(exist_ok=True);renders=root/'final_renders';renders.mkdir(exist_ok=True);(root/'reference').mkdir(exist_ok=True)
refs=[(24,0),(32,0),(50,0),(65,0),(75,0),(95,90),(115,90),(185,0),(195,0),(545,0),(615,0),(725,0),(755,90),(835,0),(885,0),(935,0),(985,0),(1085,0),(1145,0)]
if a.extract_reference_views:
    for t,roll in refs:
        path=root/'reference'/f'view_{t:04d}.jpg'
        if path.exists():continue
        subprocess.run(['ffmpeg','-v','error','-ss',str(t),'-i','examples/videos/IMG_5677.MOV','-frames:v','1','-vf','scale=720:-2','-q:v','2',str(path)],check=True)
        if roll:Image.open(path).rotate(roll,expand=True).save(path,quality=94)
if a.references_only:sys.exit(0)
for path in (root/a.model/'renders').glob('*.png'):
    target=renders/path.name
    if not target.exists():shutil.copy2(path,target)
spec=json.loads(Path('scripts/reconstruction/IMG_5677.scene.json').read_text());pilot=json.loads((root/'pilot'/'manifest.json').read_text());sfm=json.loads((root/'pilot'/'result.json').read_text())
shutil.copy2('scripts/reconstruction/IMG_5677.scene.json',out/'editable_dimensions.json')
records=[]
for path in sorted((root/'reference').glob('*.jpg')):
    if not (path.stem.startswith('view_') or path.stem[0]=='t'):continue
    timestamp=int(path.stem[5:] if path.stem.startswith('view_') else path.stem[1:])
    records.append(dict(file=str(path.relative_to(root)),timestamp_s=timestamp,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),role='human reference',viewing_transform='FFmpeg display rotation and scale; view images use recorded extra roll',extra_roll_degrees=dict(refs).get(timestamp,0) if path.stem.startswith('view_') else 0))
manifest=dict(source='IMG_5677.MOV',source_sha256=pilot['source_sha256'],source_duration_s=1280.013333,source_preserved=True,reference_views=records,colmap_manifest='../pilot/manifest.json',uncertainties=spec['uncertainties'])
(out/'reference_manifest.json').write_text(json.dumps(manifest,indent=2))
font='/System/Library/Fonts/Supplemental/Arial.ttf';bold='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
def f(size,b=False):return ImageFont.truetype(bold if b else font,size)
# A compact reusable preview, with its accuracy limit printed into the image.
board=Image.new('RGB',(1800,1360),(242,240,232));d=ImageDraw.Draw(board)
d.text((70,42),'IMG_5677  /  PROPERTY RECONSTRUCTION',font=f(26,True),fill=(31,42,46))
d.text((70,86),'Editable interior model',font=f(47,True),fill=(31,42,46))
d.text((70,150),'Approximate dimensions and layout · Source video: 21:20 · Two levels',font=f(22),fill=(76,84,86))
for name,label,x,y in [('main_level','MAIN LEVEL · inferred layout',50,220),('loft_level','LOFT LEVEL · inferred layout',920,220),('living','LIVING / DINING',50,770),('office','LOFT OFFICE',920,770)]:
    path=renders/f'{name}.png'
    if path.exists():
        im=ImageOps.fit(Image.open(path).convert('RGB'),(820,490));board.paste(im,(x,y));d.text((x,y+500),label,font=f(21,True),fill=(31,42,46))
d.text((50,1320),'Not a measured survey. Furniture, materials, bay shape and roof pitch are simplified.',font=f(20),fill=(90,80,66))
board.save(out/'overview.jpg',quality=93)
reference_for={'hall':32,'living':50,'kitchen':185,'study':835,'bathroom':545,'bedroom':725,'ensuite':755,'stairs':885,'office':935,'loft_bedroom':1085,'loft_bathroom':1145}
# Hall has a clearer existing audit image than the view at 00:32.
rows=[]
for room in spec['rooms']:
    k=room['id'];render=renders/f'{k}.png'
    if not render.exists():continue
    ref=f'view_{reference_for[k]:04d}.jpg'
    if k=='hall':ref='t0024.jpg' if (root/'reference'/'t0024.jpg').exists() else 'view_0024.jpg'
    timestamps=', '.join(f'{t//60:02d}:{t%60:02d}' for t in room['refs'])
    rows.append(f'<article><h3>{html.escape(room["name"])}</h3><div class="pair"><figure><a href="../reference/{ref}"><img loading="lazy" src="../reference/{ref}" alt="Video reference for {html.escape(room["name"])}"></a><figcaption>Video reference · viewing copy</figcaption></figure><figure><a href="../final_renders/{k}.png"><img loading="lazy" src="../final_renders/{k}.png" alt="Blender reconstruction of {html.escape(room["name"])}"></a><figcaption>Blender · approximate viewpoint</figcaption></figure></div><p>{html.escape(room["coverage"])}</p><p class="small">Evidence times: {timestamps}</p></article>')
fragment_rows=''.join(f'<tr><td>{c["component"]}</td><td>{c["registered"]}</td><td>{c["points"]:,}</td><td>{c["reprojection_error_px"]:.2f} px</td></tr>' for c in sfm['components'])
fit=json.loads((root/'camera_fit.json').read_text())
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>IMG_5677 — property reconstruction</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#f2f0e8;color:#263337;font:17px/1.6 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:52px 26px}h1{font-size:48px;line-height:1.12;letter-spacing:-1.6px;margin:12px 0 20px}h2{margin-top:64px;font-size:28px}h3{font-size:23px;margin:12px 0}p{max-width:880px}.eyebrow{font-size:13px;letter-spacing:2px;font-weight:700}.note{border-left:4px solid #ad8247;padding:10px 20px;background:#eae3d5}.links{display:flex;gap:12px;flex-wrap:wrap;margin:26px 0}a{color:#225657}a:focus-visible{outline:3px solid #996f36;outline-offset:4px}.links a{padding:10px 16px;background:#263e42;color:white;border-radius:4px;text-decoration:none}img,video{max-width:100%;display:block}.hero{width:100%;border-radius:4px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0;background:#e6e3db}figure img{width:100%;height:380px;object-fit:contain;background:#1f272b}figcaption{padding:10px 14px;font-size:13px}article{padding:30px 0;border-top:1px solid #c6cbc6}.small{font-size:13px;color:#58615f}table{border-collapse:collapse;width:100%;max-width:720px}td,th{text-align:left;border-bottom:1px solid #c6cbc6;padding:10px}li{margin:10px 0}video{width:900px;background:#182126}@media(max-width:650px){h1{font-size:36px}.pair{grid-template-columns:1fr}figure img{height:330px}main{padding:30px 18px}}
</style><main><div class="eyebrow">IMG_5677.MOV · LOCAL BLENDER RECONSTRUCTION</div><h1>The property, rebuilt as<br>an editable interior.</h1><p>Two levels, 12 room and circulation areas, with source references and recovered camera fragments kept alongside the model.</p><p class="note"><strong>Approximate reconstruction.</strong> No measured distance or floor plan was supplied. Dimensions, room offsets and camera positions are estimates. This model is a visual reference, not a measured survey or condition record.</p><nav class="links"><a href="IMG_5677_property.blend">Blender file</a><a href="IMG_5677_property.glb">GLB model</a><a href="editable_dimensions.json">Editable dimensions</a><a href="reference_manifest.json">Evidence manifest</a><a href="verification.json">File checks</a></nav><img class="hero" src="overview.jpg" alt="Main and loft level cutaways, living room and office renders"><h2>Animated room tour</h2><p>The preview moves a 3D camera within each room, with cuts between rooms. The Blender file contains the full 12 fps camera animation; this lightweight preview is encoded at 6 fps.</p><video controls preload="metadata" poster="../final_renders/living.png" src="walkthrough.mp4"></video><h2>Compare the room views</h2><p>These views document observed fittings and approximate modelling decisions. The paired images generally use different viewpoints; they are not pixel-aligned evidence of accuracy.</p>'''+''.join(rows)+f'''<h2>A fitted kitchen viewpoint</h2><p>The view below is fitted to eight manually identified washer and oven landmarks at 03:05, using nominal appliance geometry and an assumed 900 px focal length. The fitting RMS is {fit['rms_px']:.2f} px. This is a fitting residual, not independent validation or a measure of dimensional accuracy. Differences elsewhere show the limits of the simplified model.</p><div class="pair"><figure><img src="../reference/view_0185.jpg" alt="Original kitchen reference at 3 minutes 5 seconds"><figcaption>Source · 03:05</figcaption></figure><figure><img src="../final_renders/kitchen_matched_0305.png" alt="Model rendered from fitted kitchen camera"><figcaption>Model · fitted camera</figcaption></figure></div><h2>Recovered geometric evidence</h2><p>COLMAP registered 85 unique frames from 108 selected frames. It produced five overlapping fragments with conflicting focal estimates, so they remain in separate Blender scenes. A whole-property registration, global alignment and metric scale were not established.</p><table><tr><th>Fragment</th><th>Registered views</th><th>3D points</th><th>Mean reprojection error</th></tr>{fragment_rows}</table><p class="small">Fragment counts overlap. Low reprojection error within a fragment does not establish a correct property layout.</p><h2>Known limits and useful corrections</h2><ul>'''+''.join('<li>'+html.escape(x)+'</li>' for x in spec['uncertainties'])+'''</ul><p>A measured room width or floor plan would allow the next revision to replace nominal dimensions and resolve the global layout. All major mesh objects contain source timestamps; the room roots and dimension JSON make those corrections explicit.</p><h2>Opening and editing</h2><p>Open the .blend in Blender 5.2 LTS. Scene 01 contains the property, scene 02 the reference boards, and scenes 03–07 the separate COLMAP fragments. The ceilings are hidden in the opening viewport for inspection; toggle their collection to restore them. Use the timeline to play the room camera tour. Save your changes as a separate working copy before regenerating.</p><p class="small">Created locally. Original MOV preserved. Procedural materials and simplified furniture; no generated photographs or remote inference services used.</p></main></html>'''
(out/'review.html').write_text(page)
print('Review package ready:',out)
