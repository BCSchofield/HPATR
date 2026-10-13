import sys; sys.path.insert(0,'.')
import numpy as np, cv2
import f2h1_core as C
print("straight cylinders (vertical, and 30 deg), width W, length 400: round/expected, ribbon/expected_round")
for W in [1,2,3,4,5,8,11,20,40,60]:
    for ang in [0,30]:
        m = np.zeros((900,900),np.uint8)
        c=(450,450); L=400
        box = cv2.boxPoints(((450,450),(W,L),ang)) if ang else None
        if ang==0:
            m[250:650, 450-W//2:450-W//2+W]=1
        else:
            cv2.fillPoly(m,[np.round(box).astype(np.int32)],1)
        m=m.astype(bool)
        r,rb,Rm,_=C.chord_maps(m)
        A=m.sum(); Weff=A/L
        exp=np.pi*Weff**2/4*L
        print(f"W={W:3d} ang={ang:2d} A={A:6d} round/exp={r.sum()/exp:.3f} ribbon/exp={rb.sum()/exp:.3f} daves/exp={C.daves_volume(*[a.astype(float) for a in np.nonzero(m)])/exp:.3f}")
print("discs: chord-round vs sphere-from-area and Daves")
for d in [5,9,15,25,51,101]:
    m=np.zeros((300,300),np.uint8); cv2.circle(m,(150,150),d//2,1,-1); m=m.astype(bool)
    r,rb,Rm,_=C.chord_maps(m); A=m.sum(); de=np.sqrt(4*A/np.pi); vs=np.pi*de**3/6
    print(f"d={d:3d} A={A} skel-round/sphere={r.sum()/vs:.3f} ribbon/sphere={rb.sum()/vs:.3f} daves/sphere={C.daves_volume(*[a.astype(float) for a in np.nonzero(m)])/vs:.3f}")
print("ellipse 3:1 major 60")
m=np.zeros((300,300),np.uint8); cv2.ellipse(m,(150,150),(30,10),20,0,360,1,-1); m=m.astype(bool)
r,rb,Rm,_=C.chord_maps(m); exp=4/3*np.pi*30*10*10
print('prolate spheroid exp', round(exp), 'round', round(r.sum()), 'daves', round(C.daves_volume(*[a.astype(float) for a in np.nonzero(m)])))
