import json,requests
GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
Q="""query InputSchema {
 __schema {
  types {
   kind name
   inputFields {
    name
    type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
   }
  }
 }
}"""
r=requests.post(GQL,json={"operationName":"InputSchema","variables":{},"query":Q},headers=H,timeout=40)
print("PRIMAROOM_STATUS",r.status_code,len(r.content));r.raise_for_status()
d=r.json();types=(((d.get("data") or {}).get("__schema") or {}).get("types") or [])
for t in types:
    fs=t.get("inputFields") or []
    names=[str(x.get("name") or "") for x in fs]
    blob=(" ".join([str(t.get("name") or "")]+names)).lower()
    if t.get("kind")=="INPUT_OBJECT" and any(k in blob for k in ["room","person","age","birth","trip","configuration"]):
        print("PRIMAROOM_TYPE",json.dumps(t,ensure_ascii=False))
