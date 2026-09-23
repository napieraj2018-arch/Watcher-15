import json,time,requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

HOME="https://www.primaholiday.pl/"
GQL="https://app.primaholiday.pl/graphql"
QUERY="""query BluevendoFastCalculation($persons: [PersonsGroupInput!]!, $trips: [TripInput!]!) {
  bluevendoFastCalculation(persons: $persons, trips: $trips) {
    trips { price tripId persons { totalPrice __typename } lowestPrice __typename }
    __typename
  }
}"""

def collect_live_trips(d):
    trips=[];seen=set()
    for row in d.get_log("performance"):
        try:
            m=json.loads(row["message"])["message"]
            if m.get("method")!="Network.requestWillBeSent": continue
            req=m["params"]["request"]
            if req.get("url")!=GQL: continue
            raw=req.get("postData") or ""
            if "BluevendoFastCalculation" not in raw: continue
            p=json.loads(raw)
            for t in (p.get("variables") or {}).get("trips") or []:
                key=(t.get("tripid"),t.get("departureid"),t.get("arrivalid"))
                if key in seen or key[0] is None: continue
                seen.add(key);trips.append(t)
        except Exception:
            pass
    return trips

def post(sess,headers,trips,ages,label):
    payload={"operationName":"BluevendoFastCalculation",
      "variables":{"persons":[{"person":[{"age":a} for a in ages]}],"trips":trips},
      "query":QUERY}
    r=sess.post(GQL,json=payload,headers=headers,timeout=40)
    print("PRIMAGQL_STATUS",label,r.status_code,len(r.content))
    r.raise_for_status()
    data=r.json()
    rows=(((data.get("data") or {}).get("bluevendoFastCalculation") or {}).get("trips") or [])
    out={}
    for x in rows:
        tid=str(x.get("tripId"))
        ps=x.get("persons") or []
        totals=[p.get("totalPrice") for p in ps if isinstance(p,dict)]
        rec={"tripId":tid,"price":x.get("price"),"lowestPrice":x.get("lowestPrice"),"personTotals":totals}
        out[tid]=rec
        print("PRIMAGQL_ROW",label,json.dumps(rec,ensure_ascii=False))
    return out

def main():
    o=Options()
    for a in ["--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1440,3000","--lang=pl-PL"]:
        o.add_argument(a)
    o.set_capability("goog:loggingPrefs",{"performance":"ALL"})
    d=webdriver.Chrome(options=o)
    try:
        d.get(HOME);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(9)
        trips=collect_live_trips(d)[:20]
        print("PRIMAGQL_TRIP_COUNT",len(trips))
        print("PRIMAGQL_TRIPS",json.dumps(trips,ensure_ascii=False)[:7000])
        if not trips:
            print("PRIMAGQL_FAIL_NO_LIVE_TRIPS");return
        sess=requests.Session()
        for c in d.get_cookies(): sess.cookies.set(c["name"],c["value"])
        headers={"User-Agent":d.execute_script("return navigator.userAgent"),"Referer":HOME,
                 "Origin":"https://www.primaholiday.pl","Content-Type":"application/json"}
        fam=post(sess,headers,trips,[18,18,5,7],"FAMILY")
        ad=post(sess,headers,trips,[18,18],"ADULTS")
        proofs=[]
        for tid in set(fam)&set(ad):
            f,a=fam[tid],ad[tid]
            # totalPrice is explicit Bluevendo party total; require a positive
            # difference from the same trip priced for two adults.
            try:
                family_parts=[float(v) for v in f["personTotals"]]
                adult_parts=[float(v) for v in a["personTotals"]]
                family_price=float(f["price"])
                adult_price=float(a["price"])
            except (TypeError,ValueError):
                continue
            if len(family_parts)!=4 or len(adult_parts)!=2:
                print("PRIMAGQL_REJECT_PART_COUNT",tid,len(family_parts),len(adult_parts))
                continue
            family_total=round(sum(family_parts),2)
            adult_total=round(sum(adult_parts),2)
            if abs(family_total-family_price)>.01 or abs(adult_total-adult_price)>.01:
                print("PRIMAGQL_REJECT_SUM_MISMATCH",tid,family_total,family_price,adult_total,adult_price)
                continue
            if family_total>adult_total>0:
                rec={"tripId":tid,"family_total":family_total,"adults_total":adult_total,
                     "delta":round(family_total-adult_total,2),
                     "family_person_totals":family_parts,"adult_person_totals":adult_parts,
                     "family_price":family_price,"adult_price":adult_price}
                proofs.append(rec);print("PRIMAGQL_PROOF",json.dumps(rec,ensure_ascii=False))
        print("PRIMAGQL_PARTY_SENSITIVE",len(proofs))
        print("PRIMAGQL_EXACT_PARTY",[18,18,5,7])
        print("PRIMAGQL_FAMILY_TOTAL_VERIFIED",bool(proofs))
    finally:
        d.quit()

if __name__=="__main__":main()
