import json,re,time
from urllib.parse import urlencode
from selenium.webdriver.support.ui import WebDriverWait
from watcher import chrome,dismiss_cookies

BASE="https://www.travelplanet.pl/wakacje/"
VARIANTS=[(5,8),(6,9),(7,10),(8,11),(9,12),(10,13)]
def dates(text):
    m=re.search(r"departure:_(\d{4}-\d{2}-\d{2})_return:_(\d{4}-\d{2}-\d{2})",str(text or ""))
    if not m:return None
    from datetime import datetime
    a=datetime.strptime(m.group(1),"%Y-%m-%d").date()
    b=datetime.strptime(m.group(2),"%Y-%m-%d").date()
    return (b-a).days
def main():
    d=chrome()
    try:
        for lo,hi in VARIANTS:
            q=[
              ("s_action","SEARCH_FORM_SEPARATED"),("d_start_from","25.09.2026"),("d_end_to","27.09.2026"),
              ("nl_transportation_id[]","3"),("b_online_sale_customer","1"),
              ("duration",f"{lo}-{hi} days"),("nl_length_from",str(lo)),("nl_length_to",str(hi)),
              ("nl_occupancy_adults","2"),("sort","nl_sell"),("nl_occupancy_children","2"),
              ("nl_ages_children[]","5"),("nl_ages_children[]","7")
            ]
            u=BASE+"?"+urlencode(q,doseq=True)
            d.get(u);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");dismiss_cookies(d);time.sleep(3)
            raw=d.execute_script("return localStorage.getItem('ga4_serp_items_last')||''")
            filt=d.execute_script("return localStorage.getItem('ga4_serp_filters_last')||''")
            try: vals=list((json.loads(raw).get("itemsById") or {}).values())
            except: vals=[]
            counts={}
            w=[]
            for x in vals:
                n=dates(x.get("item_parameter_7"))
                if n is not None:counts[n]=counts.get(n,0)+1
                if str(x.get("item_parameter_3") or "").upper() in ("WAW","WMI","RDO"):
                    w.append((x.get("item_name"),n,x.get("item_parameter_5"),x.get("item_parameter_1"),x.get("item_parameter_8")))
            print("TP_DURATION_MATRIX",lo,hi,"FINAL",d.current_url,"FILTERS",filt[:900],"COUNTS",counts,"WARSAW",w[:12])
    finally:d.quit()
if __name__=="__main__":main()
