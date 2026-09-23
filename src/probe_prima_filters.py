import json,requests
GQL="https://app.primaholiday.pl/graphql"
H={"User-Agent":"Mozilla/5.0","Origin":"https://www.primaholiday.pl","Referer":"https://www.primaholiday.pl/","Content-Type":"application/json"}
Q="""query FilterProbe {
  __type(name:"Filters") {
    kind name
    inputFields { name type { kind name ofType { kind name ofType { kind name } } } }
  }
}"""
r=requests.post(GQL,json={"operationName":"FilterProbe","query":Q,"variables":{}},headers=H,timeout=40)
print("PRIMAFILTER_STATUS",r.status_code,len(r.content))
print("PRIMAFILTER_BODY",r.text[:30000].replace("\n"," "))
