"""Fit an approximate camera to explicit appliance landmarks, not survey data.

The nominal washer body is 0.58 x 0.88 m. Focal length is an assumption;
this planar fit is useful for visual comparison, not metric validation.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from scipy.optimize import least_squares
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('output/reconstruction/IMG_5677'));root=p.parse_args().root
# Washer front corners + oven-glass corners, manually located in view_0185.jpg.
points=[
 ('washer top left',[3.06,7.315,.88],[255,903]),
 ('washer top right',[3.64,7.315,.88],[378,908]),
 ('washer bottom right',[3.64,7.315,0],[376,1087]),
 ('washer bottom left',[3.06,7.315,0],[251,1082]),
 ('oven glass top left',[2.51,7.2975,.675],[137,927]),
 ('oven glass top right',[2.99,7.2975,.675],[252,932]),
 ('oven glass bottom left',[2.51,7.2975,.245],[131,1018]),
 ('oven glass bottom right',[2.99,7.2975,.245],[251,1025])]
xyz=np.array([x[1] for x in points],np.float64);xy=np.array([x[2] for x in points],np.float64)
K=np.array([[900,0,360],[0,900,640],[0,0,1]],np.float64)
def residual(params):
    R=cv2.Rodrigues(params[3:])[0];t=-R@params[:3]
    uv,_=cv2.projectPoints(xyz,params[3:],t,K,None)
    return (uv[:,0]-xy).ravel()
solution=least_squares(residual,[3.5,3.2,1.6,np.pi/2,0,0],
                       bounds=([1.9,.5,1.15,.9,-.5,-.5],[6.1,6.8,1.9,2.2,.5,.5]),max_nfev=500)
center=solution.x[:3];rvec=solution.x[3:];R=cv2.Rodrigues(rvec)[0];tvec=-R@center
T=np.eye(4);T[:3,:3]=R;T[:3,3]=tvec.ravel()
uv,_=cv2.projectPoints(xyz,rvec,tvec,K,None);errors=np.linalg.norm(uv[:,0]-xy,axis=1)
result=dict(source='reference/view_0185.jpg',timestamp_s=185,width=720,height=1280,K=K.tolist(),cam_from_world=T.tolist(),center=center.tolist(),rms_px=float(np.sqrt(np.mean(errors**2))),landmarks=[dict(name=a,world=b,pixel=c,error_px=float(e)) for (a,b,c),e in zip(points,errors)],status='Approximate alignment to nominal appliance geometry; focal length assumed 900 px; residuals are fitting errors, not independent accuracy')
(root/'camera_fit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
