from anex_watcher import _read

CFG={
  "adults":2,
  "children_ages":[5,7],
  "depart_in_days":[0,1,2,3],
  "min_nights":5,
  "max_nights":8,
  "meal_contains":"All Inclusive",
  "airports":["Warszawa - Radom","Warszawa - Modlin","Warszawa"],
  "max_total_price_pln":11000,
  "min_stars":4,
  "min_rating":8,
  "min_reviews":30,
}

rows=_read(CFG)
print("ANEX_CURRENT_COUNT",len(rows))
for x in sorted(rows,key=lambda y:y["price"]):
    print("ANEX_CURRENT",x)
