import json,time,re
from urllib.parse import urlencode,urlsplit,parse_qs
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

BASE="https://www.travelplanet.pl/wakacje/"
COMMON=[
 ("b_online_sale_customer","1"),("d_start_from","24.09.2026"),("d_end_to","26.09.2026"),
 ("duration","5-8 days"),("nl_length_from","5"),("nl_length_to","8"),
 ("nl_transportation_id[]","3"),("nl_occupancy_adults","2"),
 ("s_action","SEARCH_FORM_SEPARATED"),("sort","nl_sell")
]
VARIANTS=[
 ("array",[("nl_occupancy_children","2"),("nl_ages_children[]","5"),("nl_ages_children[]","7")]),
 ("repeat",[("nl_occupancy_children","2"),("nl_ages_children","5"),("nl_ages_children","7")]),
 ("comma",[("nl_occupancy_children","2"),("nl_ages_children","5,7")]),
]
def store(d,kind,key):
    try:return d.execute_script("return window."+kind+".getItem(arguments[0])",key) or ""
    except:return ""
def main():
    o=Options();o.add_argument("--headless=new");o.add_argument("--no-sandbox");o.add_argument("--disable-dev-shm-usage");o.add_argument("--window-size=1440,3000");o.add_argument("--lang=pl-PL")
    d=webdriver.Chrome(options=o)
    try:
      for label,extra in VARIANTS:
        u=BASE+"?"+urlencode(COMMON+extra,doseq=True)
        d.get(u);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(7)
        print("TP_NATIVE_VARIANT",label,d.current_url)
        print("TP_NATIVE_QS",label,json.dumps(parse_qs(urlsplit(d.current_url).query),ensure_ascii=False,sort_keys=True))
        filt=store(d,"localStorage","ga4_serp_filters_last")
        items=store(d,"localStorage","ga4_serp_items_last")
        occ=store(d,"sessionStorage","searchPreferencesOccupancy")
        print("TP_NATIVE_OCCUPANCY",label,occ)
        print("TP_NATIVE_FILTERS",label,filt[:2500])
        kid2=len(re.findall(r'adult:_?2_child:_?2',items,re.I));kid0=len(re.findall(r'adult:_?2_child:_?0',items,re.I))
        print("TP_NATIVE_ITEM_COUNTS",label,{"child2":kid2,"child0":kid0,"items_len":len(items)})
        try:
            data=json.loads(items); vals=list((data.get("itemsById") or {}).values())
            for x in vals[:12]:
                print("TP_NATIVE_ITEM",label,{"id":x.get("item_id"),"price":x.get("item_parameter_1"),"party":x.get("item_parameter_9"),"airport":x.get("item_parameter_3"),"stay":x.get("item_parameter_7"),"meal":x.get("item_parameter_8")})
        except Exception as e: print("TP_NATIVE_ITEMS_PARSE_ERR",label,type(e).__name__)
        ok=('"kids":"2"' in filt or '"kids":2' in filt or kid2>0)
        print("TP_NATIVE_EXACT_FAMILY_ACCEPTED",label,ok)
    finally:d.quit()
if __name__=="__main__":main()
