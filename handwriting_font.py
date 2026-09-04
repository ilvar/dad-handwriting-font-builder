#!/usr/bin/env python3
"""Turn corrected character crops from the scan into a TrueType font."""
from __future__ import annotations
import json, math, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
WORK, PDF = ROOT / "work", ROOT / "Scanned Document.pdf"
SCAN, BOX = WORK / "scan400.png", WORK / "ocrchars.box"
SAMPLES, SETTINGS = ROOT / "glyph_samples.json", ROOT / "font_settings.json"
OUTPUT, VENDOR = ROOT / "DadHandwriting.ttf", WORK / "vendor"
sys.path.insert(0, str(VENDOR))
CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
DIGITS, PUNCT = "0123456789", ".,!?;:-—()«»\"'№"
ALLOWED = set(CYRILLIC + LATIN + DIGITS + PUNCT)

def current_source():
    marker=WORK/"source.json"
    if marker.exists():
        path=WORK/json.loads(marker.read_text(encoding="utf-8"))["file"]
        if path.exists(): return path
    return PDF

def import_document(content, filename):
    """Install an uploaded PDF/PNG/JPEG as the active source and rerun OCR."""
    suffix=Path(filename).suffix.lower()
    if suffix not in {".pdf",".png",".jpg",".jpeg"}: raise ValueError("Upload a PDF, PNG, JPG, or JPEG file")
    if not content or len(content)>25*1024*1024: raise ValueError("File must be between 1 byte and 25 MB")
    WORK.mkdir(exist_ok=True); target=WORK/("uploaded"+suffix); target.write_bytes(content)
    marker={"file":target.name,"original_name":Path(filename).name}
    (WORK/"source.json").write_text(json.dumps(marker,ensure_ascii=False,indent=2),encoding="utf-8")
    for path in (SCAN,BOX,SAMPLES,SETTINGS):
        if path.exists(): path.unlink()
    prepare()
    width,height=Image.open(SCAN).size
    return {"samples":load_samples(),"settings":load_settings(),"filename":Path(filename).name,"width":width,"height":height}

def prepare():
    WORK.mkdir(exist_ok=True)
    if not SCAN.exists():
        source=current_source()
        if source.suffix.lower()==".pdf":
            subprocess.run(["pdftoppm","-png","-r","400","-singlefile",str(source),str(WORK/"scan400")],check=True)
        else:
            image=Image.open(source).convert("RGB")
            if image.width<2200: image=image.resize((2200,round(image.height*2200/image.width)),Image.Resampling.LANCZOS)
            image.save(SCAN)
    if not BOX.exists():
        subprocess.run(["tesseract", str(SCAN), str(WORK/"ocrchars"), "-l", "rus", "--psm", "6", "makebox"], check=True)

def initial_samples():
    prepare(); height = Image.open(SCAN).height; result = []
    for i, line in enumerate(BOX.read_text(encoding="utf-8").splitlines()):
        parts = line.rsplit(" ", 5)
        if len(parts) != 6: continue
        label, left, bottom, right, top, _page = parts
        if len(label) != 1 or label not in ALLOWED: continue
        x1, x2, y1, y2 = int(left), int(right), height-int(top), height-int(bottom)
        if x2-x1 < 8 or y2-y1 < 12: continue
        result.append({"id":i+1,"char":label,"x":x1,"y":y1,"w":x2-x1,"h":y2-y1,"enabled":True})
    return result

def load_samples():
    if not SAMPLES.exists():
        data = initial_samples(); save_samples(data); return data
    return json.loads(SAMPLES.read_text(encoding="utf-8"))

def save_samples(data):
    SAMPLES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_settings():
    default={"global":{"weight":0},"glyphs":{}}
    if not SETTINGS.exists():
        SETTINGS.write_text(json.dumps(default,ensure_ascii=False,indent=2),encoding="utf-8")
        return default
    data=json.loads(SETTINGS.read_text(encoding="utf-8"))
    data.setdefault("global",{}).setdefault("weight",0); data.setdefault("glyphs",{})
    return data

def save_settings(data):
    SETTINGS.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

def _otsu(a):
    hist=np.bincount(a.ravel(),minlength=256).astype(float); total=a.size; sa=np.dot(np.arange(256),hist)
    wb=sb=0.; best=190; bestvar=-1.
    for t in range(256):
        wb+=hist[t]
        if not wb: continue
        wf=total-wb
        if not wf: break
        sb+=t*hist[t]; mb=sb/wb; mf=(sa-sb)/wf; var=wb*wf*(mb-mf)**2
        if var>bestvar: bestvar,best=var,t
    return min(best+18,225)

def crop_bitmap(scan, sample, weight=0):
    x,y,w,h=(int(sample[k]) for k in ("x","y","w","h")); pad=max(3,int(min(w,h)*.04))
    b=(max(0,x-pad),max(0,y-pad),min(scan.width,x+w+pad),min(scan.height,y+h+pad))
    a=np.asarray(scan.crop(b).convert("L")); ink=a<_otsu(a); ys,xs=np.nonzero(ink)
    if not len(xs): return None
    x1,x2=max(0,xs.min()-1),min(ink.shape[1],xs.max()+2); y1,y2=max(0,ys.min()-1),min(ink.shape[0],ys.max()+2)
    ink=ink[y1:y2,x1:x2]; scale=min(1.,150/max(ink.shape))
    if scale<1:
        p=Image.fromarray((ink*255).astype("uint8")).resize((max(2,round(ink.shape[1]*scale)),max(2,round(ink.shape[0]*scale))),Image.Resampling.LANCZOS)
        ink=np.asarray(p)>85
    weight=int(round(weight))
    if weight:
        from scipy.ndimage import binary_dilation, binary_erosion
        ink=binary_dilation(ink,iterations=weight) if weight>0 else binary_erosion(ink,iterations=-weight)
    return ink

def _contours(bitmap):
    edges=set()
    for y,x in zip(*np.nonzero(bitmap)):
        p=[(x,y),(x+1,y),(x+1,y+1),(x,y+1)]
        for a,b in zip(p,p[1:]+p[:1]):
            if (b,a) in edges: edges.remove((b,a))
            else: edges.add((a,b))
    outgoing={}
    for a,b in edges: outgoing.setdefault(a,[]).append(b)
    loops=[]
    while edges:
        start,cur=next(iter(edges)); prev=start; loop=[start]
        while True:
            edges.discard((prev,cur)); loop.append(cur)
            if cur==start: break
            choices=[n for n in outgoing.get(cur,()) if (cur,n) in edges]
            if not choices: break
            dx,dy=cur[0]-prev[0],cur[1]-prev[1]
            choices.sort(key=lambda n:(dx*(n[1]-cur[1])-dy*(n[0]-cur[0]),-(dx*(n[0]-cur[0])+dy*(n[1]-cur[1]))))
            prev,cur=cur,choices[0]
        if len(loop)>4 and loop[-1]==start:
            simple=[]
            for p in loop[:-1]:
                if len(simple)>=2:
                    a,b=simple[-2],simple[-1]
                    if (b[0]-a[0])*(p[1]-b[1])==(b[1]-a[1])*(p[0]-b[0]): simple[-1]=p; continue
                simple.append(p)
            if len(simple)>=3: loops.append(simple)
    return loops

def _name(ch): return "uni%04X"%ord(ch) if ord(ch)<=0xffff else "u%X"%ord(ch)
def _score(s):
    w,h=float(s["w"]),float(s["h"]); aspect=w/max(h,1)
    return abs(math.log(max(h,1)/125))+max(0,aspect-1.3)*2+max(0,.15-aspect)*3

def build_font(output=None):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    output=Path(output) if output else OUTPUT
    samples=[s for s in load_samples() if s.get("enabled",True) and len(s.get("char",""))==1]
    grouped={}
    for s in samples: grouped.setdefault(s["char"],[]).append(s)
    chosen={c:min(v,key=_score) for c,v in grouped.items()}; settings=load_settings(); scan=Image.open(SCAN); chars=sorted(chosen,key=ord)
    order=[".notdef","space"]+[_name(c) for c in chars]; glyphs={}; metrics={}
    pen=TTGlyphPen(None); pen.moveTo((80,0)); pen.lineTo((520,0)); pen.lineTo((520,700)); pen.lineTo((80,700)); pen.closePath(); pen.moveTo((150,80)); pen.lineTo((150,620)); pen.lineTo((450,620)); pen.lineTo((450,80)); pen.closePath()
    glyphs[".notdef"]=pen.glyph(); metrics[".notdef"]=(600,50); glyphs["space"]=TTGlyphPen(None).glyph(); metrics["space"]=(300,0); built=[]
    for ch in chars:
        cfg=settings["glyphs"].get(ch,{}); weight=float(settings["global"].get("weight",0))+float(cfg.get("weight",0)); bm=crop_bitmap(scan,chosen[ch],weight)
        if bm is None: continue
        desc=ch.lower() in "друфцщз" or ch in ",;"; size=max(.4,min(2.,float(cfg.get("scale",1)))); scale=(700 if ch.isupper() else 520)*size/max(bm.shape[0],1); left=55; bottom=(-170 if desc else 0)+int(cfg.get("baseline",0)); pen=TTGlyphPen(None)
        for loop in _contours(bm):
            pts=[(round(left+x*scale),round(bottom+(bm.shape[0]-y)*scale)) for x,y in loop]
            pen.moveTo(pts[0])
            for p in pts[1:]: pen.lineTo(p)
            pen.closePath()
        name=_name(ch); natural=max(220,round(bm.shape[1]*scale+115)); advance=int(cfg.get("advance",0) or natural); metrics[name]=(max(100,advance),left); glyphs[name]=pen.glyph(); built.append(ch)
    if "-" not in chosen:
        pen=TTGlyphPen(None); pen.moveTo((50,230)); pen.lineTo((350,230)); pen.lineTo((350,270)); pen.lineTo((50,270)); pen.closePath(); n=_name("-"); order.append(n); glyphs[n]=pen.glyph(); metrics[n]=(410,50); built.append("-")
    cmap={32:"space"}; cmap.update({ord(c):_name(c) for c in built})
    fb=FontBuilder(1000,isTTF=True); fb.setupGlyphOrder(order); fb.setupCharacterMap(cmap); fb.setupGlyf(glyphs); fb.setupHorizontalMetrics(metrics); fb.setupHorizontalHeader(ascent=820,descent=-220,lineGap=120)
    fb.setupNameTable({"familyName":"Dad Handwriting","styleName":"Regular","uniqueFontIdentifier":"Dad Handwriting Regular 1.0","fullName":"Dad Handwriting Regular","psName":"DadHandwriting-Regular","version":"Version 1.0"})
    fb.setupOS2(sTypoAscender=820,sTypoDescender=-220,sTypoLineGap=120,usWinAscent=850,usWinDescent=240); fb.setupPost(keepGlyphNames=False); fb.setupMaxp(); fb.font.save(output)
    return {"output":str(output),"characters":"".join(built),"count":len(built)}

def main():
    prepare(); load_samples(); load_settings()
    if "--prepare" in sys.argv: print(f"Prepared {SCAN} and {SAMPLES}")
    else: print(json.dumps(build_font(),ensure_ascii=False,indent=2))
if __name__=="__main__": main()
