#!/usr/bin/env python3
import json,urllib.request,urllib.parse
KEY="dc4865146fd5436dbeadb0781e6599bf";B="http://localhost:8096"
ANIME="0c41907140d802bb58430fed7e2cd79e"
def g(p):
    r=urllib.request.Request(B+p,headers={"X-Emby-Token":KEY})
    with urllib.request.urlopen(r,timeout=120) as x:return json.load(x)
ENG={"eng","en","english"}
def streams_of(it): return it.get("MediaStreams") or []
def subs(it): return [s for s in streams_of(it) if s.get("Type")=="Subtitle"]
def has_eng(it): return any((s.get("Language") or "").lower() in ENG for s in subs(it))

eps=g("/Items?"+urllib.parse.urlencode({
    "ParentId":ANIME,"IncludeItemTypes":"Episode","Recursive":"true",
    "Fields":"MediaStreams,SeriesName","Limit":"100000"})).get("Items",[])

# --- One Pace breakdown ---
op=[e for e in eps if (e.get("SeriesName") or "")=="One Pace"]
zero_sub=[e for e in op if len(subs(e))==0]
sub_no_eng=[e for e in op if len(subs(e))>0 and not has_eng(e)]
print(f"One Pace: total={len(op)}  zero_subtitle_streams(unprobed?)={len(zero_sub)}  has_subs_but_no_eng={len(sub_no_eng)}")
print("\n--- sample One Pace WITHOUT eng: full subtitle streams ---")
for e in (sub_no_eng[:3] if sub_no_eng else op[:3]):
    print(" *",(e.get("Name") or "")[:45])
    for s in subs(e):
        print(f"     idx{s.get('Index')} codec={s.get('Codec')} lang={s.get('Language')} title={s.get('Title')!r} ext={s.get('IsExternal')} default={s.get('IsDefault')} forced={s.get('IsForced')}")
    if not subs(e): print("     (NO subtitle streams at all)")
print("\n--- sample One Pace that DOES have eng ---")
ok=[e for e in op if has_eng(e)]
for e in ok[:2]:
    print(" *",(e.get("Name") or "")[:45])
    for s in subs(e):
        print(f"     idx{s.get('Index')} codec={s.get('Codec')} lang={s.get('Language')} title={s.get('Title')!r}")

# --- Frieren missing ones: confirm genuinely no eng ---
fr=[e for e in eps if (e.get("SeriesName") or "").startswith("Frieren") and not has_eng(e)]
print(f"\nFrieren missing eng: {len(fr)} -- sample streams:")
for e in fr[:2]:
    print(" *",(e.get("Name") or "")[:45])
    for s in subs(e):
        print(f"     idx{s.get('Index')} codec={s.get('Codec')} lang={s.get('Language')} title={s.get('Title')!r}")
    if not subs(e): print("     (NO subtitle streams at all)")
