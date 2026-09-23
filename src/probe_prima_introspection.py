import json,requests
GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
Q="""query SchemaProbe {
  __schema {
    queryType { fields { name args { name type { kind name ofType { kind name ofType { kind name } } } } type { kind name ofType { kind name } } } }
  }
}"""
r=requests.post(GQL,json={"operationName":"SchemaProbe","variables":{},"query":Q},headers=H,timeout=40)
print("PRIMAINT_STATUS",r.status_code,len(r.content))
print("PRIMAINT_HEAD",r.text[:24000].replace("\n"," "))
try:
 d=r.json()
 fields=((((d.get("data") or {}).get("__schema") or {}).get("queryType") or {}).get("fields") or [])
 print("PRIMAINT_FIELD_COUNT",len(fields))
 for f in fields:
  n=(f.get("name") or "")
  if any(k in n.lower() for k in ["search","offer","trip","bluevendo","hotel","filter","departure","destination"]):
   print("PRIMAINT_FIELD",json.dumps(f,ensure_ascii=False))
except Exception as e:
 print("PRIMAINT_ERR",type(e).__name__,str(e))
