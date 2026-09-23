import re, json, requests
from urllib.parse import urlencode

URL="https://www.travelplanet.pl/wakacje/"
HEAD={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL"}
BASE=[
 ("s_action","SEARCH_FORM_SEPARATED"),
 ("d_start_from","24.09.2026"),("d_end_to","26.09.2026"),
 ("nl_transportation_id[]","3"),("b_online_sale_customer","1"),
 ("duration","5-8 days"),("nl_length_from","5"),("nl_length_to","8"),
 ("nl_occupancy_adults","2"),("sort","nl_sell")
]
VARIANTS=[
 ("array", [("nl_occupancy_children","2"),("nl_ages_children[]","5"),("nl_ages_children[]","7")]),
 ("repeat", [("nl_occupancy_children","2"),("nl_ages_children","5"),("nl_ages_children","7")]),
 ("comma", [("nl_occupancy_children","2"),("nl_ages_children","5,7")]),
 ("dash", [("nl_occupancy_children","2"),("nl_ages_children","5-7")]),
 ("json", [("nl_occupancy_children","2"),("nl_ages_children",'[5,7]')]),
]
ADULTS=BASE+[("nl_occupancy_children","0")]

def compact(s): return " ".join((s or "").split())

def probe(label,params):
    r=requests.get(URL,params=params,headers=HEAD,timeout=35,allow_redirects=True)
    text=r.text
    print("TP_DIRECT_STATUS",label,r.status_code,r.url,len(r.content),r.headers.get("content-type"))
    pats={
      "adult2_child2":len(re.findall(r"adult:_?2_child:_?2",text,re.I)),
      "adult2_child0":len(re.findall(r"adult:_?2_child:_?0",text,re.I)),
      "occup_children":text.lower().count("nl_occupancy_children"),
      "ages_children":text.lower().count("nl_ages_children"),
      "age_5_7":sum(x in text for x in ["5,7","5%2C7","5-7"]),
    }
    print("TP_DIRECT_SIGNALS",label,json.dumps(pats,ensure_ascii=False))
    for term in ["nl_occupancy_children","nl_ages_children","adult:_2_child:_2","adult:_2_child:_0","participants"]:
        low=text.lower(); t=term.lower(); pos=0
        for _ in range(3):
            i=low.find(t,pos)
            if i<0: break
            print("TP_DIRECT_SNIP",label,term,compact(text[max(0,i-450):min(len(text),i+1100)])[:1900])
            pos=i+len(t)
    return r.url,pats

for label,extra in VARIANTS:
    probe(label,BASE+extra)
probe("adults_only",ADULTS)
