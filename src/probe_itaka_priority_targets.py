import re,time
from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from watcher import chrome,dismiss_cookies,itaka_parse_total,page_stars,representative_dob,now_local

TARGETS=[
("Oasis Atlantico Salinas Sea","https://www.itaka.pl/wczasy/wyspy-zielonego-przyladka/sal/hotel-oasis-atlantico-salinas-sea,SIDOASS/?adults%5B0%5D=2&id%5B0%5D=CgVJdGFrYRIEVklUWBoDUExOIgdTSURPQVNTKAQ6BEwyNjBCBgiA89bVBkoGCIDo%2B9UGUAJiBQoDV0FXagUKA1NJRHIDCgExegUKA1NJRIIBBQoDV0FXigEDCgExkgEGCIDz1tUGmgEGCIDo%2B9UGogEFCgNER1aqAQMKAUHiAQkKB1Jlc2FiZWXqAQkKB1Jlc2FiZWXyAQkKB1Jlc2FiZWU%3D")
]
def family_url(url):
    parts=urlsplit(url)
    q=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if k not in ("adults[0]","children[0]")]
    today=now_local().date()
    ds=[representative_dob(5,today),representative_dob(7,today)]
    q.append(("adults[0]","2"));q.append(("children[0]",",".join(d.strftime("%d.%m.%Y") for d in ds)))
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(q,doseq=True),parts.fragment)),ds

def main():
    d=chrome()
    try:
      for name,url in TARGETS:
        u,dobs=family_url(url)
        print("ITAKATGT_OPEN",name,u)
        d.get(u);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(6);dismiss_cookies(d)
        cur=d.current_url
        body=d.find_element(By.TAG_NAME,"body").text
        source=d.page_source
        print("ITAKATGT_URL",name,cur)
        print("ITAKATGT_CHILDREN_OK",name,all(dob.strftime("%d.%m.%Y") in cur or dob.strftime("%d.%m.%Y").replace(".","%2E").lower() in cur.lower() for dob in dobs))
        total=itaka_parse_total(body)
        print("ITAKATGT_TOTAL",name,total)
        for line in [x.strip() for x in body.splitlines() if x.strip()]:
          lo=line.lower()
          if any(k in lo for k in ["25.09","warszawa","all inclusive","łącznie","razem","doros","dzieci","15:45"]):
            print("ITAKATGT_SIGNAL",name,line[:1000])
        stars=page_stars(d)
        if stars is None:
          for pat in [r'"(?:hotelCategory|category|standard|stars)"\s*:\s*"?([1-5])',r'(?:hotelCategory|hotel-category|stars?)[^0-9]{0,30}([1-5])']:
            m=re.search(pat,source,re.I)
            if m:stars=int(m.group(1));break
        rating=None;reviews=None
        m=re.search(r"(\d[.,]\d)\s*/\s*6",body)
        if m:rating=float(m.group(1).replace(",","."))/6*10
        ms=[int(x.replace(" ","")) for x in re.findall(r"(\d[\d ]{0,5})\s+opini",body,re.I) if x.strip()]
        if ms:reviews=max(ms)
        print("ITAKATGT_QUALITY",name,stars,rating,reviews)
        valid_date=("25.09.2026" in body or "25.09" in body or "2026-09-25" in source)
        valid_time=("15:45" in body or "15:45" in source)
        valid_ai=("all inclusive" in body.lower())
        print("ITAKATGT_VALID",name,{"date":valid_date,"time":valid_time,"ai":valid_ai,"total":total,"stars":stars,"rating":rating,"reviews":reviews})
    finally:d.quit()
if __name__=="__main__":main()
