#!/usr/bin/env python3
import json,urllib.request
JF=("http://localhost:8096","dc4865146fd5436dbeadb0781e6599bf","X-Emby-Token")
SON=("http://localhost:8989","d1c99179d7784fc0b0ed06ceaf942c76","X-Api-Key")
RAD=("http://localhost:7878","95683c4e38974f558e96c63af17df5c5","X-Api-Key")

def get(svc,p):
    base,key,hdr=svc
    r=urllib.request.Request(base+p,headers={hdr:key})
    with urllib.request.urlopen(r,timeout=60) as x:
        return json.load(x)

# tasks that do deep whole-file reads over the streaming mount = DANGEROUS if scheduled
JF_DANGER={"RefreshChapterImages","RefreshTrickplayImages","AudioNormalization",
           "KeyframeExtraction","IntroSkipperDetectSegmentsTask","TaskExtractMediaSegments",
           "CPBIntroSkipperDetectIntroductions","CPBIntroSkipperDetectCredits"}

print("="*70)
print("JELLYFIN SCHEDULED TASKS (trigger count = will it auto-run?)")
print("="*70)
tasks=get(JF,"/ScheduledTasks")
flagged=[]
for t in sorted(tasks,key=lambda x:x.get("Name","")):
    trig=len(t.get("Triggers") or [])
    key=t.get("Key","")
    danger=key in JF_DANGER
    mark=""
    if danger and trig>0: mark=" <<< DANGER: deep-read task is SCHEDULED"; flagged.append(t.get("Name"))
    elif danger and trig==0: mark=" (deep-read, but disarmed: 0 triggers - OK)"
    print(f"  {t.get('Name'):44s} triggers={trig} state={t.get('State'):8s}{mark}")
print("\nFLAGGED dangerous+scheduled:",flagged or "NONE")

print("\n"+"="*70)
print("JELLYFIN PER-LIBRARY DEEP-SCAN OPTIONS")
print("="*70)
vf=get(JF,"/Library/VirtualFolders")
risk_keys=["EnableTrickplayImageExtraction","SaveTrickplayWithMedia",
           "EnableChapterImageExtraction","ExtractChapterImagesDuringLibraryScan",
           "EnableRealtimeMonitor","EnableLUFSScan","EnableInternetProviders"]
for lib in vf:
    opt=lib.get("LibraryOptions",{}) or {}
    print(f"\n  [{lib.get('Name')}]  ({', '.join(lib.get('Locations',[]))[:60]})")
    for k in risk_keys:
        if k in opt:
            v=opt[k]
            bad = (v is True and k!="EnableInternetProviders")
            print(f"     {k:42s}= {v}{'   <<< deep-read on mount' if bad else ''}")
    print(f"     MetadataRefresh: AutoRefreshIntervalDays={opt.get('AutomaticRefreshIntervalDays')}")

def arr_report(name,svc):
    print("\n"+"="*70); print(f"{name} RECURRING TASKS + RESCAN SETTING"); print("="*70)
    for t in sorted(get(svc,"/api/v3/system/task"),key=lambda x:x.get("name","")):
        iv=t.get("interval")
        print(f"  {t.get('name'):42s} every {iv} min")
    mm=get(svc,"/api/v3/config/mediamanagement")
    print(f"  -- rescanAfterRefresh = {mm.get('rescanAfterRefresh')}  (always = re-reads disk/mount on every refresh)")
    print(f"  -- enableMediaInfo    = {mm.get('enableMediaInfo')}")
arr_report("SONARR",SON)
arr_report("RADARR",RAD)
