import json,requests
GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
Q="""query PrimaRawSearch { bluevendoSearch bluevendoTest }"""
r=requests.post(GQL,json={"operationName":"PrimaRawSearch","variables":{},"query":Q},headers=H,timeout=40)
print("PRIMARAW_STATUS",r.status_code,len(r.content))
print("PRIMARAW_BODY",r.text[:80000].replace("\n"," "))
try:
 d=r.json()
 for name in ["bluevendoSearch","bluevendoTest"]:
  v=(d.get("data") or {}).get(name)
  print("PRIMARAW_TYPE",name,type(v).__name__)
  if isinstance(v,str):
   try:v=json.loads(v)
   except:pass
  def walk(x,path="",depth=0,count=[0]):
   if depth>10 or count[0]>350:return
   if isinstance(x,dict):
    sig={k:v for k,v in x.items() if any(q in k.lower() for q in ["token","url","api","offer","trip","price","date","airport","departure","arrival","hotel","room","meal","maint","adult","child","age","search","filter","avail"])}
    if sig:
     print("PRIMARAW_SIGNAL",name,path,json.dumps(sig,ensure_ascii=False)[:5000]);count[0]+=1
    for k,v in x.items():walk(v,f"{path}.{k}" if path else k,depth+1,count)
   elif isinstance(x,list):
    for i,v in enumerate(x[:150]):walk(v,f"{path}[{i}]",depth+1,count)
  walk(v,count=[0])
except Exception as e:print("PRIMARAW_ERR",type(e).__name__,str(e))
