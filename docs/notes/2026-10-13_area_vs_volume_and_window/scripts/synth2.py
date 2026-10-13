import sys; sys.path.insert(0,'.')
import numpy as np, cv2
from scipy import ndimage as ndi
import f2h1_core as C
def variant(mask, mode, off):
    dist = ndi.distance_transform_edt(mask).astype(np.float32)
    ridge = ndi.maximum_filter(dist, size=3) if mode=='max3' else dist
    sk = C.skeletonize(mask)
    Rsk = np.where(sk, ridge-off, 0); Rsk=np.maximum(Rsk,0.5*sk)
    iy,ix = ndi.distance_transform_edt(~sk, return_distances=False, return_indices=True)
    Rp = Rsk[iy,ix]; e=np.clip(dist-0.5,0,None); e=np.minimum(e,Rp)
    ch=2*np.sqrt(np.maximum(Rp**2-(Rp-e)**2,0))
    return ch[mask].sum(), Rp[mask].sum()
def cyl(W,ang,L=400):
    yy,xx=np.mgrid[0:700,0:700]; t=np.deg2rad(ang); u=(xx-350)*np.cos(t)+(yy-350)*np.sin(t); v=-(xx-350)*np.sin(t)+(yy-350)*np.cos(t)
    m=(np.abs(u)<=L/2)&(np.abs(v)<=W/2); return m, np.pi*W**2/4*L
def disc(d):
    yy,xx=np.mgrid[0:300,0:300]; m=(xx-150.3)**2+(yy-150.2)**2<=(d/2)**2; return m, np.pi*d**3/6
for mode,off in [('raw',0.5),('raw',0.25),('max3',0.5),('max3',0.25)]:
    out=[]
    for W in [2,3,4,6,10,20,40]:
        for ang in [0,30,45]:
            m,exp=cyl(W,ang); out.append(variant(m,mode,off)[0]/exp)
    o2=[variant(*[disc(d)[0],mode,off])[0]/disc(d)[1] for d in [5,9,15,25,51]]
    print(mode,off,'cyl',np.round(out,2).tolist()); print('   disc',np.round(o2,3).tolist())
