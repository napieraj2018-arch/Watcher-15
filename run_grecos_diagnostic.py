import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from grecos_watcher import run_grecos_watcher

with open("config/watchers.json", encoding="utf-8") as fh:
    cfg = next(x for x in json.load(fh)["watchers"] if x.get("provider") == "grecos_pl")

run_grecos_watcher(cfg)
