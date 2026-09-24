import json, requests

API="https://bestreisengroup.pl/api/bv"
H={
    "User-Agent":"Mozilla/5.0",
    "Accept":"application/json,text/plain,*/*",
    "Content-Type":"application/json",
    "Referer":"https://bestreisengroup.pl/",
}
TRIPS=[
    {"tripid":"789655183","departureid":"2039282","arrivalid":"2039283"},
    {"tripid":"789655187","departureid":"2039326","arrivalid":"2039327"},
    {"tripid":"789655192","departureid":"2039328","arrivalid":"2039305"},
]

def call(label, persons):
    payload={
        "method":"fast-calculation",
        "params":{
            "trips":{"trip":TRIPS},
            "persons":[{"person":persons}],
        },
    }
    r=requests.post(API,json=payload,headers=H,timeout=50)
    print("BESTFAST_STATUS",label,r.status_code,len(r.content))
    print("BESTFAST_BODY",label,r.text[:12000].replace("\n"," "))
    r.raise_for_status()
    return r.json()

def main():
    adults=[
        {"age":"30","birthdate":"1996-01-01"},
        {"age":"30","birthdate":"1996-01-01"},
    ]
    family=adults+[
        {"age":"5","birthdate":"2021-08-24"},
        {"age":"7","birthdate":"2019-08-24"},
    ]
    a=call("ADULTS",adults)
    f=call("FAMILY",family)
    print("BESTFAST_REQUEST_FAMILY",json.dumps(family))
    print("BESTFAST_DIFFERENT",json.dumps(a,sort_keys=True)!=json.dumps(f,sort_keys=True))

if __name__=="__main__":
    main()
