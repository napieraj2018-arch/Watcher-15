import json, os, re, time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

REG=Path("config/channels.json")

def compact(s):
    return " ".join((s or "").split())

def main():
    cid=os.environ["CHANNEL_ID"]
    data=json.loads(REG.read_text(encoding="utf-8"))
    ch=next(x for x in data["channels"] if x["id"]==cid)

    opts=Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,2800")
    opts.add_argument("--lang=pl-PL")
    opts.set_capability("acceptInsecureCerts", True)

    d=webdriver.Chrome(options=opts)
    report={"id":cid,"name":ch["name"],"url":ch["url"],"configured_status":ch["status"]}
    try:
        d.get(ch["url"])
        WebDriverWait(d,45).until(lambda x:x.execute_script("return document.readyState")=="complete")
        time.sleep(4)

        for t in ["Nie zezwalaj","Akceptuję","Akceptuj","Zgadzam się","Zaakceptuj wszystkie","Zezwól na wszystkie","OK"]:
            try:
                els=d.find_elements(By.XPATH,f"//button[contains(normalize-space(.),'{t}')]")
                if els and els[0].is_displayed():
                    els[0].click(); time.sleep(.6); break
            except Exception:
                pass

        # Open likely search/filter/participant control if available.
        opened=[]
        for needle in ["Uczest", "Ile osób", "2 doros", "Filtry"]:
            try:
                els=d.find_elements(
                    By.XPATH,
                    f"//*[self::button or @role='button'][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{needle.lower()}')]"
                )
                for el in els:
                    if el.is_displayed():
                        d.execute_script("arguments[0].click();",el)
                        opened.append(compact(el.text)[:120])
                        time.sleep(.8)
                        raise StopIteration
            except StopIteration:
                break
            except Exception:
                pass

        inputs=[]
        for el in d.find_elements(By.TAG_NAME,"input"):
            try:
                if el.is_displayed():
                    inputs.append({
                        "name":el.get_attribute("name"),
                        "type":el.get_attribute("type"),
                        "placeholder":el.get_attribute("placeholder"),
                        "aria":el.get_attribute("aria-label"),
                        "value":el.get_attribute("value"),
                        "testid":el.get_attribute("data-testid"),
                        "id":el.get_attribute("id"),
                    })
            except Exception:
                pass

        buttons=[]
        for el in d.find_elements(By.TAG_NAME,"button"):
            try:
                if el.is_displayed():
                    txt=compact(el.text); aria=compact(el.get_attribute("aria-label"))
                    if txt or aria:
                        buttons.append({
                            "text":txt[:180],"aria":aria[:180],
                            "testid":el.get_attribute("data-testid"),
                            "id":el.get_attribute("id")
                        })
            except Exception:
                pass

        body=compact(d.find_element(By.TAG_NAME,"body").text)
        low=body.lower()
        links=[]
        for a in d.find_elements(By.TAG_NAME,"a"):
            try:
                href=a.get_attribute("href") or ""
                txt=compact(a.text)
                if href and txt and any(k in (txt+" "+href).lower() for k in ["hotel","ofert","wakac","last","wypoczy"]):
                    links.append({"text":txt[:180],"href":href[:500]})
                    if len(links)>=80: break
            except Exception:
                pass

        interesting_buttons=[
            x for x in buttons
            if any(k in ((x.get("text") or "")+" "+(x.get("aria") or "")).lower()
                   for k in ["doros","dzie","uczest","osób","osoby","szuk","filtr","wylot","data","cena","pokój","pokoje","dalej","wybierz"])
        ][:40]
        interesting_inputs=[
            x for x in inputs
            if any(k in (" ".join(str(v or "") for v in x.values())).lower()
                   for k in ["adult","child","dzie","doros","person","participant","date","wiek","age","price","cena","room","pok"])
        ][:40]

        report.update({
            "title":d.title,
            "final_url":d.current_url,
            "opened":opened,
            "inputs":inputs[:100],
            "buttons":buttons[:180],
            "links":links,
            "signals":{
                "participant_terms":any(k in low for k in ["uczestnik","dorosł","dzieci","ile osób"]),
                "all_inclusive":("all inclusive" in low),
                "price_terms":("zł" in low or "cena" in low),
                "airport_warsaw":("warszaw" in low),
                "airport_radom":("radom" in low),
                "last_minute":("last minute" in low),
            },
            "body_sample":body[:12000],
            "ok":True,
        })
        d.save_screenshot(f"diagnostic-{cid}.png")
    except Exception as e:
        report.update({"ok":False,"error":f"{type(e).__name__}: {str(e)[:500]}","final_url":d.current_url})
    finally:
        d.quit()

    Path(f"diagnostic-{cid}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("CHANNEL_DIAGNOSTIC",json.dumps({
        "id":cid,"ok":report.get("ok"),"title":report.get("title"),
        "final_url":report.get("final_url"),"signals":report.get("signals"),
        "inputs":len(report.get("inputs",[])),"buttons":len(report.get("buttons",[])),
        "links":len(report.get("links",[])),"error":report.get("error")
    },ensure_ascii=False))
    print("CHANNEL_DIAGNOSTIC_DETAIL",json.dumps({
        "id":cid,
        "opened":report.get("opened",[]),
        "inputs":interesting_inputs if report.get("ok") else [],
        "buttons":interesting_buttons if report.get("ok") else [],
        "sample_links":report.get("links",[])[:12] if report.get("ok") else [],
    },ensure_ascii=False))

if __name__=="__main__":
    main()
