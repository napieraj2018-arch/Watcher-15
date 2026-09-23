import re,time,json
from datetime import datetime
from urllib.parse import urlencode,urlsplit,parse_qs
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from watcher import chrome,dismiss_cookies,representative_dob,now_local,itaka_parse_total,page_stars

BASE="https://www.itaka.pl/wyniki-wyszukiwania/wakacje/fuerteventura/"
TARGETS={"24.09.2026","25.09.2026","26.09.2026"}
THU="24.09.2026"
THU_NOT_BEFORE="17:00"

def family_url():
    today=now_local().date()
    ds=[representative_dob(5,today),representative_dob(7,today)]
    q={"adults[0]":"2","children[0]":",".join(d.strftime("%d.%m.%Y") for d in ds)}
    return BASE+"?"+urlencode(q),ds

def compact(s):return " ".join((s or "").split())

def parse_time(txt):
    m=re.search(r"(?:Warszawa(?:-Okęcie|-Modlin|-Radom)?|Radom)[^\d]{0,100}([0-2]?\d:[0-5]\d)",txt,re.I)
    return m.group(1) if m else None

def main():
    url,dobs=family_url();d=chrome()
    try:
        print("ITAKAFUE_START",url)
        d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);dismiss_cookies(d)
        cur=d.current_url.lower()
        if "children%5b0%5d" not in cur and "children[0]" not in cur:
            print("ITAKAFUE_FAIL_CHILD_PARAMS");return
        last=-1;stable=0
        for _ in range(30):
            tiles=d.find_elements(By.CSS_SELECTOR,"[data-testid='offer-list-item']")
            n=len(tiles)
            stable=stable+1 if n==last else 0
            last=n
            print("ITAKAFUE_TILE_COUNT",n)
            # click load-more controls when present, else scroll
            clicked=False
            for b in d.find_elements(By.XPATH,"//button|//a"):
                try:
                    if not b.is_displayed():continue
                    txt=compact(b.text).lower()
                    if any(k in txt for k in ["pokaż więcej","więcej ofert","załaduj więcej"]):
                        d.execute_script("arguments[0].click()",b);time.sleep(2);clicked=True;break
                except:pass
            if not clicked:
                d.execute_script("window.scrollTo(0, document.body.scrollHeight);");time.sleep(1)
            if stable>=4:break
        rows=[]
        for tile in d.find_elements(By.CSS_SELECTOR,"[data-testid='offer-list-item']"):
            try:
                txt=compact(tile.text)
                if "all inclusive" not in txt.lower():continue
                if not any(x[:5] in txt for x in TARGETS):continue
                md=re.search(r"(\d{2}\.\d{2})\s*-\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*\((\d+)\s+dni",txt,re.I)
                if not md:continue
                dep=md.group(1)+".2026"
                if dep not in TARGETS:continue
                nights=max(1,int(md.group(3))-1)
                if not 5<=nights<=8:continue
                a=tile.find_element(By.CSS_SELECTOR,"a[href*='/wczasy/']")
                href=a.get_attribute("href") or ""
                hotel=compact(a.get_attribute("title"))
                if not hotel:
                    hotel=urlsplit(href).path.rstrip("/").split("/")[-1].split(",")[0].replace("-"," ").title()
                mr=re.search(r"(\d[.,]\d)\s*/\s*6",txt)
                rating=(float(mr.group(1).replace(",","."))/6*10) if mr else None
                rv=[int(x.replace(" ","")) for x in re.findall(r"(\d[\d ]{0,5})\s+opini",txt,re.I) if x.strip()]
                reviews=max(rv) if rv else None
                pp=None
                mp=re.search(r"([0-9][0-9 ]{2,})\s*zł\s*/\s*os",txt,re.I)
                if mp:pp=int(mp.group(1).replace(" ",""))
                dep_time=parse_time(txt)
                rows.append({"hotel":hotel,"departure":dep,"departure_time":dep_time,"nights":nights,"rating":rating,"reviews":reviews,"listing_pp":pp,"href":href,"text":txt[:2200]})
            except Exception as e:print("ITAKAFUE_TILE_ERR",type(e).__name__,str(e)[:160])
        print("ITAKAFUE_CANDIDATES",len(rows))
        for r in rows:
            print("ITAKAFUE_CANDIDATE",json.dumps(r,ensure_ascii=False))
            d.get(r["href"]);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(4);dismiss_cookies(d)
            body=d.find_element(By.TAG_NAME,"body").text;source=d.page_source;current=d.current_url.lower()
            child_ok=("children%5b0%5d" in current or "children[0]" in current) and all(x.strftime("%d.%m.%Y").lower() in current for x in dobs)
            dep_ok=(r["departure"] in body or r["departure"] in source or r["departure"][:5] in body)
            ai="all inclusive" in body.lower()
            total=itaka_parse_total(body)
            stars=page_stars(d)
            if stars is None:
                for pat in [r'"(?:hotelCategory|category|standard|stars)"\s*:\s*"?([1-5])',r'(?:hotelCategory|hotel-category|stars?)[^0-9]{0,30}([1-5])']:
                    mm=re.search(pat,source,re.I)
                    if mm:stars=int(mm.group(1));break
            tm=r["departure_time"] or parse_time(body)
            time_ok=True
            if r["departure"]==THU:
                time_ok=bool(tm and tuple(map(int,tm.split(":")))>=tuple(map(int,THU_NOT_BEFORE.split(":"))))
            proof={"hotel":r["hotel"],"departure":r["departure"],"departure_time":tm,"nights":r["nights"],"child_ok":child_ok,"departure_ok":dep_ok,"time_ok":time_ok,"ai":ai,"total":total,"stars":stars,"rating":r["rating"],"reviews":r["reviews"],"href":d.current_url}
            print("ITAKAFUE_PROOF",json.dumps(proof,ensure_ascii=False))
            d.back();time.sleep(2)
        print("ITAKAFUE_DONE")
    finally:d.quit()

if __name__=="__main__":main()
