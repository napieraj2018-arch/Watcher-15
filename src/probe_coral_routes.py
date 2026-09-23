import re,requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE="https://booking.coraltravel.pl/"
UA={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL,pl;q=0.9"}

def compact(s): return re.sub(r"\s+"," ",s or "").strip()

def main():
    r=requests.get(BASE,headers=UA,timeout=35)
    print("CORALROUTE_HOME",r.status_code,len(r.content),r.url)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    scripts=[urljoin(r.url,s.get("src")) for s in soup.find_all("script",src=True)]
    target=next((u for u in scripts if "/Assets/js/Site" in u),None)
    print("CORALROUTE_SITE",target or "")
    if not target: raise SystemExit("FAIL_CLOSED: Site bundle missing")
    b=requests.get(target,headers=UA,timeout=45)
    print("CORALROUTE_BUNDLE",b.status_code,len(b.content),b.headers.get("content-type"))
    b.raise_for_status()
    t=b.text

    # Collect only route-like literals and ajax/fetch contexts. This intentionally
    # excludes generic UI text and data URIs.
    lits=set()
    for m in re.finditer(r'["\']([^"\']{2,300})["\']',t):
        v=m.group(1)
        lv=v.lower()
        if v.startswith("data:"): continue
        if (v.startswith("/") or "coraltravel.pl" in lv) and any(k in lv for k in [
            "hotel","search","price","availability","avail","offer","book","reservation",
            "pax","passenger","child","age","room","flight","tour","package","api"
        ]):
            lits.add(v)
    for v in sorted(lits):
        print("CORALROUTE_LITERAL",v)

    patterns=[
      r'url\s*:\s*["\']([^"\']+)["\']',
      r'\.ajax\s*\(\s*\{[^{}]{0,1500}?url\s*:\s*["\']([^"\']+)["\']',
      r'\.get(?:JSON)?\s*\(\s*["\']([^"\']+)["\']',
      r'\.post\s*\(\s*["\']([^"\']+)["\']',
      r'fetch\s*\(\s*["\']([^"\']+)["\']'
    ]
    found=set()
    for p in patterns:
        for m in re.finditer(p,t,re.I|re.S):
            v=m.group(1)
            lv=v.lower()
            if any(k in lv for k in ["hotel","search","price","avail","offer","book","room","pax","child","flight","tour","api"]):
                found.add(v)
    for v in sorted(found):
        print("CORALROUTE_AJAX",v)

    # Focused snippets around likely route/action identifiers.
    terms=[
      "HotelSearch","SearchHotel","HotelResult","HotelList","GetHotel","RoomSearch",
      "SearchResult","SearchRoom","Pax","ChildAge","Passenger","TotalPrice",
      "CheckPrice","Availability","GetPrice","SearchHotels"
    ]
    lo=t.lower()
    for term in terms:
        p=0;n=0
        while n<6:
            i=lo.find(term.lower(),p)
            if i<0:break
            sn=compact(t[max(0,i-700):min(len(t),i+1800)])
            # only emit useful contexts containing an HTTP/AJAX clue
            if any(x in sn.lower() for x in ["url:", "$.ajax", "$.get", "$.post", "/hotel", "/search", "action"]):
                print("CORALROUTE_CONTEXT",term,sn[:3600])
                n+=1
            p=i+len(term)

if __name__=="__main__":main()
