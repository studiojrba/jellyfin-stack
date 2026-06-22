#!/usr/bin/env python3
import json, urllib.request

def get(url):
    with urllib.request.urlopen(url, timeout=30) as x:
        return json.load(x)

print("=== SABnzbd queue (decypharr) ===")
try:
    d = get("http://localhost:8282/sabnzbd/api?mode=queue&output=json")
    q = d.get("queue", {})
    print("status:", q.get("status"), "| slots:", len(q.get("slots", [])))
    for s in q.get("slots", [])[:10]:
        print(f"  {s.get('status'):12s} {s.get('percentage','?'):>4}% {s.get('filename','')[:45]}")
except Exception as e:
    print("ERR:", str(e)[:120])

print("\n=== SABnzbd history (completed) ===")
try:
    d = get("http://localhost:8282/sabnzbd/api?mode=history&output=json&limit=20")
    slots = d.get("history", {}).get("slots", [])
    print("history items:", len(slots))
    from collections import Counter
    c = Counter(s.get("status") for s in slots)
    print("status breakdown:", dict(c))
    for s in slots[:10]:
        print(f"  {s.get('status'):10s} cat={s.get('category','?'):10s} {s.get('name','')[:42]}")
        if s.get("fail_message"):
            print(f"      fail: {s.get('fail_message')[:70]}")
except Exception as e:
    print("ERR:", str(e)[:120])
