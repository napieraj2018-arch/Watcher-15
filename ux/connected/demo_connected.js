/* Local-only integration demo. NEVER load this in the production login UI.
 * Only calls a same-origin synthetic backend. No account passwords or Steel.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const LABELS = Object.freeze({
  clinic: "Przychodnia", architect: "Architekt", demo: "Test"
});
const inflight = new Map();
const lastKnown = new Map();
const tip = $("page-view").querySelector(".tip");

function currentWorkspace() {
  const label=$("workspace-label").textContent.trim();
  return Object.keys(LABELS).find(x=>LABELS[x]===label) || "demo";
}

function present(workspace,label,description) {
  if (currentWorkspace() !== workspace) return;
  $("connection-label").textContent=label+" — symulator";
  if (description && tip) tip.textContent=description;
}

async function jsonRequest(route, payload) {
  const response=await fetch(route,{
    method:"POST",mode:"same-origin",credentials:"same-origin",
    cache:"no-store",redirect:"error",
    headers:{"content-type":"application/json"},
    body:JSON.stringify(payload)
  });
  if (response.status===401 || response.status===403)
    throw new Error("authorization_required");
  if (!response.ok) throw new Error("request_rejected");
  const data=await response.json();
  if (typeof data!=="object" || data===null) throw new Error("unexpected_response");
  return data;
}

async function pollJob(workspace,request_id,generation=0) {
  const queue=inflight.get(workspace);
  if(!queue || queue.request_id!==request_id || queue.generation!==generation) return;
  const route="/_demo/api/poll?workspace_id="+encodeURIComponent(workspace)
              +"&request_id="+encodeURIComponent(request_id);
  try {
    const response=await fetch(route,{mode:"same-origin",credentials:"same-origin",
      cache:"no-store",redirect:"error"});
    if(!response.ok) throw new Error("poll_unavailable");
    const data=await response.json();
    updateStatus(workspace,data);
    if(data.status==="queued" && queue.attempts++<30){
      window.setTimeout(()=>pollJob(workspace,request_id,generation),500);
    }
  } catch {
    present(workspace,"Przerwano sprawdzanie","Stan sesji jest niepewny. Nie ponawiaj automatycznie logowania.");
  }
}

function updateStatus(workspace,data){
  lastKnown.set(workspace,data);
  switch(data.status){
    case "ready":
      present(workspace,"Gotowe","To tylko fikcyjna sesja demonstracyjna. Prawdziwa witryna nie została otwarta.");
      break;
    case "queued":
      present(workspace,"W kolejce","Przeglądarka jest zajęta w innym zadaniu. Poczekaj lub zakończ tamto zadanie.");
      break;
    case "paused":
      present(workspace,"Wymaga sprawdzenia","Uruchomienie nie zostało potwierdzone. Nie ponawiam próby automatycznie.");
      break;
    case "expired":
      present(workspace,"Wygasło","Zadanie wygasło. Nowe żądanie wymaga świadomego ponowienia.");
      break;
    case "released":
      present(workspace,"Zwolniono","Sesja demonstracyjna została poprawnie zapisana i zwolniona.");
      break;
    default:
      present(workspace,"Niedostępne","Brak potwierdzenia wykonania. Nic nie zostało opublikowane.");
  }
}

window.addEventListener("aib:workspace-selected", event=>{
  const workspace=event.detail?.workspace_id;
  if(!(workspace in LABELS))return;
  if(lastKnown.has(workspace)){
    updateStatus(workspace,lastKnown.get(workspace));
  } else {
    $("connection-label").textContent="Symulator lokalny";
    if(tip)tip.textContent="Brak uruchomionej sesji tej przestrzeni. To wyłącznie test lokalny.";
  }
});

window.addEventListener("aib:navigation-intent",async (event)=>{
  const {workspace_id,url,tab_id}=event.detail || {};
  if(!(workspace_id in LABELS) || typeof url!=="string" || !url.startsWith("https://")) return;
  const request_id=crypto.randomUUID();
  const queue={request_id,generation:tab_id,attempts:0};
  inflight.set(workspace_id,queue);
  present(workspace_id,"Otwieranie","Uruchamiam fikcyjną kartę w lokalnym symulatorze...");
  try {
    const result=await jsonRequest("/_demo/api/open",{
      workspace_id,url,request_id,tab_id
    });
    updateStatus(workspace_id,result);
    if(result.status==="queued"){
      window.setTimeout(()=>pollJob(workspace_id,request_id,tab_id),500);
    }
  } catch {
    present(workspace_id,"Błąd połączenia","Nie wykonano żadnych działań na kontach ani stronach.");
  }
});

const closing=document.createElement("button");
closing.id="demo-end-task";
closing.type="button";
closing.className="menu-item";
closing.textContent="Zakończ symulowaną sesję";
closing.setAttribute("aria-label","Zakończ sesję demonstracyjną tej przestrzeni");
$("menu-sheet").insertBefore(closing,$("menu-sheet").querySelector(".sheet-footnote"));
closing.addEventListener("click",async ()=>{
  const workspace_id=currentWorkspace();
  closing.disabled=true;
  try {
    await jsonRequest("/_demo/api/close",{workspace_id});
    updateStatus(workspace_id,{status:"released"});
  } catch {
    present(workspace_id,"Nie zwolniono","Ta przestrzeń nie jest właścicielem obecnej sesji.");
  } finally{
    closing.disabled=false;
    $("close-menu").click();
  }
});

$("connection-label").textContent="Symulator lokalny";
$("active-profile-label").textContent="Brak prawdziwych kont";
if(tip) tip.textContent="To symulator. Żadne połączenie ze Steel ani zewnętrznymi witrynami nie jest wykonywane.";
