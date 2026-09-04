const API_URL="http://127.0.0.1:8000";
const state={backendOnline:false,health:null,dashboard:null,workers:[],events:[],products:[],activeView:"overview"};
const viewMeta={overview:"Overview",offers:"Products & Offers",opportunities:"Opportunities",audience:"Audience",content:"Content Assets",distribution:"Distribution",attribution:"Attribution",commissions:"Commissions & Payouts",performance:"Economic Performance",recommendations:"Recommendations",approvals:"Approval Queue",experiments:"Experiments",agents:"AI Agents",activity:"Activity"};

async function api(endpoint,options={}){
  try{
    const response=await fetch(`${API_URL}${endpoint}`,{cache:"no-store",...options});
    if(!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  }catch(error){console.error(`API error ${endpoint}:`,error);return null;}
}
function esc(v){return String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;")}
function toast(message){const el=document.getElementById("toast");el.textContent=message;el.classList.add("show");clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove("show"),2400)}
function setBackendStatus(online){
  state.backendOnline=online;
  ["sidebar-dot","top-dot"].forEach(id=>{const el=document.getElementById(id);el.classList.toggle("online",online);el.classList.toggle("offline",!online)});
  document.getElementById("sidebar-status").textContent=online?"Backend online":"Backend offline";
  document.getElementById("connection-text").textContent=online?"Live backend":"Disconnected";
}
function normalizeProducts(data){if(Array.isArray(data))return data;if(Array.isArray(data?.items))return data.items;if(Array.isArray(data?.products))return data.products;return []}
function statusClass(status){const s=String(status||"").toUpperCase();return s==="ONLINE"?"status-online":s==="BUSY"?"status-busy":"status-offline"}
function eventClass(type){const t=String(type||"INFO").toUpperCase();return t==="SUCCESS"?"success":(t==="ERROR"||t==="FAILED")?"error":(t==="WARNING"||t==="WARN")?"warning":""}
function time(value){if(!value)return"--:--";const d=new Date(value);return Number.isNaN(d.getTime())?"--:--":d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}

async function refreshData({silent=false}={}){
  const [health,dashboard,workers,events,products]=await Promise.all([
    api("/health"),api("/system/dashboard"),api("/system/workers"),api("/system/events"),api("/products/")
  ]);
  state.health=health;state.dashboard=dashboard;state.workers=Array.isArray(workers)?workers:[];state.events=Array.isArray(events)?events:[];state.products=normalizeProducts(products);
  setBackendStatus(Boolean(health?.success));
  document.getElementById("sidebar-version").textContent=health?.success?"FastAPI connected":"127.0.0.1:8000";
  render();
  if(!silent)toast(health?.success?"Live data refreshed.":"Backend is not reachable.");
}
function kpi(label,value,meta){return `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="meta">${esc(meta)}</div></div>`}
function workers(limit=6){
  const list=state.workers.slice(0,limit);
  if(!list.length)return `<div class="empty">${state.backendOnline?"No workers returned by runtime.":"Backend unavailable."}</div>`;
  return `<div class="worker-list">${list.map(w=>`<div class="worker-row"><div class="worker-left"><span class="dot ${String(w.status).toUpperCase()==="ONLINE"?"online":""}"></span><div><span class="worker-name">${esc(w.name||"Unnamed worker")}</span><span class="sub">${esc(w.worker_type||"AI worker")}</span></div></div><span class="status-pill ${statusClass(w.status)}">${esc(w.status||"UNKNOWN")}</span></div>`).join("")}</div>`;
}
function events(limit=7){
  const list=[...state.events].slice(-limit).reverse();
  if(!list.length)return `<div class="empty">No runtime events yet.</div>`;
  return `<div class="event-list">${list.map(e=>`<div class="event-row"><div class="event-left"><span class="event-dot ${eventClass(e.type)}"></span><span class="event-message">${esc(e.event||"Event")}</span></div><span class="event-time">${esc(time(e.timestamp))}</span></div>`).join("")}</div>`;
}
function overview(){
  const d=state.dashboard||{};const wc=state.workers.length||Number(d.workers||0);const running=Number(d.running_missions||0);const success=Number(d.success_rate??100);
  return `<div class="hero"><div><h3>Affiliate operations at a glance</h3><p>Live runtime data is shown where an API exists. Frozen optimization capabilities without an API are clearly marked instead of being faked.</p></div><span class="live-badge">${state.backendOnline?"● LIVE BACKEND":"● BACKEND OFFLINE"}</span></div>
  <div class="grid kpi-grid">${kpi("Products & Offers",state.products.length,state.products.length?"Loaded from /products/":"No products returned")}${kpi("AI Workers",wc,state.backendOnline?"Live runtime registry":"Backend unavailable")}${kpi("Running Missions",running,"Runtime mission activity")}${kpi("Success Rate",`${success}%`,"Backend authoritative")}</div>
  <div class="grid two-col">
    <section class="card"><div class="card-head"><div><h4>AI Workforce</h4><p>Registered operational workers</p></div><span class="state-badge">${wc} registered</span></div><div class="card-body">${workers()}</div></section>
    <section class="card"><div class="card-head"><div><h4>Optimization Pipeline</h4><p>Frozen through M11A10</p></div><span class="state-badge">DESIGN ONLY</span></div><div class="card-body"><div class="pipeline"><span class="stage frozen">Economic truth</span><span>→</span><span class="stage frozen">Preference</span><span>→</span><span class="stage frozen">Recommendation</span><span>→</span><span class="stage frozen">Approval</span><span>→</span><span class="stage frozen">Experiment design</span></div><div class="callout" style="margin-top:14px">M11A10 can describe an experiment, but cannot allocate money, assign traffic, schedule execution, or launch anything.</div></div></section>
    <section class="card"><div class="card-head"><div><h4>Recent Activity</h4><p>Live system events</p></div><button class="secondary" data-action="activity">View all</button></div><div class="card-body">${events()}</div></section>
    <section class="card"><div class="card-head"><div><h4>Operator Attention</h4><p>Human-visible boundaries</p></div></div><div class="card-body"><div class="mini-list"><div class="mini-row"><span>Recommendation API surface</span><span class="state-badge">Pending</span></div><div class="mini-row"><span>Approval API surface</span><span class="state-badge">Pending</span></div><div class="mini-row"><span>Experiment design API surface</span><span class="state-badge">Pending</span></div></div></div></section>
  </div>`;
}
function offers(){
  const p=state.products;
  return `<div class="section-stack"><div><h3 class="section-title">Products & Offers</h3><p class="section-copy">Live products from the existing FastAPI products endpoint.</p></div><section class="card"><div class="card-body table-wrap">${p.length?`<table class="data-table"><thead><tr><th>Name</th><th>Category</th><th>Program</th><th>Score</th><th>Status</th></tr></thead><tbody>${p.map(x=>`<tr><td>${esc(x.name||"—")}</td><td>${esc(x.category||"—")}</td><td>${esc(x.affiliate_program||x.affiliate_network||"—")}</td><td>${esc(x.affiliate_score??x.opportunity_score??"—")}</td><td>${esc(x.status||"—")}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">No products returned. The screen is wired and ready for live product records.</div>`}</div></section></div>`;
}
function pending(title,copy,frozen=false){return `<div class="section-stack"><div><h3 class="section-title">${esc(title)}</h3><p class="section-copy">${esc(copy)}</p></div><section class="card"><div class="card-body"><div class="callout">${frozen?"Backend service is frozen and qualified, but this UI intentionally waits for a dedicated API surface before showing operational controls.":"UI shell is ready. This capability will be wired when its backend read model/API is exposed."}</div></div></section></div>`}
function approvals(){return `<div class="section-stack"><div><h3 class="section-title">Approval Queue</h3><p class="section-copy">M11A9 is the explicit external approval boundary.</p></div><section class="card"><div class="card-head"><div><h4>Governance controls</h4><p>No fake approvals are shown.</p></div><span class="state-badge">M11A9 FROZEN</span></div><div class="card-body"><div class="callout">Approve / Reject / Defer controls will appear only after the frozen M11A9 service has a proper API endpoint. Approval will still not equal execution.</div></div></section></div>`}
function experiments(){return `<div class="section-stack"><div><h3 class="section-title">Experiments</h3><p class="section-copy">Read-only experiment design from frozen M11A10.</p></div><section class="card"><div class="card-head"><div><h4>Experiment Design</h4><p>Hypothesis, control, treatment, success measure, observation window</p></div><span class="state-badge">DESIGN ONLY</span></div><div class="card-body"><div class="callout">There is deliberately no Launch button. M11A10 has no execution, traffic, budget, scheduling, or platform authority.</div></div></section></div>`}
function agents(){return `<div class="section-stack"><div><h3 class="section-title">AI Agents</h3><p class="section-copy">Live workforce plus existing discovery mission controls.</p></div><section class="card"><div class="card-head"><div><h4>Runtime Workers</h4><p>Shared workforce registry</p></div><span class="state-badge">${state.workers.length} workers</span></div><div class="card-body">${workers(30)}</div></section><section class="card"><div class="card-head"><div><h4>Mission Controls</h4><p>Existing system commands</p></div></div><div class="card-body"><div class="toolbar"><button class="primary" data-action="product-discovery">Launch Product Discovery</button><button class="secondary" data-action="affiliate-discovery">Launch Affiliate Discovery</button></div></div></section></div>`}
function activity(){return `<div class="section-stack"><div><h3 class="section-title">Activity</h3><p class="section-copy">Latest runtime events from /system/events.</p></div><section class="card"><div class="card-body">${events(50)}</div></section></div>`}

const renderers={
  overview,offers,
  opportunities:()=>pending("Opportunities","Opportunity intelligence and scoring views."),
  audience:()=>pending("Audience","Audience intelligence, signals, profiles and qualification."),
  content:()=>pending("Content Assets","Research briefs, generated content, evaluations and repurposed assets."),
  distribution:()=>pending("Distribution","Prepared content, distribution runs and delivery status."),
  attribution:()=>pending("Attribution","Content → click → conversion → commission → payout → profit lineage.",true),
  commissions:()=>pending("Commissions & Payouts","Revenue settlement and payout visibility.",true),
  performance:()=>pending("Economic Performance","Revenue-rooted operating-profit and optimization evidence.",true),
  recommendations:()=>pending("Recommendations","M11A8 Tier-1 economic recommendation proposals.",true),
  approvals,experiments,agents,activity
};
function render(){document.getElementById("page-title").textContent=viewMeta[state.activeView]||"Overview";document.getElementById("view-container").innerHTML=(renderers[state.activeView]||overview)();bindActions()}
function activate(view){state.activeView=view;document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));document.getElementById("sidebar").classList.remove("open");render()}
async function postCommand(endpoint,label){toast(`${label} requested…`);const r=await api(endpoint,{method:"POST"});toast(r?.message||`${label} failed. Check FastAPI console.`);if(r)await refreshData({silent:true})}
function bindActions(){document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{const a=b.dataset.action;if(a==="activity")activate("activity");if(a==="product-discovery")await postCommand("/system/command/run-product-discovery","Product discovery");if(a==="affiliate-discovery")await postCommand("/system/command/run-affiliate","Affiliate discovery")})}
document.addEventListener("DOMContentLoaded",()=>{
  document.querySelectorAll(".nav-item").forEach(b=>b.onclick=()=>activate(b.dataset.view));
  document.getElementById("refresh-button").onclick=()=>refreshData();
  document.getElementById("menu-button").onclick=()=>document.getElementById("sidebar").classList.toggle("open");
  refreshData({silent:true});
  setInterval(()=>refreshData({silent:true}),8000);
});
