import requests
from bs4 import BeautifulSoup

URL='https://fly.pl/szukaj-wycieczek/'
FAMILY={'filter[person]':'2','filter[child]':'2','filter[childAge][1]':'01-01-2021','filter[childAge][2]':'01-01-2019','filter[fp]':'2'}
ADULTS={'filter[person]':'2','filter[child]':'0','filter[fp]':'2'}
for label,params in [('FAMILY',FAMILY),('ADULTS',ADULTS)]:
 r=requests.get(URL,params=params,headers={'User-Agent':'Mozilla/5.0'},timeout=30)
 print('FLY_TOTAL_REQ',label,r.status_code,r.url,len(r.content))
 s=BeautifulSoup(r.text,'html.parser')
 text=' '.join(s.get_text(' ',strip=True).split())
 print('FLY_TOTAL_MODE',label,'Cena za wszystkich' in text)
 print('FLY_TOTAL_SAMPLE',label,text[text.find('Wyświetlono'):text.find('Wyświetlono')+5000])
