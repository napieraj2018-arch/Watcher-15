import json
from pathlib import Path

from sunfun_watcher import run_sunfun_watcher


def main():
    watchers=json.loads(Path('config/watchers.json').read_text(encoding='utf-8'))['watchers']
    cfg=next(x for x in watchers if x.get('provider')=='sunfun_pl' and x.get('enabled'))
    run_sunfun_watcher(cfg)


if __name__=='__main__':
    main()
