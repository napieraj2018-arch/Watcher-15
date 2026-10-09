/* AI Browser mobile chrome prototype — no backend, credentials, storage or network actions.
 * This file intentionally does not load real websites. Production integration
 * requires a same-origin authenticated BFF, tenant-scoped profiles and leases.
 */
"use strict";

const MAX_TABS = 12;
const WORKSPACES = Object.freeze([
  {id:"clinic",label:"Przychodnia",subtitle:"Osobne karty przychodni",monogram:"P"},
  {id:"architect",label:"Architekt",subtitle:"Osobne karty biura projektowego",monogram:"A"},
  {id:"demo",label:"Test",subtitle:"Środowisko bez kont",monogram:"T"}
]);
let nextTabId = 1;
function newTab() {
  return {id:nextTabId++, history:[""],position:0};
}
const stacks = new Map(WORKSPACES.map(w=>[w.id,{tabs:[newTab()],activeIndex:0}]));
const state = {workspace:"clinic",openSheet:null,priorFocus:null};
const el = id => document.getElementById(id);
const activeStack = () => stacks.get(state.workspace);
const activeTab = () => activeStack().tabs[activeStack().activeIndex];

function requireHttpsAddress(raw) {
  if (typeof raw !== "string" || !raw.trim() || raw.length > 1024) return null;
  const text=raw.trim();
  if (/[\x00-\x1f\x7f\\]/.test(text)) return null;
  if (/^\w[\w+.-]*:/.test(text) && !/^https:\/\//i.test(text)) return null;
  let guess;
  if (/^https:\/\//i.test(text)) {
    guess=text;
  } else if (/^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/|$)/i.test(text)) {
    guess="https://"+text;
  } else if (text.includes("://") || text.includes("@")) {
    return null;
  } else {
    guess="https://www.google.com/search?q="+encodeURIComponent(text);
  }
  try {
    const parsed=new URL(guess);
    if (parsed.protocol!=="https:" || !parsed.hostname || parsed.username || parsed.password) return null;
    if (parsed.hostname==="localhost" || parsed.hostname.endsWith(".localhost")
        || parsed.hostname.endsWith(".local") || parsed.hostname.endsWith(".internal")
        || parsed.hostname.endsWith(".invalid")) return null;
    if (/^\[?[\d.:]+\]?$/.test(parsed.hostname)) return null;
    // No top-level navigation occurs in the demo: addresses stay in memory only.
    return parsed.href;
  } catch {
    return null;
  }
}

function titleFor(url) {
  if (!url) return "Nowa karta";
  try {return new URL(url).hostname.replace(/^www\./,"");}
  catch {return "Karta";}
}
function writeText(node,value) {node.textContent=String(value);}
function icon(name) {
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("class","icon");svg.setAttribute("aria-hidden","true");
  const use=document.createElementNS("http://www.w3.org/2000/svg","use");
  use.setAttribute("href","#i-"+name);svg.append(use);return svg;
}
let toastTimer;
function inform(message) {
  writeText(el("announcements"),message);
  const toast=el("toast");
  writeText(toast,message);
  toast.hidden=false;
  window.clearTimeout(toastTimer);
  toastTimer=window.setTimeout(()=>{toast.hidden=true;},3400);
}
function updateBrowser() {
  const tab=activeTab();
  const current=tab.history[tab.position] || "";
  const isHome=!current;
  el("welcome").hidden=!isHome;
  el("page-view").hidden=isHome;
  el("address").value=current ? titleFor(current) : "";
  el("go-back").disabled=tab.position===0;
  el("go-forward").disabled=tab.position===tab.history.length-1;
  writeText(el("tab-count"),activeStack().tabs.length);
  const workspace=WORKSPACES.find(w=>w.id===state.workspace);
  writeText(el("workspace-label"),workspace.label);
  writeText(el("active-profile-label"),"Przestrzeń: "+workspace.label);
  if (!isHome) {
    writeText(el("page-title"),titleFor(current));
    writeText(el("page-domain"),current);
  }
  document.title=(isHome?"AI Browser":titleFor(current)+" — AI Browser")+" (prototyp)";
}
function pushPage(url) {
  const tab=activeTab();
  tab.history=tab.history.slice(0,tab.position+1);
  tab.history.push(url);
  tab.position=tab.history.length-1;
  updateBrowser();
  el("viewport").scrollTop=0;
  // A trusted same-origin BFF may listen for this intent. In the standalone
  // prototype there is no listener and no network activity.
  if (url) {
    window.dispatchEvent(new CustomEvent("aib:navigation-intent", {
      detail: {workspace_id: state.workspace, tab_id: tab.id, url}
    }));
  }
}
function navigate(input) {
  const url=requireHttpsAddress(input);
  if (!url) {
    inform("Wpisz poprawny adres HTTPS lub szukaną frazę.");
    return false;
  }
  pushPage(url);
  inform("Adres zapisany w karcie. To prototyp, bez połączenia ze stroną.");
  return true;
}
function home() {pushPage("");}
function step(delta) {
  const tab=activeTab();
  const target=tab.position+delta;
  if(target<0 || target>=tab.history.length)return;
  tab.position=target;
  updateBrowser();
}
function createTab() {
  const stack=activeStack();
  if(stack.tabs.length>=MAX_TABS) {inform("Limit demonstracyjny: 12 kart.");return false;}
  stack.tabs.push(newTab());
  stack.activeIndex=stack.tabs.length-1;
  updateBrowser();
  return true;
}
function removeTab(id) {
  const stack=activeStack();
  const index=stack.tabs.findIndex(t=>t.id===id);
  if(index<0)return;
  stack.tabs.splice(index,1);
  if(stack.tabs.length===0){stack.tabs=[newTab()];stack.activeIndex=0;}
  else if(stack.activeIndex>=index && stack.activeIndex>0)stack.activeIndex--;
  updateBrowser();
  buildTabList();
}

function buildTabList() {
  const holder=el("tab-items");holder.replaceChildren();
  activeStack().tabs.forEach((tab,index)=>{
    const row=document.createElement("div");row.className="tab-entry";row.setAttribute("role","listitem");
    const select=document.createElement("button");select.type="button";select.className="tab-select";
    if(index===activeStack().activeIndex){select.classList.add("active");select.setAttribute("aria-current","page");}
    select.setAttribute("aria-label","Przejdź do karty "+(index+1));
    const mini=document.createElement("span");mini.className="tab-miniature";mini.append(icon("globe"));
    const copy=document.createElement("span");copy.className="tab-copy";
    const title=document.createElement("span");title.className="tab-name";
    const address=document.createElement("span");address.className="tab-domain";
    const url=tab.history[tab.position]||"";
    writeText(title,titleFor(url));writeText(address,url||"Strona startowa");
    copy.append(title,address);select.append(mini,copy);
    select.addEventListener("click",()=>{activeStack().activeIndex=index;updateBrowser();closeSheet();});
    const close=document.createElement("button");close.type="button";close.className="tab-close";
    close.setAttribute("aria-label","Zamknij kartę "+(index+1));close.append(icon("close"));
    close.addEventListener("click",()=>removeTab(tab.id));
    row.append(select,close);holder.append(row);
  });
}
function buildWorkspaceList() {
  const holder=el("workspace-items");holder.replaceChildren();
  for(const workspace of WORKSPACES){
    const row=document.createElement("button");
    row.type="button";row.className="workspace-entry";
    row.setAttribute("aria-pressed",String(workspace.id===state.workspace));
    const avatar=document.createElement("span");avatar.className="workspace-avatar";
    writeText(avatar,workspace.monogram);
    const details=document.createElement("span");details.className="workspace-details";
    const label=document.createElement("span");label.className="workspace-title";
    const sub=document.createElement("span");sub.className="workspace-caption";
    writeText(label,workspace.label);writeText(sub,workspace.subtitle);
    details.append(label,sub);row.append(avatar,details);
    if(workspace.id===state.workspace){const check=document.createElement("span");check.className="workspace-check";check.append(icon("check"));row.append(check);}
    row.addEventListener("click",()=>{
      state.workspace=workspace.id;
      updateBrowser();closeSheet();inform("Przełączono przestrzeń: "+workspace.label);
      window.dispatchEvent(new CustomEvent("aib:workspace-selected", {
        detail: {workspace_id:workspace.id}
      }));
    });
    holder.append(row);
  }
}

const SHEETS={tabs:"tabs-sheet",workspace:"workspace-sheet",menu:"menu-sheet"};
function openSheet(name,source) {
  if(state.openSheet===name){closeSheet();return;}
  closeSheet(false);
  state.openSheet=name;state.priorFocus=source||document.activeElement;
  if(name==="tabs")buildTabList();
  if(name==="workspace")buildWorkspaceList();
  el(SHEETS[name]).hidden=false;el("overlay").hidden=false;
  el("open-tabs").setAttribute("aria-expanded",String(name==="tabs"));
  el("open-menu").setAttribute("aria-expanded",String(name==="menu"));
  el("workspace-switch").setAttribute("aria-expanded",String(name==="workspace"));
  el(SHEETS[name]).querySelector("button")?.focus();
}
function closeSheet(restoreFocus=true){
  for(const id of Object.values(SHEETS))el(id).hidden=true;
  el("overlay").hidden=true;
  el("open-tabs").setAttribute("aria-expanded","false");
  el("open-menu").setAttribute("aria-expanded","false");
  el("workspace-switch").setAttribute("aria-expanded","false");
  const previous=state.priorFocus;state.openSheet=null;state.priorFocus=null;
  if(restoreFocus && previous?.isConnected)previous.focus();
}
function trapFocus(e){
  if(!state.openSheet || e.key!=="Tab")return;
  const dialog=el(SHEETS[state.openSheet]);
  const controls=[...dialog.querySelectorAll("button:not(:disabled)")];
  if(!controls.length)return;
  const current=document.activeElement;
  const at=controls.indexOf(current);
  if(e.shiftKey && (at<=0)){e.preventDefault();controls[controls.length-1].focus();}
  else if(!e.shiftKey && at===controls.length-1){e.preventDefault();controls[0].focus();}
}

el("go-back").addEventListener("click",()=>step(-1));
el("go-forward").addEventListener("click",()=>step(1));
el("page-home").addEventListener("click",home);
el("address-form").addEventListener("submit",e=>{
  e.preventDefault();
  const input=el("address").value;
  navigate(input);
  el("address").blur();
});
el("address").addEventListener("focus",()=>{
  const tab=activeTab();
  el("address").value=tab.history[tab.position] || "";
  el("address").select();
});
el("address").addEventListener("blur",()=>{
  if(!el("address").value.trim())updateBrowser();
});
el("quick-grid").addEventListener("click",e=>{
  const target=e.target.closest("button[data-destination]");
  if(target && el("quick-grid").contains(target))navigate(target.dataset.destination);
});
el("open-tabs").addEventListener("click",e=>openSheet("tabs",e.currentTarget));
el("open-menu").addEventListener("click",e=>openSheet("menu",e.currentTarget));
el("workspace-switch").addEventListener("click",e=>openSheet("workspace",e.currentTarget));
el("close-tabs").addEventListener("click",()=>closeSheet());
el("close-menu").addEventListener("click",()=>closeSheet());
el("close-workspaces").addEventListener("click",()=>closeSheet());
el("overlay").addEventListener("click",()=>closeSheet());
el("new-tab").addEventListener("click",()=>{if(createTab()){closeSheet();el("address").focus();}});
el("reload-page").addEventListener("click",()=>{closeSheet();inform("Podgląd nie pobiera prawdziwej strony.");});
el("menu-home").addEventListener("click",()=>{closeSheet();home();});
document.addEventListener("keydown",e=>{
  if(e.key==="Escape" && state.openSheet){e.preventDefault();closeSheet();return;}
  trapFocus(e);
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="l"){
    e.preventDefault();closeSheet(false);el("address").focus();return;
  }
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="t"){
    e.preventDefault();if(createTab()){closeSheet(false);el("address").focus();}
  }
});
updateBrowser();
