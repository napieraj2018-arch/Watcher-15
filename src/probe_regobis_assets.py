import re,requests
BASE="https://www.rego-bis.pl/build/assets/"
FILES=[
 "SearchParticipants-ZPHKVOTM.js","SearchBar-CTdQbhhk.js",
 "useFilters-Cy34ieIH.js","offerCardNormalizer-BpktgQfj.js",
 "publicOfferNavigationState-BhYo0_mt.js"
]
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL,pl;q=0.9"}
TERMS=["children","child","age","ages","birth","participants","adult","guest","filters","search","api","offers","rooms"]
for name in FILES:
    r=requests.get(BASE+name,headers=UA,timeout=30)
    print("REGODEEP_FILE",name,r.status_code,len(r.content))
    if r.status_code!=200:continue
    t=r.text;lo=t.lower()
    urls=sorted(set(re.findall(r'["\']([^"\']*(?:/api/|api/|/offers|/search)[^"\']*)["\']',t,re.I)))
    for u in urls[:80]:print("REGODEEP_URL",name,u[:1800])
    for term in TERMS:
        p=0;n=0
        while n<8:
            i=lo.find(term.lower(),p)
            if i<0:break
            sn=re.sub(r"\s+"," ",t[max(0,i-1200):min(len(t),i+2200)])
            print("REGODEEP_SNIP",name,term,sn[:3500])
            p=i+len(term);n+=1
