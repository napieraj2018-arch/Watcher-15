import re,requests
from urllib.parse import quote
BASE="https://www.eccoholiday.com"
H={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/153 Safari/537.36","Accept-Language":"pl-PL,pl;q=0.9"}
FAMILY="/l,,,2026-09-24,,,,2,5;7,,,samolot,,,,,1,,,,,,,,,,,,,,,,,,samolotem"
ADULTS="/l,,,2026-09-24,,,,2,,,,samolot,,,,,1,,,,,,,,,,,,,,,,,,samolotem"
def norm(s):return " ".join(re.sub(r"<[^>]+>"," ",s or "").replace("&nbsp;"," ").split())
def fetch(label,path):
 r=requests.get(BASE+path,headers=H,timeout=45)
 print("ECCOCTRL_STATUS",label,r.status_code,len(r.content),r.url)
 r.raise_for_status()
 t=r.text
 # Total-price mode is server-visible through priceTotal=1; collect card-ish fragments.
 for token in ["priceTotal","zł/razem","Dzieci :","5 lat","7 lat","Dostępność","offerId","extOfferId"]:
  print("ECCOCTRL_SIGNAL",label,token,t.lower().find(token.lower()))
 # Extract surrounding fragments around zł/razem and common offer identifiers.
 rows=[]
 for m in re.finditer(r"([0-9][0-9 .]{2,})\s*zł\s*/\s*razem",t,re.I):
  frag=t[max(0,m.start()-7000):m.end()+2500]
  txt=norm(frag)
  price=int(re.sub(r"\D","",m.group(1)))
  ids=re.findall(r'(?:offerId|offer-id|data-offer|extOfferId)[^0-9A-Za-z]{0,20}([0-9A-Za-z_-]{2,})',frag,re.I)
  hotel=""
  # page uses hotel names in links/headings; keep text fragment for diagnostics
  rows.append({"price":price,"ids":ids[:6],"text":txt[-2200:]})
 print("ECCOCTRL_ROWS",label,len(rows))
 for x in rows[:20]:print("ECCOCTRL_ROW",label,x)
 return rows,t
def main():
 # Generate canonical URLs via the site's own serializer so priceTotal=1 is not guessed.
 s=requests.Session();s.headers.update(H)
 import json
 def canon(label,children):
  p={"resultsPerPage":"","resultsPageNumber":"","adults":"2","transport":["samolot"],"length":["5","6","7","8"],"departureDateFrom":"2026-09-24","departureDateTo":"2026-09-26","countryRegion":[],"departureFrom":[],"extraType":"samolotem","returnDateTo":"","dateDepFromRetTo":["",""],"category":["4","5"],"children":children,"feeding":["all inclusive"],"price":[],"attributes":[],"tourOperator":[],"offerType":[],"offerCatalog":"","priceTotal":"1"}
  u=BASE+"/index.php?module=bp/search/searchParamsToUrl&mode=ajax&linkType=getSearchLink&searchParams="+quote(json.dumps(p,separators=(",",":")))
  r=s.get(u,timeout=30);print("ECCOCTRL_CANON",label,r.status_code,r.text[:3000])
  return r
 canon("FAMILY",["5","7"]);canon("ADULTS",[])
 fr,ft=fetch("FAMILY",FAMILY)
 ar,at=fetch("ADULTS",ADULTS)
 # This probe deliberately does not certify unless stable same-offer identifiers can be paired.
 print("ECCOCTRL_FAMILY_TOTAL_SURFACE",bool(fr))
 print("ECCOCTRL_ADULT_TOTAL_SURFACE",bool(ar))
if __name__=="__main__":main()
