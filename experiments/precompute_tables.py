from __future__ import annotations
import math, pickle
from pathlib import Path

def q(z):
    z%=256
    return min(z,256-z)

kappa=[10**9]*256
kappa_args=[None]*256
for f in range(1,256):
    for d in range(1,256):
        g=math.gcd(d,256)
        if f >= 256//g: continue
        z=(-f*d)&255
        cand=(q(z)+q(d),z,d)
        if kappa_args[f] is None or cand<kappa_args[f]:
            kappa[f]=cand[0]; kappa_args[f]=cand

decomp=[None]*256
for f in range(1,256):
    row=[]
    for k in range(256):
        best=None
        for b in range(256):
            r=(k-f*b)&255
            cand=(q(b)+q(r),b,r)
            if best is None or cand<best: best=cand
        row.append(best)
    decomp[f]=row

out=Path(__file__).resolve().parents[1]/'results'/'nested_tables.pkl'
out.write_bytes(pickle.dumps({'kappa':kappa,'kappa_args':kappa_args,'decomp':decomp},protocol=5))
print(out, out.stat().st_size)
