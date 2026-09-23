import re,json,requests
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

BASE="https://search.anextour.com.pl/search_tour"
TZ=ZoneInfo("Europe/Warsaw")
UA={"User-Agent":"Mozilla/5.0","Accept-Language":"pl-PL,pl;q=0.9","Referer":BASE}
AIRPORTS={"2200":"Radom","1885":"Warszawa"}

def compact(s): return " ".join((s or "").split())

def params(town,family):
    today=datetime.now(TZ).date()
    p={
      "LANG":"pol","samo_action":"PRICES","TOWNFROMINC":town,
      "STATEINC":"10","TOURTYPE":"0","TOURINC":"0","PROGRAMINC":"0",
      "CHECKIN_BEG":(today+timedelta(days=1)).strftime("%Y%m%d"),
      "CHECKIN_END":(today+timedelta(days=3)).strftime("%Y%m%d"),
      "NIGHTS_FROM":"4","NIGHTS_TILL":"9","ADULT":"2","CURRENCY":"4",
      "CHILD":"2" if family else "0","TOWNS_ANY":"1","townssearch":"0","TOWNS":"",
      "STARS_ANY":"1","STARS":"","HOTELS_ANY":"1","hotelsearch":"0","HOTELS":"",
      "MEALS_ANY":"1","MEALS":"","ROOMS_ANY":"1","ROOMS":"","CHILD_IN_BED":"0",
      "FREIGHT":"0","COMFORTABLE_SEATS":"0","FILTER":"1","MOMENT_CONFIRM":"0",
      "UFILTER":"","HOTELTYPES":"","PARTITION_PRICE":"224","PRICEPAGE":"1","DYN_SEPARATE":"1"
    }
    p["AGES"]="5,7" if family else ""
    return p

def read_rows(html,town,family):
    soup=BeautifulSoup(html,"html.parser"); out={}
    for tr in soup.select("tr.price_info"):
        cls=" ".join(tr.get("class",[]))
        if "adult-2" not in cls: continue
        if family and "child-2" not in cls: continue
        checkin=tr.get("data-checkin") or ""; nights=tr.get("data-nights") or ""
        try:n=int(nights)
        except:continue
        if n<5 or n>8:continue
        if not checkin:continue
        price=tr.select_one("[data-converted-price-number]")
        if not price:continue
        raw=price.get("data-converted-price-number") or ""
        if not raw.isdigit():continue
        hotel=compact(tr.select_one("td.link-hotel").get_text(" ",strip=True) if tr.select_one("td.link-hotel") else "")
        cells=[compact(td.get_text(" ",strip=True)) for td in tr.select("td")]
        meal=next((x for x in cells if "All Inclusive" in x),"")
        if "All Inclusive" not in meal:continue
        room=next((x for x in cells if "2+2" in x),"") if family else ""
        if family and not room:continue
        av=[x.get("title") for x in tr.select(".hotel_availability") if x.get("title")]
        flights=[x.get("title") for x in tr.select(".fr_place_r,.fr_place_l") if x.get("title")]
        live=any(x in ("Dostępne","Ostatnie miejsca") for x in av) and any("Miejsca dostępne" in x for x in flights)
        if not live:continue
        key=(checkin,nights,tr.get("data-hotel") or "",tr.get("data-tour") or "",tr.get("data-room") or "",tr.get("data-meal") or "",town)
        out[key]={"key":key,"hotel":hotel,"price":int(raw),"meal":meal,"room":room,"availability":av,"flights":flights,"airport":AIRPORTS[town]}
    return out

def main():
    s=requests.Session();s.headers.update(UA);s.get(BASE,timeout=25)
    total_proofs=[]
    for town in ["2200","1885"]:
        sets={}
        for label,family in [("FAMILY",True),("ADULTS",False)]:
            r=s.get(BASE,params=params(town,family),timeout=40)
            print("ANEXDIR_STATUS",AIRPORTS[town],label,r.status_code,r.url,len(r.content))
            r.raise_for_status()
            rows=read_rows(r.text,town,family)
            sets[label]=rows
            print("ANEXDIR_ROWS",AIRPORTS[town],label,len(rows))
            for x in list(rows.values())[:6]:print("ANEXDIR_ROW",label,json.dumps(x,ensure_ascii=False))
        common=set(sets["FAMILY"]) & set(sets["ADULTS"])
        print("ANEXDIR_COMMON",AIRPORTS[town],len(common))
        for k in common:
            f,a=sets["FAMILY"][k],sets["ADULTS"][k]
            if f["price"]==a["price"]:continue
            proof=dict(f);proof["adult_total"]=a["price"];proof["delta"]=f["price"]-a["price"]
            total_proofs.append(proof)
            print("ANEXDIR_PROOF",json.dumps(proof,ensure_ascii=False))
    print("ANEXDIR_PARTY_SENSITIVE",len(total_proofs))
    print("ANEXDIR_FAMILY_TOTAL_VERIFIED",bool(total_proofs))

if __name__=="__main__":main()
