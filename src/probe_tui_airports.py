import time,re
from urllib.parse import quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from watcher import chrome,dismiss_cookies

DOB1="25.08.2021"; DOB2="25.08.2019"
for code in ["WAW","WMI","RDO"]:
    q=(
      ":price:byPlane:T:additionalType:GT03%23TUZ-LAST25"
      f":a:{code}:dF:5:dT:8:startDate:24.09.2026:endDate:27.09.2026"
      f":ctAdult:2:ctChild:2:birthDate:{DOB1}:birthDate:{DOB2}"
      f":room:2-{DOB1}-{DOB2}:minHotelCategory:defaultHotelCategory"
      ":tripAdvisorRating:defaultTripAdvisorRating:beach_distance:defaultBeachDistance"
      ":flightDuration:defaultFlightDuration:tripType:WS"
    )
    url="https://www.tui.pl/last-minute-z-warszawy?q="+quote(q,safe="")+"&fullPrice=false"
    d=chrome()
    try:
        d.get(url);WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete");time.sleep(5);dismiss_cookies(d)
        tiles=d.find_elements(By.CSS_SELECTOR,"[data-testid='offer-tile']")
        print("TUIAIR",code,"FINAL",d.current_url,"COUNT",len(tiles))
        for t in tiles[:8]:
            try:
                txt=" ".join((t.text or "").split())
                if "All Inclusive" in txt:
                    print("TUIAIR_TILE",code,txt[:1400])
            except:pass
    finally:d.quit()
