import json
from src.grecos_watcher import run_grecos_watcher

with open("config/watchers.json", encoding="utf-8") as fh:
    cfg = next(x for x in json.load(fh)["watchers"] if x.get("provider") == "grecos_pl")

run_grecos_watcher(cfg)
