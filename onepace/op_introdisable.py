#!/usr/bin/env python3
P="/cfg/plugins/configurations/IntroSkipper.xml"
s=open(P,encoding="utf-8").read()
changed=[]
for old,new in [
    ("<AutoDetectIntros>true</AutoDetectIntros>","<AutoDetectIntros>false</AutoDetectIntros>"),
    ("<AutoDetectCredits>true</AutoDetectCredits>","<AutoDetectCredits>false</AutoDetectCredits>"),
]:
    if old in s:
        s=s.replace(old,new); changed.append(old.split('>')[0][1:])
open(P,"w",encoding="utf-8").write(s)
print("disabled auto-analysis fields:", changed or "none found (check field names)")
# show current relevant lines
for line in open(P,encoding="utf-8"):
    if "AutoDetect" in line: print("  ", line.strip())
