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
