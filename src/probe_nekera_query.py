import re,requests
from bs4 import BeautifulSoup

URL='https://www.nekera.pl/hotels/'
BASE=[('adults','2'),('child','2021-01-01'),('child','2019-01-01'),('product','F')]
VARIANTS=[
    ('base',[]),
    ('priceView',[('priceView','2')]),
    ('filter_priceView',[('filter[priceView]','2')]),
    ('price_type',[('price_type','2')]),
    ('pricetype_total',[('pricetype','1')]),
    ('pricetype_person',[('pricetype','0')]),
]
HEAD={'User-Agent':'Mozilla/5.0'}
for label,extra in VARIANTS:
    r=requests.get(URL,params=BASE+extra,headers=HEAD,timeout=30)
    print('NEKERA_VARIANT',label,r.status_code,r.url,len(r.content))
    soup=BeautifulSoup(r.text,'html.parser')
    for b in soup.select('[data-to="priceView"]'):
        print('NEKERA_PRICE_BUTTON',label,b.get('data-value'),b.get('data-checked'),str(b)[:700])
    for el in soup.select('input[name]'):
        n=el.get('name','')
        if 'price' in n.lower() or 'view' in n.lower():
            parent=el.parent
            print('NEKERA_PRICE_FIELD',label,n,el.get('value',''),'checked',el.has_attr('checked'),'parent',str(parent)[:1400])
    text=' '.join(soup.get_text(' ',strip=True).split())
    for m in re.finditer(r'\b\d[\d ]{1,8}\s*zł(?:\s*/os\.)?',text,re.I):
        sn=text[max(0,m.start()-180):m.start()+420]
        if 'Athenaeum' in sn or 'Centrale' in sn or '/os.' not in m.group(0).lower():
            print('NEKERA_PRICE_SNIP',label,m.group(0),sn[:650])
            break
    print('NEKERA_HAS_EXACT_CHILDREN',label,'child=2021-01-01' in r.url and 'child=2019-01-01' in r.url)


# Control experiment: "za wszystkich" must actually depend on the two children.
# Compare the same listing blocks for exact 2+2 against 2 adults only.
def card_rows(soup):
    rows=[]
    seen=set()
    for a in soup.find_all("a"):
        label=" ".join(a.get_text(" ",strip=True).split())
        if "Szczegóły" not in label:
            continue
        node=a
        chosen=None
        for _ in range(7):
            node=node.parent
            if node is None: break
            txt=" ".join(node.get_text(" ",strip=True).split())
            if "zł" in txt and 80 <= len(txt) <= 2200:
                chosen=txt
                if len(txt) >= 140: break
        if not chosen: continue
        href=a.get("href") or ""
        # Stable human key: beginning of card text plus route path. Keep raw
        # evidence too; this is diagnostic and never used to alert.
        head=re.sub(r"\s+"," ",chosen)[:140]
        key=(href.split("?")[0], re.sub(r"\b\d[\d ]*\s*zł\b.*","",head).strip())
        if key in seen: continue
        seen.add(key)
        m=re.search(r"(?<!/)\b(\d[\d ]*)\s*zł(?!\s*/os)",chosen,re.I)
        rows.append({"key":key,"href":href,"total":int(re.sub(r"\D","",m.group(1))) if m else None,"text":chosen[:900]})
    return rows

fam=requests.get(URL,params=BASE+[("pricetype","1")],headers=HEAD,timeout=30)
adu=requests.get(URL,params=[("adults","2"),("product","F"),("pricetype","1")],headers=HEAD,timeout=30)
fam.raise_for_status(); adu.raise_for_status()
fr=card_rows(BeautifulSoup(fam.text,"html.parser"))
ar=card_rows(BeautifulSoup(adu.text,"html.parser"))
print("NEKERA_FAMILY_TOTAL_CARD_ROWS",len(fr),"ADULT_CARD_ROWS",len(ar))
amap={x["key"]:x for x in ar}
same=[];diff=[]
for x in fr:
    y=amap.get(x["key"])
    if not y or x["total"] is None or y["total"] is None: continue
    rec={"key":x["key"],"family_total":x["total"],"adults_total":y["total"],
         "family_text":x["text"][:500],"adults_text":y["text"][:500]}
    (diff if x["total"]!=y["total"] else same).append(rec)
print("NEKERA_PARTY_SENSITIVE_TOTAL_COUNT",len(diff))
for x in diff[:12]: print("NEKERA_PARTY_SENSITIVE_TOTAL",x)
print("NEKERA_SAME_AS_ADULT_TOTAL_COUNT",len(same))
for x in same[:8]: print("NEKERA_SAME_AS_ADULT_TOTAL",x)
print("NEKERA_FAMILY_TOTAL_VERIFIED",bool(diff))
