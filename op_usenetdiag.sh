#!/usr/bin/env bash
echo "=== 1) decypharr usenet config ==="
python3 -c "
import json
c=json.load(open('/home/jrbaprz/torbox-stack/config/decypharr/config.json'))
u=c.get('usenet',{}) if isinstance(c.get('usenet'),dict) else {}
print('  usenet block:', json.dumps(u, indent=2)[:600])
" 2>/dev/null || grep -iE 'usenet|processing_timeout|max_connections|nzb' /home/jrbaprz/torbox-stack/config/decypharr/config.json

echo
echo "=== 2) decypharr logs for a STUCK item (Django / Forrest / Casino) ==="
docker logs --since 48h decypharr 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -iE 'django|forrest.gump|casino.1995|wolf.of.wall' | tail -15
echo "  (if empty: these were processed before the 48h log window)"

echo
echo "=== 3) does a stuck movie's file physically exist + readable in mount? ==="
for pat in "Django" "Forrest" "Casino" "Wolf.of.Wall" "Dune.Part"; do
  f=$(docker exec jellyfin sh -c "find /data/media/movies -iname \"*${pat}*\" 2>/dev/null | head -1")
  if [ -n "$f" ]; then
    echo "  FOUND in library: $f"
  else
    echo "  not in /data/media/movies: $pat"
  fi
done

echo
echo "=== 4) check decypharr mount for the raw symlink targets ==="
docker exec decypharr sh -c 'ls -la /mnt/remote/torbox/ 2>/dev/null | head -8; echo "..."; ls /mnt/remote/ 2>/dev/null'

echo
echo "=== 5) SAB queue: show nzo_ids + paths of first 3 stuck items ==="
curl -s --max-time 10 'http://localhost:8282/sabnzbd/api?mode=queue&output=json' | python3 -c "
import json,sys
q=json.load(sys.stdin).get('queue',{})
for s in q.get('slots',[])[:3]:
    print('  nzo_id=%s status=%s mb=%s mbleft=%s filename=%s'%(s.get('nzo_id'),s.get('status'),s.get('mb'),s.get('mbleft'),(s.get('filename') or '')[:40]))
"
