import requests
from bs4 import BeautifulSoup

URL='https://www.nekera.pl/hotels/'
params=[('adults','2'),('child','01.01.2021'),('child','01.01.2019'),('product','F')]
r=requests.get(URL,params=params,headers={'User-Agent':'Mozilla/5.0'},timeout=30)
print('NEKERA_DIRECT_STATUS',r.status_code,r.url,len(r.content))
print('NEKERA_DIRECT_CHILD_QUERY','child=01.01.2021' in r.url and 'child=01.01.2019' in r.url)
soup=BeautifulSoup(r.text,'html.parser')
for el in soup.select('input[name], select[name]'):
    name=el.get('name','')
    if any(k in name.lower() for k in ['adult','child','birth','passenger']):
        print('NEKERA_DIRECT_FIELD',name,el.get('value',''),str(el)[:900])
text=' '.join(soup.get_text(' ',strip=True).split())
for needle in ['2 doros','2 dzieci','2021','2019','Cena','zł','All Inclusive']:
    i=text.lower().find(needle.lower())
    if i>=0: print('NEKERA_DIRECT_SNIP',needle,text[max(0,i-250):i+900])
