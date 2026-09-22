import json, sys, time
from pathlib import Path
from urllib.parse import urlparse

import requests

REG=Path("config/channels.json")
TIMEOUT=18

def main():
    data=json.loads(REG.read_text(encoding="utf-8"))
    rows=[]
    for ch in data["channels"]:
        url=ch["url"]
        started=time.time()
        try:
            r=requests.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=True,
                headers={
                    "User-Agent":"Mozilla/5.0 (Watcher-15 health check; compatible browser)",
                    "Accept-Language":"pl-PL,pl;q=0.9,en;q=0.7",
                },
            )
            elapsed=round(time.time()-started,2)
            text=(r.text or "")[:300000].lower()
            plausible=(
                r.status_code < 500
                and len(text) > 500
                and any(k in text for k in ["wakac","last minute","all inclusive","hotel","wyciecz"])
            )
            row={
                "id":ch["id"],"name":ch["name"],"configured_status":ch["status"],
                "http":r.status_code,"seconds":elapsed,"final_url":r.url,
                "reachable":bool(plausible),
            }
        except Exception as e:
            row={
                "id":ch["id"],"name":ch["name"],"configured_status":ch["status"],
                "http":None,"seconds":round(time.time()-started,2),
                "final_url":url,"reachable":False,
                "error":f"{type(e).__name__}: {str(e)[:180]}",
            }
        rows.append(row)
        print("CHANNEL_HEALTH",json.dumps(row,ensure_ascii=False))

    ok=sum(1 for r in rows if r["reachable"])
    print(f"CHANNEL_HEALTH_SUMMARY {ok}/{len(rows)} reachable")
    Path("channel-health.json").write_text(
        json.dumps({"checked":rows,"reachable":ok,"total":len(rows)},ensure_ascii=False,indent=2),
        encoding="utf-8",
    )
    # Health failures must not kill the entire system; individual adapters remain isolated.
    return 0

if __name__=="__main__":
    raise SystemExit(main())
