"""Safe, bounded display of pip-audit results. Never print descriptions or raw JSON."""
from __future__ import annotations
import json
import pathlib
import re
import sys

NAME=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
VERSION=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+!-]{0,79}$")
VULN=re.compile(r"^(?:CVE-\d{4}-\d{4,}|GHSA-[A-Za-z0-9-]+|PYSEC-[A-Za-z0-9-]+|OSV-[A-Za-z0-9._-]+)$",re.I)
MAX_REPORT_BYTES=2_000_000

def safe(value,pattern,max_len=100):
    return value if isinstance(value,str) and len(value)<=max_len and pattern.fullmatch(value) else "[redacted]"

def summarize(raw):
    if isinstance(raw,dict):
        items=raw.get("dependencies",[])
    elif isinstance(raw,list):
        items=raw
    else:
        return {"status":"invalid_report","affected_packages":0,"advisories":0,"packages":[]}
    if not isinstance(items,list):
        return {"status":"invalid_report","affected_packages":0,"advisories":0,"packages":[]}
    results=[]
    total=0
    for item in items:
        if not isinstance(item,dict):continue
        vulns=item.get("vulns",[])
        if not isinstance(vulns,list) or not vulns:continue
        total+=len(vulns)
        if len(results)>=30:continue
        ids=[]
        fixes=[]
        for vuln in vulns[:30]:
            if not isinstance(vuln,dict):continue
            identifier=safe(vuln.get("id"),VULN,100)
            ids.append(identifier)
            for version in vuln.get("fix_versions",[])[:6] if isinstance(vuln.get("fix_versions"),list) else []:
                value=safe(version,VERSION,80)
                if value not in fixes:fixes.append(value)
        results.append({
            "name":safe(item.get("name"),NAME),
            "version":safe(item.get("version"),VERSION,80),
            "advisory_ids":ids,
            "fixed_versions":fixes[:12]
        })
    return {
      "status":"vulnerabilities_found" if total else "no_known_vulnerabilities",
      "affected_packages":sum(1 for p in items if isinstance(p,dict) and isinstance(p.get("vulns"),list) and p["vulns"]),
      "advisories":total,
      "packages":results
    }

def main(path):
    try:
        p=pathlib.Path(path)
        if not p.is_file() or p.stat().st_size>MAX_REPORT_BYTES:raise ValueError()
        data=json.loads(p.read_text("utf-8"))
        output=summarize(data)
    except (OSError,ValueError,UnicodeError,TypeError):
        output={"status":"audit_report_unavailable","affected_packages":0,"advisories":0,"packages":[]}
    print("AIB_PIP_AUDIT_SUMMARY="+json.dumps(output,separators=(",",":"),ensure_ascii=True))
    return 0

if __name__=="__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv)>1 else "security/dependency-report.json"))
