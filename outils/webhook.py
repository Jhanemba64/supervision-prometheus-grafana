"""Résume les notifications reçues par alert-receiver.
Usage : docker compose logs -t --no-log-prefix alert-receiver | python outils/webhook.py"""
import json, sys
from datetime import datetime

for line in sys.stdin:
    ts, _, rest = line.partition(" ")
    rest = rest.strip()
    if not rest.startswith('"body":'):
        continue
    body = json.loads(json.loads(rest[len('"body":'):].rstrip(",")))
    heure = datetime.fromisoformat(ts[:19] + "+00:00").astimezone().strftime("%H:%M:%S")
    for a in body["alerts"]:
        print(f'{heure}  {a["status"].upper():<8} {a["labels"]["alertname"]:<23} {a["annotations"].get("summary", "")}')
