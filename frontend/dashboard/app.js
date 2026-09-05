const state={
  auth:{status:"checking",authority:null,expiresAt:null,csrfToken:null,error:null},
  backendOnline:false,
  health:null,
  dashboard:null,
  workers:[],
  events:[],
  products:[],
  opportunities:{
    status:"idle",
    runs:[],
    error:null,
    selectedRunId:null,
    detailStatus:"idle",
    candidates:[],
    ranking:[],
    selected:[],
    evidence:{},
    evidenceStatus:{}
  },
  audience:{status:"idle",profiles:[],signals:[],qualifications:[],segments:[],segmentRevisions:[],memberships:[],error:null},
  attribution:{status:"idle",publications:[],contexts:[],clicks:[],facts:[],earningLinks:[],settlementLinks:[],error:null},
  performance:{status:"idle",rows:[],error:null},
  contentOps:{status:"idle",briefs:[],generationRuns:[],artifacts:[],evaluations:[],repurposingRuns:[],error:null},
  distribution:{status:"idle",queue:[],error:null},
  commissions:{
    earningsStatus:"idle",
    payoutsStatus:"idle",
    earnings:[],
    payouts:[]
  },
  activeView:"overview",
  recommendations:{status:"idle",rows:[],error:null,request:null},
  approvals:{
    status:"idle",
    outcome:null,
    error:null,
    request:null,
    form:{
      decisionState:"",
      selected:[],
      actorReference:"",
      decisionReference:"",
      decidedAt:"",
      policyVersion:""
    }
  },
  experiments:{
    status:"idle",
    rows:[],
    error:null,
    form:{
      policyVersion:"",
      selected:[],
      designs:{}
    }
  }
};
const viewMeta={overview:"Overview",offers:"Products & Offers",opportunities:"Opportunities",audience:"Audience",content:"Content Assets",distribution:"Distribution",attribution:"Attribution",commissions:"Commissions & Payouts",performance:"Economic Performance",recommendations:"Recommendations",approvals:"Approval Queue",experiments:"Experiments",agents:"AI Agents",activity:"Activity"};

function clearProtectedData(){
  state.backendOnline=false;state.health=null;state.dashboard=null;state.workers=[];state.events=[];state.products=[];
  state.opportunities={status:"idle",runs:[],error:null,selectedRunId:null,detailStatus:"idle",candidates:[],ranking:[],selected:[],evidence:{},evidenceStatus:{}};
  state.audience={status:"idle",profiles:[],signals:[],qualifications:[],segments:[],segmentRevisions:[],memberships:[],error:null};
  state.attribution={status:"idle",publications:[],contexts:[],clicks:[],facts:[],earningLinks:[],settlementLinks:[],error:null};
  state.performance={status:"idle",rows:[],error:null};state.contentOps={status:"idle",briefs:[],generationRuns:[],artifacts:[],evaluations:[],repurposingRuns:[],error:null};
  state.distribution={status:"idle",queue:[],error:null};state.commissions={earningsStatus:"idle",payoutsStatus:"idle",earnings:[],payouts:[]};
  state.recommendations={status:"idle",rows:[],error:null,request:null};
  state.approvals={status:"idle",outcome:null,error:null,request:null,form:{decisionState:"",selected:[],actorReference:"",decisionReference:"",decidedAt:"",policyVersion:""}};
  state.experiments=emptyExperimentState();
}
function clearAuth(message=null){state.auth={status:"anonymous",authority:null,expiresAt:null,csrfToken:null,error:message};clearProtectedData();renderAuthState()}
function sessionPayloadIsValid(payload){return Boolean(payload&&payload.authenticated===true&&payload.authority==="OPERATOR"&&typeof payload.csrf_token==="string"&&payload.csrf_token&&typeof payload.expires_at==="string"&&payload.expires_at)}
function renderAuthState(){
  const gate=document.getElementById("auth-gate");const shell=document.getElementById("app-shell");
  if(state.auth.status==="authenticated"){
    gate.hidden=true;shell.hidden=false;
    document.getElementById("session-expiry").textContent=`Expires ${time(state.auth.expiresAt)}`;
    return;
  }
  shell.hidden=true;gate.hidden=false;
  if(state.auth.status==="checking"){gate.innerHTML=`<div class="auth-card"><div class="spinner"></div><h2>Checking operator session…</h2><p>Secured console access is being verified.</p></div>`;return}
  gate.innerHTML=`<div class="auth-card"><div class="brand-mark">ETM</div><p class="eyebrow">ETM AFFILIATE OS</p><h1>Operator Console</h1><p>Sign in with your operator credential to access the secured console.</p>${state.auth.error?`<div class="auth-error">${esc(state.auth.error)}</div>`:""}<form id="login-form" class="login-form"><label class="field"><span>Operator credential</span><input id="operator-credential" type="password" autocomplete="off" spellcheck="false" required></label><button class="primary" id="login-button" type="submit">Sign in</button></form></div>`;
  document.getElementById("login-form").onsubmit=login;
}
async function requestApi(endpoint,options={}){
  if(state.auth.status!=="authenticated")return null;
  const method=(options.method||"GET").toUpperCase();const headers=new Headers(options.headers||{});
  if(["POST","PUT","PATCH","DELETE"].includes(method)){
    if(!state.auth.csrfToken){clearAuth("Your operator session has expired. Sign in again.");return null}
    headers.set("X-CSRF-Token",state.auth.csrfToken);
  }
  try{
    const response=await fetch(endpoint,{...options,headers,credentials:"same-origin",cache:"no-store"});
    if(response.status===401){clearAuth("Your operator session has expired. Sign in again.");return response}
    if(response.status===403)toast("Your operator session is not authorized for that action.");
    return response;
  }catch(_error){return null}
}
async function api(endpoint,options={}){
  const response=await requestApi(endpoint,options);
  if(!response||!response.ok)return null;
  return response.json().catch(()=>null);
}
async function bootstrapSession(){
  state.auth={status:"checking",authority:null,expiresAt:null,csrfToken:null,error:null};renderAuthState();
  try{
    const response=await fetch("/operator/session",{credentials:"same-origin",cache:"no-store"});
    if(response.status===200){const payload=await response.json().catch(()=>null);if(sessionPayloadIsValid(payload)){state.auth={status:"authenticated",authority:"OPERATOR",expiresAt:payload.expires_at,csrfToken:payload.csrf_token,error:null};renderAuthState();await refreshData({silent:true});return}}
  }catch(_error){}
  clearAuth(null);
}
async function login(event){
  event.preventDefault();const input=document.getElementById("operator-credential");const button=document.getElementById("login-button");const credential=input?.value||"";
  if(!credential)return;
  button.disabled=true;button.textContent="Signing in…";state.auth.error=null;document.querySelector(".auth-error")?.remove();
  let response=null;
  try{response=await fetch("/operator/session/login",{method:"POST",headers:{Authorization:`Bearer ${credential}`},credentials:"same-origin",cache:"no-store"})}catch(_error){}finally{if(input)input.value=""}
  if(response?.status===200){const payload=await response.json().catch(()=>null);if(sessionPayloadIsValid(payload)){state.auth={status:"authenticated",authority:"OPERATOR",expiresAt:payload.expires_at,csrfToken:payload.csrf_token,error:null};renderAuthState();await refreshData();return}}
  clearAuth(response?.status===403?"Credential is not authorized for the operator console.":"Invalid operator credential.");
}
async function logout(){
  const csrfToken=state.auth.csrfToken;
  try{await fetch("/operator/session/logout",{method:"POST",headers:{"X-CSRF-Token":csrfToken||""},credentials:"same-origin",cache:"no-store"})}catch(_error){}
  clearAuth(null);
}
function esc(v){return String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;")}
function toast(message){const el=document.getElementById("toast");el.textContent=message;el.classList.add("show");clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove("show"),2400)}
function setBackendStatus(online){state.backendOnline=online;["sidebar-dot","top-dot"].forEach(id=>{const el=document.getElementById(id);el.classList.toggle("online",online);el.classList.toggle("offline",!online)});document.getElementById("sidebar-status").textContent=online?"Backend online":"Backend offline";document.getElementById("connection-text").textContent=online?"Live backend":"Disconnected"}
function normalizeProducts(data){if(Array.isArray(data))return data;if(Array.isArray(data?.items))return data.items;if(Array.isArray(data?.products))return data.products;return []}
function statusClass(status){const s=String(status||"").toUpperCase();return s==="ONLINE"?"status-online":s==="BUSY"?"status-busy":"status-offline"}
function eventClass(type){const t=String(type||"INFO").toUpperCase();return t==="SUCCESS"?"success":(t==="ERROR"||t==="FAILED")?"error":(t==="WARNING"||t==="WARN")?"warning":""}
function time(value){if(!value)return"--:--";const d=new Date(value);return Number.isNaN(d.getTime())?"--:--":d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}

async function refreshData({silent=false}={}){
  if(state.auth.status!=="authenticated"){renderAuthState();return}
  const [
    health,
    dashboard,
    workersData,
    eventsData,
    productsData,
    discoveryRunsData,
    contentOperationsData,
    audienceVisibilityData,
    attributionLineageData,
    economicPerformanceData,
    publishingQueueData,
    earningsData,
    payoutsData
  ]=await Promise.all([
    api("/health"),
    api("/system/dashboard"),
    api("/system/workers"),
    api("/system/events"),
    api("/products/"),
    api("/discovery/runs?limit=50"),
    api("/content/operations?limit=50"),
    api("/audience/visibility?limit=50"),
    api("/attribution/lineage?limit=50"),
    api("/economics/performance"),
    api("/publisher/queue"),
    api("/affiliate-earnings/?limit=100"),
    api("/affiliate-payouts/?limit=100")
  ]);

  state.health=health;
  state.dashboard=dashboard;
  state.workers=Array.isArray(workersData)?workersData:[];
  state.events=Array.isArray(eventsData)?eventsData:[];
  state.products=normalizeProducts(productsData);

  state.opportunities={
    ...state.opportunities,
    status:discoveryRunsData?"success":"error",
    runs:Array.isArray(discoveryRunsData)?discoveryRunsData:[],
    error:discoveryRunsData?null:"Discovery run index API unavailable."
  };

  state.audience={
    status:audienceVisibilityData?"success":"error",
    profiles:Array.isArray(audienceVisibilityData?.profiles)?audienceVisibilityData.profiles:[],
    signals:Array.isArray(audienceVisibilityData?.signals)?audienceVisibilityData.signals:[],
    qualifications:Array.isArray(audienceVisibilityData?.qualifications)?audienceVisibilityData.qualifications:[],
    segments:Array.isArray(audienceVisibilityData?.segments)?audienceVisibilityData.segments:[],
    segmentRevisions:Array.isArray(audienceVisibilityData?.segment_revisions)?audienceVisibilityData.segment_revisions:[],
    memberships:Array.isArray(audienceVisibilityData?.memberships)?audienceVisibilityData.memberships:[],
    error:audienceVisibilityData?null:"Audience visibility API unavailable."
  };

  state.attribution={
    status:attributionLineageData?"success":"error",
    publications:Array.isArray(attributionLineageData?.publications)?attributionLineageData.publications:[],
    contexts:Array.isArray(attributionLineageData?.contexts)?attributionLineageData.contexts:[],
    clicks:Array.isArray(attributionLineageData?.clicks)?attributionLineageData.clicks:[],
    facts:Array.isArray(attributionLineageData?.facts)?attributionLineageData.facts:[],
    earningLinks:Array.isArray(attributionLineageData?.earning_links)?attributionLineageData.earning_links:[],
    settlementLinks:Array.isArray(attributionLineageData?.settlement_links)?attributionLineageData.settlement_links:[],
    error:attributionLineageData?null:"Attribution lineage API unavailable."
  };

  state.performance={
    status:economicPerformanceData?"success":"error",
    rows:Array.isArray(economicPerformanceData?.rows)?economicPerformanceData.rows:[],
    error:economicPerformanceData?null:"Economic performance API unavailable."
  };

  state.contentOps={
    status:contentOperationsData?"success":"error",
    briefs:Array.isArray(contentOperationsData?.briefs)?contentOperationsData.briefs:[],
    generationRuns:Array.isArray(contentOperationsData?.generation_runs)?contentOperationsData.generation_runs:[],
    artifacts:Array.isArray(contentOperationsData?.artifacts)?contentOperationsData.artifacts:[],
    evaluations:Array.isArray(contentOperationsData?.evaluations)?contentOperationsData.evaluations:[],
    repurposingRuns:Array.isArray(contentOperationsData?.repurposing_runs)?contentOperationsData.repurposing_runs:[],
    error:contentOperationsData?null:"Content operations API unavailable."
  };

  state.distribution={
    status:publishingQueueData?"success":"error",
    queue:Array.isArray(publishingQueueData?.queue)?publishingQueueData.queue:[],
    error:publishingQueueData?null:"Publishing queue API unavailable."
  };

  state.commissions={
    earningsStatus:earningsData?"success":"error",
    payoutsStatus:payoutsData?"success":"error",
    earnings:Array.isArray(earningsData?.earnings)?earningsData.earnings:[],
    payouts:Array.isArray(payoutsData?.payouts)?payoutsData.payouts:[]
  };

  setBackendStatus(Boolean(health?.success));
  document.getElementById("sidebar-version").textContent=health?.success?"FastAPI connected":"Backend unavailable";

  if(!["recommendations","approvals","experiments"].includes(state.activeView))render();
  if(!silent)toast(health?.success?"Live data refreshed.":"Backend is not reachable.");
}
function kpi(label,value,meta){return `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="meta">${esc(meta)}</div></div>`}
function workers(limit=6){const list=state.workers.slice(0,limit);if(!list.length)return `<div class="empty">${state.backendOnline?"No workers returned by runtime.":"Backend unavailable."}</div>`;return `<div class="worker-list">${list.map(w=>`<div class="worker-row"><div class="worker-left"><span class="dot ${String(w.status).toUpperCase()==="ONLINE"?"online":""}"></span><div><span class="worker-name">${esc(w.name||"Unnamed worker")}</span><span class="sub">${esc(w.worker_type||"AI worker")}</span></div></div><span class="status-pill ${statusClass(w.status)}">${esc(w.status||"UNKNOWN")}</span></div>`).join("")}</div>`}
function events(limit=7){const list=[...state.events].slice(-limit).reverse();if(!list.length)return `<div class="empty">No runtime events yet.</div>`;return `<div class="event-list">${list.map(e=>`<div class="event-row"><div class="event-left"><span class="event-dot ${eventClass(e.type)}"></span><span class="event-message">${esc(e.event||"Event")}</span></div><span class="event-time">${esc(time(e.timestamp))}</span></div>`).join("")}</div>`}

function overview(){const d=state.dashboard||{};const wc=state.workers.length||Number(d.workers||0);const running=Number(d.running_missions||0);const success=Number(d.success_rate??100);return `<div class="hero"><div><h3>Affiliate operations at a glance</h3><p>Live runtime data is shown where an API exists. Frozen optimization capabilities without an API are clearly marked instead of being faked.</p></div><span class="live-badge">${state.backendOnline?"● LIVE BACKEND":"● BACKEND OFFLINE"}</span></div>
<div class="grid kpi-grid">${kpi("Products & Offers",state.products.length,state.products.length?"Loaded from /products/":"No products returned")}${kpi("AI Workers",wc,state.backendOnline?"Live runtime registry":"Backend unavailable")}${kpi("Running Missions",running,"Runtime mission activity")}${kpi("Success Rate",`${success}%`,"Backend authoritative")}</div>
<div class="grid two-col"><section class="card"><div class="card-head"><div><h4>AI Workforce</h4><p>Registered operational workers</p></div><span class="state-badge">${wc} registered</span></div><div class="card-body">${workers()}</div></section>
<section class="card"><div class="card-head"><div><h4>Optimization Pipeline</h4><p>Frozen through M11A10</p></div><span class="state-badge">DESIGN ONLY</span></div><div class="card-body"><div class="pipeline"><span class="stage frozen">Economic truth</span><span>→</span><span class="stage frozen">Preference</span><span>→</span><span class="stage frozen">Recommendation</span><span>→</span><span class="stage frozen">Approval</span><span>→</span><span class="stage frozen">Experiment design</span></div><div class="callout" style="margin-top:14px">M11A10 can describe an experiment, but cannot allocate money, assign traffic, schedule execution, or launch anything.</div></div></section>
<section class="card"><div class="card-head"><div><h4>Recent Activity</h4><p>Live system events</p></div><button class="secondary" data-action="activity">View all</button></div><div class="card-body">${events()}</div></section>
<section class="card"><div class="card-head"><div><h4>Operator Attention</h4><p>Human-visible boundaries</p></div></div><div class="card-body"><div class="mini-list"><div class="mini-row"><span>Recommendation API surface</span><span class="state-badge status-online">LIVE</span></div><div class="mini-row"><span>Approval API surface</span><span class="state-badge status-online">LIVE</span></div><div class="mini-row"><span>Experiment design API surface</span><span class="state-badge status-online">LIVE</span></div></div></div></section></div>`}
function offers(){const p=state.products;return `<div class="section-stack"><div><h3 class="section-title">Products & Offers</h3><p class="section-copy">Live products from the existing FastAPI products endpoint.</p></div><section class="card"><div class="card-body table-wrap">${p.length?`<table class="data-table"><thead><tr><th>Name</th><th>Category</th><th>Program</th><th>Score</th><th>Status</th></tr></thead><tbody>${p.map(x=>`<tr><td>${esc(x.name||"—")}</td><td>${esc(x.category||"—")}</td><td>${esc(x.affiliate_program||x.affiliate_network||"—")}</td><td>${esc(x.affiliate_score??x.opportunity_score??"—")}</td><td>${esc(x.status||"—")}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">No products returned. The screen is wired and ready for live product records.</div>`}</div></section></div>`}
function pending(title,copy,frozen=false){return `<div class="section-stack"><div><h3 class="section-title">${esc(title)}</h3><p class="section-copy">${esc(copy)}</p></div><section class="card"><div class="card-body"><div class="callout">${frozen?"Backend service is frozen and qualified, but this UI intentionally waits for a dedicated API surface before showing operational controls.":"UI shell is ready. This capability will be wired when its backend read model/API is exposed."}</div></div></section></div>`}
function approvalCandidateRows(){
  const rows=state.recommendations.rows||[];
  const form=state.approvals.form;
  const approved=form.decisionState==="APPROVED";

  if(!rows.length){
    return `<div class="empty">The current recommendation projection has no Tier-1 rows. REJECTED or DEFERRED may still be projected against the same recommendation request; APPROVED requires at least one Tier-1 row.</div>`;
  }

  return `<div class="approval-candidates">${rows.map((row,index)=>{
    const checked=form.selected.includes(index);
    return `<label class="approval-candidate ${checked?"selected":""}">
      <input type="checkbox" class="approval-row-select" data-index="${index}" ${checked?"checked":""} ${approved?"":"disabled"}>
      <div class="approval-candidate-main">
        <div>
          <span class="tier-badge">TIER ${esc(row.preference_tier)}</span>
          <strong>Recommendation ${index+1}</strong>
          <small>${esc(dimensionLabel(row.dimensions||[]))}</small>
        </div>
        <div class="approval-profit">
          <span>Operating Profit</span>
          <strong>${esc(row.currency)} ${esc(row.operating_profit)}</strong>
        </div>
      </div>
    </label>`;
  }).join("")}</div>`;
}

function approvalOutcome(){
  const approval=state.approvals;

  if(approval.status==="loading"){
    return `<div class="recommendation-state approval-state"><div class="spinner"></div><strong>Projecting external approval decision...</strong><span>The frozen M11A9 service is re-evaluating the same recommendation request. No decision is persisted and nothing is executed.</span></div>`;
  }

  if(approval.status==="error"){
    return `<div class="recommendation-state error-state approval-state"><strong>Approval projection failed</strong><span>${esc(approval.error||"The frozen approval projection could not be completed.")}</span></div>`;
  }

  if(approval.status!=="success"||!approval.outcome){
    return `<div class="recommendation-state approval-state"><strong>Awaiting an external decision</strong><span>Select APPROVED, REJECTED, or DEFERRED and provide explicit decision provenance. The API projects the frozen M11A9 outcome only; it does not persist, allocate, launch, or execute anything.</span></div>`;
  }

  const out=approval.outcome;
  const rows=Array.isArray(out.approved_rows)?out.approved_rows:[];

  return `<div class="approval-result">
    <div class="result-banner approval-result-banner">
      <div>
        <span class="result-kicker">M11A9 EXTERNAL DECISION</span>
        <strong>${esc(out.decision_state)}</strong>
      </div>
      <span class="state-badge status-online">PROJECTED · NOT PERSISTED</span>
    </div>

    <div class="approval-summary-grid">
      <div><span>Currency</span><strong>${esc(out.currency)}</strong></div>
      <div><span>Evaluated at</span><strong>${esc(out.evaluated_at)}</strong></div>
      <div><span>Actor</span><strong>${esc(out.actor_reference)}</strong></div>
      <div><span>Decision reference</span><strong>${esc(out.decision_reference)}</strong></div>
      <div><span>Decided at</span><strong>${esc(out.decided_at)}</strong></div>
      <div><span>Approval policy</span><strong>${esc(out.approval_policy_version)}</strong></div>
      <div><span>Recommendation policy</span><strong>${esc(out.recommendation_policy_version)}</strong></div>
      <div><span>Approval contract</span><strong>${esc(out.approval_contract_version)}</strong></div>
    </div>

    <div class="approval-approved-rows">
      <h5>${out.decision_state==="APPROVED"?"Approved Tier-1 rows":"Approved rows"}</h5>
      ${rows.length?rows.map((row,index)=>`<div class="approved-row">
        <div>
          <span class="tier-badge">TIER ${esc(row.preference_tier)}</span>
          <strong>${esc(dimensionLabel(row.dimensions||[]))}</strong>
        </div>
        <strong>${esc(row.currency)} ${esc(row.operating_profit)}</strong>
      </div>`).join(""):`<div class="empty">No approved rows. This is required for ${esc(out.decision_state)}.</div>`}
    </div>

    <details class="provenance">
      <summary>Frozen approval provenance</summary>
      <dl>
        <div><dt>Source recommendation contract</dt><dd>${esc(out.source_recommendation_contract_version)}</dd></div>
        <div><dt>Source recommendation semantics</dt><dd>${esc(out.source_recommendation_semantics)}</dd></div>
        <div><dt>Approval semantics</dt><dd>${esc(out.approval_semantics)}</dd></div>
      </dl>
    </details>

    <div class="toolbar"><button class="primary" data-action="go-experiments">Open Experiment Design</button></div>
    <div class="authority-wall"><strong>Authority stops here.</strong> This projected approval outcome does not allocate budget, assign traffic, create an experiment, launch content, dispatch outreach, or execute any operation.</div>
  </div>`;
}

function approvals(){
  const rec=state.recommendations;
  const form=state.approvals.form;
  const ready=rec.status==="success"&&rec.request;

  if(!ready){
    return `<div class="section-stack">
      <div class="hero">
        <div><h3>Approval Queue</h3><p>M11A9 is the explicit external governance boundary over a frozen M11A8 recommendation request.</p></div>
        <span class="live-badge">${state.backendOnline?"● UIF3A API READY":"● BACKEND OFFLINE"}</span>
      </div>
      <section class="card">
        <div class="card-head"><div><h4>No recommendation request loaded</h4><p>Approval cannot be inferred or invented.</p></div><span class="state-badge">M11A9 FROZEN</span></div>
        <div class="card-body">
          <div class="callout">Project Recommendations first. UIF3B will carry that exact operator-supplied proposal request into the approval API; it will not invent policy values or reconstruct economic inputs.</div>
          <div class="toolbar" style="margin-top:14px"><button class="primary" data-action="go-recommendations">Go to Recommendations</button></div>
        </div>
      </section>
    </div>`;
  }

  const approvedEnabled=rec.rows.length>0;
  return `<div class="section-stack">
    <div class="hero">
      <div><h3>Approval Queue</h3><p>Project an explicit external M11A9 decision over the current frozen recommendation request. A fresh server-side M11A8 projection is authoritative; stale selections may be rejected.</p></div>
      <span class="live-badge">${state.backendOnline?"● UIF3A API READY":"● BACKEND OFFLINE"}</span>
    </div>

    <div class="approval-layout">
      <section class="card approval-form-card">
        <div class="card-head"><div><h4>External Decision</h4><p>Human-supplied governance provenance</p></div><span class="state-badge">NO EXECUTION</span></div>
        <div class="card-body">
          <form id="approval-form" class="recommendation-form">
            <div class="approval-source">
              <span>Current recommendation request</span>
              <strong>${esc(rec.request.currency)} · ${esc((rec.request.dimensions||[]).join(", "))}</strong>
              <small>Evaluated ${esc(rec.request.evaluated_at)} · ${rec.rows.length} Tier-1 ${rec.rows.length===1?"row":"rows"} shown from the last UIF2A projection.</small>
            </div>

            <div class="decision-options">
              <label class="decision-option ${form.decisionState==="APPROVED"?"active":""} ${approvedEnabled?"":"disabled"}">
                <input type="radio" name="approval-state" value="APPROVED" ${form.decisionState==="APPROVED"?"checked":""} ${approvedEnabled?"":"disabled"}>
                <span><strong>APPROVED</strong><small>Select one, multiple, or all Tier-1 rows in exact API order.</small></span>
              </label>
              <label class="decision-option ${form.decisionState==="REJECTED"?"active":""}">
                <input type="radio" name="approval-state" value="REJECTED" ${form.decisionState==="REJECTED"?"checked":""}>
                <span><strong>REJECTED</strong><small>No candidate selection is permitted.</small></span>
              </label>
              <label class="decision-option ${form.decisionState==="DEFERRED"?"active":""}">
                <input type="radio" name="approval-state" value="DEFERRED" ${form.decisionState==="DEFERRED"?"checked":""}>
                <span><strong>DEFERRED</strong><small>No candidate selection is permitted.</small></span>
              </label>
            </div>

            <div>
              <div class="approval-subhead"><strong>Tier-1 candidate selection</strong><span>${form.decisionState==="APPROVED"?"Explicit selection required":"Enabled only for APPROVED"}</span></div>
              ${approvalCandidateRows()}
            </div>

            <div class="form-grid">
              <label class="field"><span>Actor reference <em>required</em></span><input id="approval-actor" type="text" value="${esc(form.actorReference)}" placeholder="operator-001" required></label>
              <label class="field"><span>Decision reference <em>required</em></span><input id="approval-reference" type="text" value="${esc(form.decisionReference)}" placeholder="decision-2026-001" required></label>
              <label class="field span-2"><span>Decided at <em>required</em></span><div class="inline-field"><input id="approval-decided-at" type="datetime-local" value="${esc(form.decidedAt)}" required><button class="secondary compact" type="button" data-action="approval-now">Use current time</button></div><small>Converted to explicit UTC. The frozen service requires this time not to predate the recommendation evaluation.</small></label>
              <label class="field span-2"><span>Approval policy version <em>required</em></span><input id="approval-policy-version" type="text" value="${esc(form.policyVersion)}" placeholder="operator-approval-v1" required></label>
            </div>

            <div class="form-actions">
              <button class="primary" type="submit">Project Approval Decision</button>
              <span class="authority-note">External decision projection · not persisted · no allocation · no execution</span>
            </div>
          </form>
        </div>
      </section>

      <section class="card approval-output-card">
        <div class="card-head"><div><h4>Frozen M11A9 Outcome</h4><p>Authoritative UIF3A projection</p></div><span class="state-badge">${state.approvals.status==="success"?"LIVE RESULT":"WAITING"}</span></div>
        <div class="card-body">${approvalOutcome()}</div>
      </section>
    </div>
  </div>`;
}
function emptyExperimentState(){
  return {
    status:"idle",
    rows:[],
    error:null,
    form:{
      policyVersion:"",
      selected:[],
      designs:{}
    }
  };
}

function ensureExperimentDesignForms(){
  const out=state.approvals.outcome;
  const rows=Array.isArray(out?.approved_rows)?out.approved_rows:[];
  const form=state.experiments.form;

  form.selected=form.selected
    .filter(index=>Number.isInteger(index)&&index>=0&&index<rows.length)
    .sort((a,b)=>a-b);

  rows.forEach((_row,index)=>{
    if(!form.designs[index]){
      form.designs[index]={
        experimentReference:"",
        hypothesis:"",
        controlDefinition:"",
        treatmentDefinition:"",
        successMeasure:"",
        observationWindow:"",
        designReference:"",
        designedAt:""
      };
    }
  });

  Object.keys(form.designs).forEach(key=>{
    const index=Number(key);
    if(!Number.isInteger(index)||index<0||index>=rows.length){
      delete form.designs[key];
    }
  });
}

function experimentDesignCards(){
  const out=state.approvals.outcome;
  const rows=Array.isArray(out?.approved_rows)?out.approved_rows:[];
  const form=state.experiments.form;

  if(out?.decision_state!=="APPROVED"){
    return `<div class="callout">The last M11A9 decision is ${esc(out?.decision_state||"not approved")}. Frozen M11A10 requires <strong>zero experiment design inputs</strong> for REJECTED or DEFERRED decisions. You may still project the explicit empty M11A10 result using the policy version below.</div>`;
  }

  if(!rows.length){
    return `<div class="empty">The authoritative APPROVED outcome contains no approved rows. No experiment design input can be bound.</div>`;
  }

  ensureExperimentDesignForms();

  return `<div class="experiment-candidates">${rows.map((row,index)=>{
    const selected=form.selected.includes(index);
    const design=form.designs[index];
    const required=selected?"required":"";
    const disabled=selected?"":"disabled";

    return `<article class="experiment-design-card ${selected?"selected":""}">
      <label class="experiment-design-select-row">
        <input class="experiment-row-select" type="checkbox" data-index="${index}" ${selected?"checked":""}>
        <div>
          <span class="tier-badge">TIER ${esc(row.preference_tier)}</span>
          <strong>Design against approved row ${index+1}</strong>
          <small>${esc(dimensionLabel(row.dimensions||[]))} · ${esc(row.currency)} ${esc(row.operating_profit)}</small>
        </div>
        <span class="state-badge">${selected?"IN DESIGN":"NOT DESIGNED"}</span>
      </label>

      <div class="experiment-design-fields">
        <div class="form-grid">
          <label class="field"><span>Experiment reference <em>${selected?"required":"select row first"}</em></span><input id="exp-reference-${index}" type="text" value="${esc(design.experimentReference)}" placeholder="experiment-001" ${required} ${disabled}></label>
          <label class="field"><span>Design reference <em>${selected?"required":"select row first"}</em></span><input id="exp-design-reference-${index}" type="text" value="${esc(design.designReference)}" placeholder="design-001" ${required} ${disabled}></label>

          <label class="field span-2"><span>Hypothesis <em>${selected?"required":"select row first"}</em></span><textarea id="exp-hypothesis-${index}" rows="3" placeholder="Explicit operator-supplied hypothesis" ${required} ${disabled}>${esc(design.hypothesis)}</textarea></label>
          <label class="field span-2"><span>Control definition <em>${selected?"required":"select row first"}</em></span><textarea id="exp-control-${index}" rows="2" placeholder="Define the control condition" ${required} ${disabled}>${esc(design.controlDefinition)}</textarea></label>
          <label class="field span-2"><span>Treatment definition <em>${selected?"required":"select row first"}</em></span><textarea id="exp-treatment-${index}" rows="2" placeholder="Define the treatment condition" ${required} ${disabled}>${esc(design.treatmentDefinition)}</textarea></label>
          <label class="field span-2"><span>Success measure <em>${selected?"required":"select row first"}</em></span><textarea id="exp-success-${index}" rows="2" placeholder="Define the success measure" ${required} ${disabled}>${esc(design.successMeasure)}</textarea></label>

          <label class="field"><span>Observation window <em>${selected?"required":"select row first"}</em></span><input id="exp-window-${index}" type="text" value="${esc(design.observationWindow)}" placeholder="P14D" ${required} ${disabled}><small>Explicit ISO-8601 duration, for example P14D or PT72H.</small></label>
          <label class="field"><span>Designed at <em>${selected?"required":"select row first"}</em></span><div class="inline-field"><input id="exp-designed-at-${index}" type="datetime-local" value="${esc(design.designedAt)}" ${required} ${disabled}><button class="secondary compact" type="button" data-action="experiment-now" data-index="${index}" ${disabled}>Use current time</button></div><small>Converted to UTC. Frozen M11A10 requires this not to predate the approval decision.</small></label>
        </div>
      </div>
    </article>`;
  }).join("")}</div>`;
}

function approvedRecommendationProvenance(row){
  if(!row)return "";

  return `<details class="provenance">
    <summary>Complete approved recommendation provenance</summary>
    <dl>
      <div><dt>Currency</dt><dd>${esc(row.currency)}</dd></div>
      <div><dt>Dimensions</dt><dd>${esc(dimensionLabel(row.dimensions||[]))}</dd></div>
      <div><dt>Operating profit</dt><dd>${esc(row.operating_profit)}</dd></div>
      <div><dt>Preference tier</dt><dd>${esc(row.preference_tier)}</dd></div>
      <div><dt>Evaluated at</dt><dd>${esc(row.evaluated_at)}</dd></div>
      <div><dt>Eligibility policy</dt><dd>${esc(row.eligibility_policy_version)}</dd></div>
      <div><dt>Eligibility fingerprint</dt><dd>${esc(row.eligibility_policy_fingerprint)}</dd></div>
      <div><dt>Comparison policy</dt><dd>${esc(row.comparison_policy_version)}</dd></div>
      <div><dt>Recommendation policy</dt><dd>${esc(row.recommendation_policy_version)}</dd></div>
      <div><dt>Source preference semantics</dt><dd>${esc(row.source_ordered_preference_semantics)}</dd></div>
      <div><dt>Source preference contract</dt><dd>${esc(row.source_ordered_preference_contract_version)}</dd></div>
      <div><dt>Recommendation semantics</dt><dd>${esc(row.recommendation_proposal_semantics)}</dd></div>
      <div><dt>Recommendation contract</dt><dd>${esc(row.recommendation_proposal_contract_version)}</dd></div>
    </dl>
  </details>`;
}

function experimentOutcome(){
  const exp=state.experiments;

  if(exp.status==="loading"){
    return `<div class="recommendation-state experiment-state"><div class="spinner"></div><strong>Projecting frozen M11A10 design...</strong><span>The server is re-projecting the exact M11A9 approval request and binding only the explicit design inputs. Nothing is persisted or executed.</span></div>`;
  }

  if(exp.status==="error"){
    return `<div class="recommendation-state error-state experiment-state"><strong>Experiment design projection failed</strong><span>${esc(exp.error||"The frozen M11A10 projection could not be completed.")}</span></div>`;
  }

  if(exp.status!=="success"){
    return `<div class="recommendation-state experiment-state"><strong>Awaiting experiment design projection</strong><span>Use the exact last successful M11A9 approval request, select zero or more approved rows to design, and provide every design field explicitly.</span></div>`;
  }

  const rows=Array.isArray(exp.rows)?exp.rows:[];

  if(!rows.length){
    return `<div class="experiment-result">
      <div class="result-banner">
        <div><span class="result-kicker">M11A10 DESIGN PROJECTION</span><strong>0 design rows returned</strong></div>
        <span class="state-badge status-online">PROJECTED · NOT EXECUTED</span>
      </div>
      <div class="empty experiment-empty-result">Frozen M11A10 returned an explicit empty design set. This is valid for an APPROVED decision with zero supplied designs and is required for REJECTED or DEFERRED decisions.</div>
      <div class="authority-wall"><strong>Design authority only.</strong> No budget allocation, traffic assignment, scheduling, publication, outreach, platform action, or execution occurred.</div>
    </div>`;
  }

  return `<div class="experiment-result">
    <div class="result-banner">
      <div><span class="result-kicker">M11A10 DESIGN PROJECTION</span><strong>${rows.length} ${rows.length===1?"design row":"design rows"} returned</strong></div>
      <span class="state-badge status-online">PROJECTED · NOT EXECUTED</span>
    </div>

    <div class="experiment-result-list">${rows.map((row,index)=>{
      const approved=row.approved_recommendation_row||{};
      return `<article class="experiment-result-card">
        <div class="experiment-result-head">
          <div>
            <span class="result-kicker">DESIGN ${index+1}</span>
            <h4>${esc(row.experiment_reference)}</h4>
            <p>${esc(dimensionLabel(approved.dimensions||[]))}</p>
          </div>
          <div class="profit-block"><span>Approved operating profit</span><strong>${esc(approved.currency)} ${esc(approved.operating_profit)}</strong></div>
        </div>

        <div class="experiment-copy-grid">
          <div><span>Hypothesis</span><p>${esc(row.hypothesis)}</p></div>
          <div><span>Control</span><p>${esc(row.control_definition)}</p></div>
          <div><span>Treatment</span><p>${esc(row.treatment_definition)}</p></div>
          <div><span>Success measure</span><p>${esc(row.success_measure)}</p></div>
        </div>

        <div class="experiment-metadata-grid">
          <div><span>Observation window</span><strong>${esc(row.observation_window)}</strong></div>
          <div><span>Actor</span><strong>${esc(row.actor_reference)}</strong></div>
          <div><span>Decision reference</span><strong>${esc(row.decision_reference)}</strong></div>
          <div><span>Decided at</span><strong>${esc(row.decided_at)}</strong></div>
          <div><span>Design reference</span><strong>${esc(row.design_reference)}</strong></div>
          <div><span>Designed at</span><strong>${esc(row.designed_at)}</strong></div>
          <div><span>Recommendation policy</span><strong>${esc(row.recommendation_policy_version)}</strong></div>
          <div><span>Approval policy</span><strong>${esc(row.approval_policy_version)}</strong></div>
          <div><span>Experiment design policy</span><strong>${esc(row.experiment_design_policy_version)}</strong></div>
        </div>

        <details class="provenance">
          <summary>Frozen M11A10 provenance</summary>
          <dl>
            <div><dt>Source approval semantics</dt><dd>${esc(row.source_approval_semantics)}</dd></div>
            <div><dt>Source approval contract</dt><dd>${esc(row.source_approval_contract_version)}</dd></div>
            <div><dt>Experiment design semantics</dt><dd>${esc(row.experiment_design_semantics)}</dd></div>
            <div><dt>Experiment design contract</dt><dd>${esc(row.experiment_design_contract_version)}</dd></div>
          </dl>
        </details>

        ${approvedRecommendationProvenance(approved)}
      </article>`;
    }).join("")}</div>

    <div class="authority-wall"><strong>Design authority only.</strong> UIF4A projected frozen M11A10 design rows. It did not allocate budget, assign traffic, schedule work, publish content, dispatch outreach, call a platform, or execute an experiment.</div>
  </div>`;
}

function experiments(){
  const approval=state.approvals;
  const out=approval.outcome;
  const ready=approval.status==="success"&&approval.request&&out;

  if(!ready){
    return `<div class="section-stack">
      <div class="hero">
        <div><h3>Experiments</h3><p>Live read-only experiment design over the exact last successful M11A9 approval projection.</p></div>
        <span class="live-badge">${state.backendOnline?"● UIF4A API READY":"● BACKEND OFFLINE"}</span>
      </div>
      <section class="card">
        <div class="card-head"><div><h4>No successful approval request loaded</h4><p>M11A10 cannot infer or reconstruct governance.</p></div><span class="state-badge">M11A10 DESIGN ONLY</span></div>
        <div class="card-body">
          <div class="callout">Project an Approval Queue decision first. UIF4B carries that exact approval request into UIF4A; it does not rebuild the decision from visible output.</div>
          <div class="toolbar" style="margin-top:14px"><button class="primary" data-action="go-approvals">Go to Approval Queue</button></div>
        </div>
      </section>
    </div>`;
  }

  ensureExperimentDesignForms();
  const approvedRows=Array.isArray(out.approved_rows)?out.approved_rows:[];
  const selectedCount=state.experiments.form.selected.length;

  return `<div class="section-stack">
    <div class="hero">
      <div><h3>Experiments</h3><p>Bind explicit design inputs to the authoritative M11A9 approval. UIF4A re-projects the exact approval request, so a stale approval may be rejected by the server.</p></div>
      <span class="live-badge">${state.backendOnline?"● UIF4A API READY":"● BACKEND OFFLINE"}</span>
    </div>

    <div class="experiment-layout">
      <section class="card experiment-form-card">
        <div class="card-head"><div><h4>Experiment Design Request</h4><p>All design semantics are operator supplied.</p></div><span class="state-badge">M11A10 → UIF4A</span></div>
        <div class="card-body">
          <form id="experiment-form" class="recommendation-form">
            <div class="experiment-source">
              <span>Last successful M11A9 approval</span>
              <strong>${esc(out.decision_state)} · ${esc(out.currency)}</strong>
              <small>Decision ${esc(out.decision_reference)} · ${approvedRows.length} approved ${approvedRows.length===1?"row":"rows"} · exact approval request retained from UIF3B.</small>
            </div>

            ${experimentDesignCards()}

            <div class="form-grid">
              <label class="field span-2"><span>Experiment design policy version <em>required</em></span><input id="experiment-policy-version" type="text" value="${esc(state.experiments.form.policyVersion)}" placeholder="experiment-design-v1" required><small>No server or UI default is supplied.</small></label>
            </div>

            <div class="experiment-selection-note">${out.decision_state==="APPROVED"
              ? `${selectedCount} of ${approvedRows.length} approved rows selected for design. Zero is valid and projects an explicit empty design set.`
              : `${esc(out.decision_state)} requires zero experiment design inputs.`}</div>

            <div class="form-actions">
              <button class="primary" type="submit">${out.decision_state==="APPROVED"?"Project Experiment Design":"Project Empty Design Outcome"}</button>
              <span class="authority-note">Read-only design · not persisted · no budget · no traffic · no launch · no execution</span>
            </div>
          </form>
        </div>
      </section>

      <section class="card experiment-output-card">
        <div class="card-head"><div><h4>Frozen M11A10 Output</h4><p>Authoritative UIF4A projection</p></div><span class="state-badge">${state.experiments.status==="success"?"LIVE RESULT":"WAITING"}</span></div>
        <div class="card-body">${experimentOutcome()}</div>
      </section>
    </div>
  </div>`;
}

function renderExperimentOutput(){
  const card=document.querySelector(".experiment-output-card");
  if(!card){render();return}

  const badge=card.querySelector(".card-head .state-badge");
  if(badge){
    badge.textContent=
      state.experiments.status==="loading"?"PROJECTING":
      state.experiments.status==="success"?"LIVE RESULT":
      state.experiments.status==="error"?"ERROR":
      "WAITING";
  }

  const body=card.querySelector(".card-body");
  if(body)body.innerHTML=experimentOutcome();
}

function captureExperimentForm(){
  const form=state.experiments.form;
  const policy=document.getElementById("experiment-policy-version");
  if(policy)form.policyVersion=policy.value;

  form.selected=Array.from(document.querySelectorAll(".experiment-row-select:checked"))
    .map(input=>Number(input.dataset.index))
    .filter(Number.isInteger)
    .sort((a,b)=>a-b);

  const rows=Array.isArray(state.approvals.outcome?.approved_rows)
    ? state.approvals.outcome.approved_rows
    : [];

  rows.forEach((_row,index)=>{
    if(!form.designs[index])return;
    const design=form.designs[index];
    const fields={
      experimentReference:`exp-reference-${index}`,
      designReference:`exp-design-reference-${index}`,
      hypothesis:`exp-hypothesis-${index}`,
      controlDefinition:`exp-control-${index}`,
      treatmentDefinition:`exp-treatment-${index}`,
      successMeasure:`exp-success-${index}`,
      observationWindow:`exp-window-${index}`,
      designedAt:`exp-designed-at-${index}`
    };

    Object.entries(fields).forEach(([key,id])=>{
      const input=document.getElementById(id);
      if(input)design[key]=input.value;
    });
  });
}

async function projectExperimentDesigns(){
  const formElement=document.getElementById("experiment-form");
  if(!formElement||!formElement.reportValidity())return;

  const approval=state.approvals;
  const out=approval.outcome;

  if(approval.status!=="success"||!approval.request||!out){
    toast("Project an Approval Queue decision first.");
    return;
  }

  ensureExperimentDesignForms();
  captureExperimentForm();

  const form=state.experiments.form;
  const approvedRows=Array.isArray(out.approved_rows)?out.approved_rows:[];

  if(out.decision_state!=="APPROVED"&&form.selected.length){
    toast(`${out.decision_state} requires zero experiment design inputs.`);
    return;
  }

  const experimentDesignInputs=out.decision_state==="APPROVED"
    ? approvedRows
        .map((row,index)=>({row,index}))
        .filter(item=>form.selected.includes(item.index))
        .map(item=>{
          const design=form.designs[item.index];
          return {
            experiment_reference:design.experimentReference.trim(),
            approved_dimensions:(item.row.dimensions||[]).map(
              dim=>({name:dim.name,value:dim.value})
            ),
            hypothesis:design.hypothesis.trim(),
            control_definition:design.controlDefinition.trim(),
            treatment_definition:design.treatmentDefinition.trim(),
            success_measure:design.successMeasure.trim(),
            observation_window:design.observationWindow.trim(),
            design_reference:design.designReference.trim(),
            designed_at:new Date(design.designedAt).toISOString()
          };
        })
    : [];

  const payload={
    approval_request:approval.request,
    experiment_design_inputs:experimentDesignInputs,
    experiment_design_policy:{
      policy_version:form.policyVersion.trim()
    }
  };

  state.experiments.status="loading";
  state.experiments.rows=[];
  state.experiments.error=null;
  renderExperimentOutput();

  try{
    const response=await requestApi("/optimization/experiment-designs/project",{
      method:"POST",
      cache:"no-store",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });

    if(!response||response.status===401)return;
    const body=await response.json().catch(()=>null);

    if(!response.ok){
      state.experiments.status="error";
      state.experiments.rows=[];
      state.experiments.error=typeof body?.detail==="string"
        ? body.detail
        : `Experiment design projection failed with HTTP ${response.status}.`;
      renderExperimentOutput();
      return;
    }

    state.experiments.status="success";
    state.experiments.rows=Array.isArray(body?.experiment_designs)
      ? body.experiment_designs
      : [];
    state.experiments.error=null;
    renderExperimentOutput();
  }catch(error){
    console.error("Experiment design projection error:",error);
    state.experiments.status="error";
    state.experiments.rows=[];
    state.experiments.error="The UIF4A experiment design API is unreachable.";
    renderExperimentOutput();
  }
}

/* UIF5B — Read-Only Opportunities Visibility */
function opportunityCandidateName(candidate){
  return candidate.program_name||candidate.vendor_name||candidate.canonical_domain||candidate.program_identity_key||candidate.id||"Unnamed candidate";
}
function opportunityEvidenceValue(value){
  if(value===null||value===undefined)return "—";
  if(typeof value==="object"){try{return JSON.stringify(value)}catch(_error){return String(value)}}
  return String(value);
}
function opportunityEvidenceBlock(candidateId){
  const surface=state.opportunities;
  const status=surface.evidenceStatus[candidateId]||"idle";
  const rows=surface.evidence[candidateId]||[];
  if(status==="loading")return `<div class="opportunity-evidence-state"><div class="spinner"></div><span>Loading durable evidence…</span></div>`;
  if(status==="error")return `<div class="operations-error">Evidence could not be loaded for this candidate.</div>`;
  if(status!=="success")return "";
  if(!rows.length)return `<div class="empty opportunity-evidence-empty">The evidence API is live and returned no observations for this candidate.</div>`;
  return `<div class="opportunity-evidence-list">${rows.map(item=>`<div class="opportunity-evidence-row"><div><strong>${esc(item.claim_type||"Evidence observation")}</strong><span>${esc(opportunityEvidenceValue(item.observed_value))}</span>${item.excerpt?`<small>${esc(item.excerpt)}</small>`:""}</div><dl><div><dt>Source</dt><dd>${esc(item.source_type||"—")}</dd></div><div><dt>Confidence</dt><dd>${esc(item.confidence??"—")}</dd></div><div><dt>Observed</dt><dd>${esc(dateTime(item.observed_at))}</dd></div></dl></div>`).join("")}</div>`;
}
function opportunityRunDetail(){
  const surface=state.opportunities;
  const run=surface.runs.find(item=>item.id===surface.selectedRunId);
  if(!surface.selectedRunId)return `<div class="recommendation-state opportunity-detail-state"><strong>Select a discovery run</strong><span>Choose a durable run on the left to read its candidates, frozen ranking, selected opportunities, and evidence.</span></div>`;
  if(surface.detailStatus==="loading")return `<div class="recommendation-state opportunity-detail-state"><div class="spinner"></div><strong>Loading discovery ledger…</strong><span>Read-only candidate, ranking, and selection APIs are being queried.</span></div>`;
  if(surface.detailStatus==="error")return `<div class="recommendation-state error-state opportunity-detail-state"><strong>Discovery detail unavailable</strong><span>The selected run could not be read from one or more discovery APIs.</span></div>`;
  if(!run)return `<div class="recommendation-state error-state opportunity-detail-state"><strong>Run no longer present</strong><span>Refresh the run list and select another durable discovery run.</span></div>`;
  const selectedIds=new Set((surface.selected||[]).map(item=>item.id));
  const ranked=surface.ranking||[];
  const candidates=surface.candidates||[];
  return `<div class="opportunity-detail"><div class="opportunity-run-summary"><div><span class="result-kicker">DISCOVERY RUN</span><h4>${esc(run.input_value)}</h4><p>${esc(run.input_type)} · ${esc(run.id)}</p></div><span class="status-pill ${operationStatusClass(run.status)}">${esc(run.status||"UNKNOWN")}</span></div><div class="opportunity-summary-grid"><div><span>Candidates</span><strong>${esc(run.candidate_count)}</strong></div><div><span>Verified</span><strong>${esc(run.verified_count)}</strong></div><div><span>Selected</span><strong>${esc(run.selected_count)}</strong></div><div><span>Created</span><strong>${esc(dateTime(run.created_at))}</strong></div></div>${run.last_error?`<div class="operations-error"><strong>Run error:</strong> ${esc(run.last_error)}</div>`:""}<section class="opportunity-subsection"><div class="approval-subhead"><strong>Frozen Ranking</strong><span>${ranked.length} ranked</span></div>${ranked.length?`<div class="opportunity-ranking-list">${ranked.map(item=>{const candidate=item.candidate||{};const selected=selectedIds.has(candidate.id);const evidenceStatus=surface.evidenceStatus[candidate.id]||"idle";return `<article class="opportunity-candidate-card ${selected?"selected":""}"><div class="opportunity-candidate-head"><div class="opportunity-rank">#${esc(item.rank)}</div><div><h5>${esc(opportunityCandidateName(candidate))}</h5><p>${esc(candidate.canonical_domain||candidate.source_url||"—")}</p></div>${selected?`<span class="state-badge status-online">SELECTED</span>`:""}</div><div class="opportunity-candidate-grid"><div><span>Score</span><strong>${esc(candidate.score??"—")}</strong></div><div><span>Confidence</span><strong>${esc(candidate.confidence??"—")}</strong></div><div><span>Verification</span><strong>${esc(candidate.verification_status||"—")}</strong></div><div><span>Disposition</span><strong>${esc(candidate.disposition||"—")}</strong></div><div><span>Network</span><strong>${esc(candidate.affiliate_network||"—")}</strong></div><div><span>Evidence count</span><strong>${esc(item.evidence_count??0)}</strong></div></div><div class="opportunity-candidate-actions"><button class="secondary compact" type="button" data-action="opportunity-evidence" data-candidate-id="${esc(candidate.id)}">${evidenceStatus==="success"?"Refresh evidence":"View evidence"}</button></div>${opportunityEvidenceBlock(candidate.id)}</article>`;}).join("")}</div>`:`<div class="empty">The ranking API is live and returned no ranked candidates for this run.</div>`}</section><section class="opportunity-subsection"><div class="approval-subhead"><strong>Candidate Ledger</strong><span>${candidates.length} candidates</span></div>${candidates.length?`<div class="table-wrap"><table class="data-table opportunity-ledger"><thead><tr><th>Candidate</th><th>Domain</th><th>Network</th><th>Score</th><th>Confidence</th><th>Verification</th><th>Disposition</th></tr></thead><tbody>${candidates.map(candidate=>`<tr><td>${esc(opportunityCandidateName(candidate))}</td><td>${esc(candidate.canonical_domain||"—")}</td><td>${esc(candidate.affiliate_network||"—")}</td><td>${esc(candidate.score??"—")}</td><td>${esc(candidate.confidence??"—")}</td><td>${esc(candidate.verification_status||"—")}</td><td>${esc(candidate.disposition||"—")}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty">The candidate ledger is live and currently empty for this run.</div>`}</section></div>`;
}
function opportunities(){
  const surface=state.opportunities;
  const runs=surface.runs||[];
  const totalCandidates=runs.reduce((sum,run)=>sum+Number(run.candidate_count||0),0);
  const totalVerified=runs.reduce((sum,run)=>sum+Number(run.verified_count||0),0);
  const totalSelected=runs.reduce((sum,run)=>sum+Number(run.selected_count||0),0);
  return `<div class="section-stack"><div class="hero"><div><h3>Opportunities</h3><p>Read-only visibility into durable discovery runs, candidate evidence, frozen ranking, and selected opportunities. UIF5B does not create, execute, launch, or retry discovery runs.</p></div><span class="live-badge">${state.backendOnline&&surface.status==="success"?"● DISCOVERY LEDGER LIVE":"● DISCOVERY INDEX UNAVAILABLE"}</span></div><div class="grid operations-kpi-grid">${kpi("Recent Runs",runs.length,"Latest up to 50 durable runs")}${kpi("Candidates",totalCandidates,"Counters across loaded runs")}${kpi("Verified",totalVerified,"Counters across loaded runs")}${kpi("Selected",totalSelected,"Counters across loaded runs")}</div>${surface.status==="error"?`<div class="operations-error">${esc(surface.error||"Discovery run index API unavailable.")}</div>`:""}<div class="opportunity-layout"><section class="card opportunity-run-card"><div class="card-head"><div><h4>Recent Discovery Runs</h4><p>Newest durable run first</p></div><span class="state-badge">${runs.length} loaded</span></div><div class="card-body">${runs.length?`<div class="opportunity-run-list">${runs.map(run=>`<button class="opportunity-run-row ${surface.selectedRunId===run.id?"active":""}" type="button" data-action="opportunity-run" data-run-id="${esc(run.id)}"><div><strong>${esc(run.input_value)}</strong><span>${esc(run.input_type)} · ${esc(dateTime(run.created_at))}</span></div><div><span class="status-pill ${operationStatusClass(run.status)}">${esc(run.status||"UNKNOWN")}</span><small>${esc(run.candidate_count)} candidates · ${esc(run.selected_count)} selected</small></div></button>`).join("")}</div>`:`<div class="empty">${surface.status==="success"?"The discovery run index is live and currently empty.":"No discovery run data is available."}</div>`}</div></section><section class="card opportunity-detail-card"><div class="card-head"><div><h4>Opportunity Intelligence</h4><p>Candidate → evidence → ranking → selection</p></div><span class="state-badge">READ ONLY</span></div><div class="card-body">${opportunityRunDetail()}</div></section></div><div class="authority-wall"><strong>Visibility only.</strong> UIF5B reads the durable discovery ledger and existing ranking/evidence outputs. It exposes no run creation, execution, mission launch, retry, publishing, outreach, allocation, or economic decision authority.</div></div>`;
}
async function loadOpportunityRun(runId){
  if(!runId)return;
  const surface=state.opportunities;
  surface.selectedRunId=runId;surface.detailStatus="loading";surface.candidates=[];surface.ranking=[];surface.selected=[];surface.evidence={};surface.evidenceStatus={};render();
  const [candidatesData,rankingData,selectedData]=await Promise.all([api(`/discovery/runs/${encodeURIComponent(runId)}/candidates`),api(`/discovery/runs/${encodeURIComponent(runId)}/ranking`),api(`/discovery/runs/${encodeURIComponent(runId)}/selected`)]);
  if(!candidatesData||!rankingData||!selectedData){surface.detailStatus="error";render();return}
  surface.candidates=Array.isArray(candidatesData)?candidatesData:[];surface.ranking=Array.isArray(rankingData?.items)?rankingData.items:[];surface.selected=Array.isArray(selectedData?.candidates)?selectedData.candidates:[];surface.detailStatus="success";render();
}
async function loadOpportunityEvidence(candidateId){
  if(!candidateId)return;
  const surface=state.opportunities;surface.evidenceStatus[candidateId]="loading";render();
  const data=await api(`/discovery/candidates/${encodeURIComponent(candidateId)}/evidence`);
  if(!data){surface.evidenceStatus[candidateId]="error";render();return}
  surface.evidence[candidateId]=Array.isArray(data)?data:[];surface.evidenceStatus[candidateId]="success";render();
}



/* UIF5D — Read-Only Audience Intelligence Visibility */
function audienceIntelligence(){
  const surface=state.audience;
  const profiles=surface.profiles||[];
  const signals=surface.signals||[];
  const qualifications=surface.qualifications||[];
  const segments=surface.segments||[];
  const revisions=surface.segmentRevisions||[];
  const memberships=surface.memberships||[];
  const qualified=qualifications.filter(row=>["QUALIFIED","HIGH_INTENT"].includes(String(row.qualification_status||"").toUpperCase())).length;
  const activeSegments=segments.filter(row=>!row.retired_at).length;

  return `<div class="section-stack">
    <div class="hero">
      <div>
        <h3>Audience</h3>
        <p>Read-only visibility into durable audience profiles, intent and problem signals, qualification assessments, segments, and memberships. Subject IDs remain pseudonymous; UIF5D does not expose external identities or contact points.</p>
      </div>
      <span class="live-badge">${state.backendOnline&&surface.status==="success"?"● AUDIENCE INTELLIGENCE LIVE":"● AUDIENCE DATA UNAVAILABLE"}</span>
    </div>

    <div class="grid audience-kpi-grid">
      ${kpi("Profiles",profiles.length,"Latest up to 50 immutable snapshots")}
      ${kpi("Signals",signals.length,"Problem, interest, intent and purchase signals")}
      ${kpi("Qualified+",qualified,"Recorded QUALIFIED or HIGH_INTENT assessments")}
      ${kpi("Active Segments",activeSegments,"Segments without a retirement timestamp")}
      ${kpi("Memberships",memberships.length,"Latest up to 50 evaluation results")}
    </div>

    ${surface.status==="error"?`<div class="operations-error">${esc(surface.error||"Audience visibility API unavailable.")}</div>`:""}

    <section class="card">
      <div class="card-head"><div><h4>Audience Profiles</h4><p>Immutable derived snapshots keyed by pseudonymous subject ID</p></div><span class="state-badge">${profiles.length} loaded</span></div>
      <div class="card-body table-wrap">${profiles.length?`<table class="data-table audience-table"><thead><tr><th>Profile</th><th>Subject</th><th>Ruleset</th><th>Derived</th><th>Effective As Of</th><th>Last Signal</th></tr></thead><tbody>${profiles.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.subject_id||"—")}</td><td>${esc(row.profile_ruleset_version||"—")}</td><td>${esc(dateTime(row.derived_at))}</td><td>${esc(dateTime(row.effective_as_of))}</td><td>${esc(dateTime(row.last_signal_observed_at))}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">${surface.status==="success"?"The audience profile ledger is live and currently empty.":"No audience profiles are available."}</div>`}</div>
    </section>

    <section class="card">
      <div class="card-head"><div><h4>Audience Signals</h4><p>Recorded problem, interest, intent, purchase, engagement, and business-need signals</p></div><span class="state-badge">${signals.length} loaded</span></div>
      <div class="card-body table-wrap">${signals.length?`<table class="data-table audience-table"><thead><tr><th>Signal</th><th>Subject</th><th>Type</th><th>Topic</th><th>Intent Stage</th><th>Strength</th><th>Confidence</th><th>Observed</th></tr></thead><tbody>${signals.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.subject_id||"—")}</td><td>${esc(row.signal_type||"—")}</td><td>${esc(row.topic_label||row.topic_slug||"—")}</td><td>${esc(row.intent_stage||"—")}</td><td>${esc(row.strength??"—")}</td><td>${esc(row.confidence??"—")}</td><td>${esc(dateTime(row.observed_at))}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">${surface.status==="success"?"The audience signal ledger is live and currently empty.":"No audience signals are available."}</div>`}</div>
    </section>

    <section class="card">
      <div class="card-head"><div><h4>Qualification Assessments</h4><p>Recorded intent and qualification scores; the UI performs no recalculation</p></div><span class="state-badge">${qualifications.length} loaded</span></div>
      <div class="card-body table-wrap">${qualifications.length?`<table class="data-table audience-table"><thead><tr><th>Assessment</th><th>Profile</th><th>Context</th><th>Intent Score</th><th>Qualification Score</th><th>Status</th><th>Purchase Signal</th><th>Business Need</th><th>Derived</th></tr></thead><tbody>${qualifications.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.profile_id||"—")}</td><td>${esc(row.context_type||"—")}</td><td>${esc(row.intent_score??"—")}</td><td>${esc(row.qualification_score??"—")}</td><td><span class="status-pill ${operationStatusClass(row.qualification_status)}">${esc(row.qualification_status||"UNKNOWN")}</span></td><td>${esc(row.purchase_signal??"—")}</td><td>${esc(row.business_need_fit??"—")}</td><td>${esc(dateTime(row.derived_at))}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">${surface.status==="success"?"No durable audience qualification assessments are currently recorded.":"No qualification data is available."}</div>`}</div>
    </section>

    <section class="card">
      <div class="card-head"><div><h4>Audience Segments</h4><p>Immutable segment definitions and latest loaded revisions</p></div><span class="state-badge">${segments.length} segments · ${revisions.length} revisions</span></div>
      <div class="card-body table-wrap">${segments.length?`<table class="data-table audience-table"><thead><tr><th>Segment</th><th>Key</th><th>Name</th><th>Status</th><th>Created</th><th>Loaded Revisions</th></tr></thead><tbody>${segments.map(row=>{const count=revisions.filter(rev=>rev.segment_id===row.id).length;return `<tr><td class="operations-reference">${esc(row.id||"—")}</td><td>${esc(row.segment_key||"—")}</td><td>${esc(row.name||"—")}</td><td><span class="status-pill ${row.retired_at?"status-offline":"status-online"}">${row.retired_at?"RETIRED":"ACTIVE"}</span></td><td>${esc(dateTime(row.created_at))}</td><td>${esc(count)}</td></tr>`;}).join("")}</tbody></table>`:`<div class="empty">${surface.status==="success"?"The audience segment ledger is live and currently empty.":"No segment data is available."}</div>`}</div>
    </section>

    <section class="card">
      <div class="card-head"><div><h4>Segment Memberships</h4><p>Recorded profile-to-segment evaluation outcomes</p></div><span class="state-badge">${memberships.length} loaded</span></div>
      <div class="card-body table-wrap">${memberships.length?`<table class="data-table audience-table"><thead><tr><th>Membership</th><th>Profile</th><th>Segment Revision</th><th>Member</th><th>Evaluated</th></tr></thead><tbody>${memberships.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.profile_id||"—")}</td><td class="operations-reference">${esc(row.segment_revision_id||"—")}</td><td>${row.is_member===true?"Yes":row.is_member===false?"No":"—"}</td><td>${esc(dateTime(row.evaluated_at))}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">${surface.status==="success"?"No durable audience segment memberships are currently recorded.":"No membership data is available."}</div>`}</div>
    </section>

    <div class="authority-wall"><strong>Visibility only.</strong> UIF5D reads immutable audience intelligence. It exposes no external identity resolution, contact enrichment, targeting, outreach, profile mutation, signal extraction, qualification recalculation, segment evaluation, mission launch, or execution authority.</div>
  </div>`;
}

/* UIF5C — Read-Only Content Operations Visibility */
function contentText(value,max=92){const text=String(value??"");return text.length>max?`${text.slice(0,max-1)}…`:text}
function contentOperations(){
  const s=state.contentOps,b=s.briefs||[],g=s.generationRuns||[],a=s.artifacts||[],e=s.evaluations||[],r=s.repurposingRuns||[];
  const table=(title,copy,count,headers,rows,empty)=>`<section class="card"><div class="card-head"><div><h4>${esc(title)}</h4><p>${esc(copy)}</p></div><span class="state-badge">${count} loaded</span></div><div class="card-body table-wrap">${count?`<table class="data-table content-table"><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`:`<div class="empty">${esc(empty)}</div>`}</div></section>`;
  return `<div class="section-stack"><div class="hero"><div><h3>Content Assets</h3><p>Read-only visibility into durable research briefs, generation runs, generated assets, evaluations, and repurposing lineage. UIF5C does not generate, evaluate, repurpose, publish, schedule, or dispatch content.</p></div><span class="live-badge">${state.backendOnline&&s.status==="success"?"● CONTENT LEDGER LIVE":"● CONTENT LEDGER UNAVAILABLE"}</span></div>
  <div class="grid content-kpi-grid">${kpi("Research Briefs",b.length,"Latest up to 50 durable briefs")}${kpi("Generation Runs",g.length,"Latest up to 50 attempts")}${kpi("Generated Assets",a.length,"Durable generated artifacts")}${kpi("Evaluations",e.length,"Recorded evaluation decisions")}${kpi("Repurpose Runs",r.length,"Recorded repurposing lineage")}</div>
  ${s.status==="error"?`<div class="operations-error">${esc(s.error||"Content operations API unavailable.")}</div>`:""}
  ${table("Research Briefs","Upstream content instructions grounded in discovery candidates",b.length,["Brief","Type","Channel","Objective","Status","Candidate","Created"],b.map(x=>`<tr><td class="operations-reference">${esc(x.id||"—")}</td><td>${esc(x.content_type||"—")}</td><td>${esc(x.channel_intent||"—")}</td><td class="content-copy-cell">${esc(contentText(x.objective))}</td><td><span class="status-pill ${operationStatusClass(x.status)}">${esc(x.status||"UNKNOWN")}</span></td><td class="operations-reference">${esc(x.discovery_candidate_id||"—")}</td><td>${esc(dateTime(x.created_at))}</td></tr>`).join(""),s.status==="success"?"The content ledger is live and currently contains no research briefs.":"No content brief data is available.")}
  ${table("Generation Runs","Durable generation attempts; visibility only",g.length,["Run","Brief","Provider","Model","Prompt","Status","Attempts","Updated"],g.map(x=>`<tr><td class="operations-reference">${esc(x.id||"—")}</td><td class="operations-reference">${esc(x.content_brief_id||"—")}</td><td>${esc(x.provider||"—")}</td><td>${esc(x.model||"—")}</td><td>${esc(x.prompt_version||"—")}</td><td><span class="status-pill ${operationStatusClass(x.status)}">${esc(x.status||"UNKNOWN")}</span></td><td>${esc(x.attempt_count??0)}</td><td>${esc(dateTime(x.updated_at))}</td></tr>`).join(""),s.status==="success"?"No durable content generation runs have been recorded.":"No generation-run data is available.")}
  ${table("Generated Assets","Generated content already persisted by the backend",a.length,["Artifact","Title","Type","Status","Brief","Generation Run","Created"],a.map(x=>`<tr><td class="operations-reference">${esc(x.id||"—")}</td><td class="content-copy-cell">${esc(contentText(x.title,72)||"—")}</td><td>${esc(x.content_type||"—")}</td><td><span class="status-pill ${operationStatusClass(x.status)}">${esc(x.status||"UNKNOWN")}</span></td><td class="operations-reference">${esc(x.content_brief_id||"—")}</td><td class="operations-reference">${esc(x.generation_run_id||"—")}</td><td>${esc(dateTime(x.created_at))}</td></tr>`).join(""),s.status==="success"?"No generated content artifacts are currently recorded.":"No generated-asset data is available.")}
  ${table("Content Evaluations","Recorded quality and compliance decisions; no decision is made in the UI",e.length,["Evaluation","Artifact","Overall","Decision","Approved","Policy","Evaluator","Created"],e.map(x=>`<tr><td class="operations-reference">${esc(x.id||"—")}</td><td class="operations-reference">${esc(x.artifact_id||"—")}</td><td>${esc(x.overall_score??"—")}</td><td><span class="status-pill ${operationStatusClass(x.decision)}">${esc(x.decision||"UNKNOWN")}</span></td><td>${x.approved===true?"Yes":x.approved===false?"No":"—"}</td><td>${esc(x.policy_version||"—")}</td><td>${esc(x.evaluator_version||"—")}</td><td>${esc(dateTime(x.created_at))}</td></tr>`).join(""),s.status==="success"?"No content evaluations are currently recorded.":"No evaluation data is available.")}
  ${table("Repurposing Runs","Source-to-result lineage for repurposed content",r.length,["Run","Source Artifact","Source Evaluation","Target Type","Channel","Status","Result Artifact","Updated"],r.map(x=>`<tr><td class="operations-reference">${esc(x.id||"—")}</td><td class="operations-reference">${esc(x.source_artifact_id||"—")}</td><td class="operations-reference">${esc(x.source_evaluation_id||"—")}</td><td>${esc(x.target_content_type||"—")}</td><td>${esc(x.channel_intent||"—")}</td><td><span class="status-pill ${operationStatusClass(x.status)}">${esc(x.status||"UNKNOWN")}</span></td><td class="operations-reference">${esc(x.result_artifact_id||"—")}</td><td>${esc(dateTime(x.updated_at))}</td></tr>`).join(""),s.status==="success"?"No content repurposing runs are currently recorded.":"No repurposing data is available.")}
  <div class="authority-wall"><strong>Visibility only.</strong> UIF5C reads records already persisted by the content subsystem. It exposes no generation launch, evaluation decision, repurposing launch, publishing, scheduling, outreach, allocation, or execution authority.</div></div>`
}

/* UIF5E — Read-Only Attribution Lineage Visibility */
function attributionLineage(){
  const s=state.attribution;
  const publications=s.publications||[];
  const contexts=s.contexts||[];
  const clicks=s.clicks||[];
  const facts=s.facts||[];
  const earningLinks=s.earningLinks||[];
  const settlements=s.settlementLinks||[];
  const conversionFacts=facts.filter(row=>String(row.fact_kind||"").toUpperCase()==="CONVERSION_REPORTED").length;
  const table=(title,copy,count,headers,rows,empty)=>`<section class="card"><div class="card-head"><div><h4>${esc(title)}</h4><p>${esc(copy)}</p></div><span class="state-badge">${count} loaded</span></div><div class="card-body table-wrap">${count?`<table class="data-table operations-table"><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>`:`<div class="empty">${esc(empty)}</div>`}</div></section>`;

  return `<div class="section-stack">
    <div class="hero">
      <div>
        <h3>Attribution</h3>
        <p>Read-only durable reference lineage from publication → context/link/click → conversion fact → earning → payout settlement. UIF5E shows only explicit stored references and never infers attribution from timestamps, URLs, or presentation order.</p>
      </div>
      <span class="live-badge">${state.backendOnline&&s.status==="success"?"● ATTRIBUTION LINEAGE LIVE":"● ATTRIBUTION DATA UNAVAILABLE"}</span>
    </div>

    <div class="grid operations-kpi-grid">
      ${kpi("Publications",publications.length,"Explicit publication authority bindings")}
      ${kpi("Contexts",contexts.length,"Program + publication attribution contexts")}
      ${kpi("Clicks",clicks.length,"Durable attributed click records")}
      ${kpi("Conversion Facts",conversionFacts,"Loaded CONVERSION_REPORTED facts")}
      ${kpi("Earning Links",earningLinks.length,"Explicit conversion → earning references")}
      ${kpi("Settlements",settlements.length,"Explicit earning → payout settlement references")}
    </div>

    ${s.status==="error"?`<div class="operations-error">${esc(s.error||"Attribution lineage API unavailable.")}</div>`:""}

    ${table(
      "Attribution Publications",
      "Explicit bindings to legacy publishing queue or durable distribution-run authority",
      publications.length,
      ["Publication","Publishing Queue","Distribution Run","Created"],
      publications.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td>${esc(row.legacy_publishing_queue_id??"—")}</td><td class="operations-reference">${esc(row.distribution_run_id||"—")}</td><td>${esc(dateTime(row.created_at))}</td></tr>`).join(""),
      s.status==="success"?"The attribution publication ledger is live and currently empty.":"No attribution publication data is available."
    )}

    ${table(
      "Attribution Contexts",
      "Durable program-to-publication contexts; no context is reconstructed in the UI",
      contexts.length,
      ["Context","Program","Publication","Created"],
      contexts.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td>#${esc(row.affiliate_program_id??"—")}</td><td class="operations-reference">${esc(row.attribution_publication_id||"—")}</td><td>${esc(dateTime(row.created_at))}</td></tr>`).join(""),
      s.status==="success"?"The attribution context ledger is live and currently empty.":"No attribution context data is available."
    )}

    ${table(
      "Attributed Clicks",
      "Recorded click references bound to an existing context and affiliate link",
      clicks.length,
      ["Click","Context","Affiliate Link","Source","Occurred","Recorded"],
      clicks.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.attribution_context_id||"—")}</td><td>#${esc(row.affiliate_link_id??"—")}</td><td>${esc(row.source_namespace||"—")}</td><td>${esc(dateTime(row.occurred_at))}</td><td>${esc(dateTime(row.recorded_at))}</td></tr>`).join(""),
      s.status==="success"?"The durable attributed-click ledger is live and currently empty.":"No attributed-click data is available."
    )}

    ${table(
      "Immutable Attribution Facts",
      "Append-only facts preserving publication, link, click, conversion and correction references",
      facts.length,
      ["Fact","Kind","Context","Click","Affiliate Link","Conversion","Supersedes","Occurred"],
      facts.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td><span class="status-pill ${operationStatusClass(row.fact_kind)}">${esc(row.fact_kind||"UNKNOWN")}</span></td><td class="operations-reference">${esc(row.attribution_context_id||"—")}</td><td class="operations-reference">${esc(row.attribution_click_id||"—")}</td><td>${row.affiliate_link_id==null?"—":`#${esc(row.affiliate_link_id)}`}</td><td>${row.affiliate_conversion_id==null?"—":`#${esc(row.affiliate_conversion_id)}`}</td><td class="operations-reference">${esc(row.supersedes_fact_id||"—")}</td><td>${esc(dateTime(row.occurred_at))}</td></tr>`).join(""),
      s.status==="success"?"The immutable attribution-fact ledger is live and currently empty.":"No attribution facts are available."
    )}

    ${table(
      "Conversion → Earning Links",
      "Immutable references from a conversion fact to its durable affiliate earning",
      earningLinks.length,
      ["Earning Link","Fact","Conversion","Earning","Source","Observed","Recorded"],
      earningLinks.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.attribution_fact_id||"—")}</td><td>#${esc(row.affiliate_conversion_id??"—")}</td><td>#${esc(row.affiliate_earning_id??"—")}</td><td>${esc(row.source_namespace||"—")}</td><td>${esc(dateTime(row.observed_at))}</td><td>${esc(dateTime(row.recorded_at))}</td></tr>`).join(""),
      s.status==="success"?"No durable conversion-to-earning attribution links are currently recorded.":"No earning-link data is available."
    )}

    ${table(
      "Earning → Payout Settlement Links",
      "Observed successful settlement lineage through explicit earning, payout and payout-attempt references",
      settlements.length,
      ["Settlement","Earning Link","Earning","Payout","Attempt","Source","Observed"],
      settlements.map(row=>`<tr><td class="operations-reference">${esc(row.id||"—")}</td><td class="operations-reference">${esc(row.attribution_earning_link_id||"—")}</td><td>#${esc(row.affiliate_earning_id??"—")}</td><td>#${esc(row.affiliate_payout_id??"—")}</td><td>#${esc(row.affiliate_payout_attempt_id??"—")}</td><td>${esc(row.source_namespace||"—")}</td><td>${esc(dateTime(row.observed_at))}</td></tr>`).join(""),
      s.status==="success"?"No durable earning-to-payout settlement links are currently recorded.":"No settlement-link data is available."
    )}

    <div class="authority-wall"><strong>Visibility only.</strong> UIF5E reads immutable attribution references already persisted by M10. It does not infer joins from timestamps or URLs, mutate or correct facts, reattribute conversions, mark earnings paid, process payouts, calculate profit, allocate budget, or execute anything.</div>
  </div>`;
}

/* UIF5F — Frozen M10 Economic Performance Visibility */
function economicPerformance(){
  const surface=state.performance;
  const rows=surface.rows||[];
  const profitable=rows.filter(row=>Number(row.operating_profit)>0).length;
  const loss=rows.filter(row=>Number(row.operating_profit)<0).length;
  const zero=rows.filter(row=>Number(row.operating_profit)===0).length;

  return `<div class="section-stack">
    <div class="hero">
      <div>
        <h3>Economic Performance</h3>
        <p>Read-only projection of frozen M10 economic truth at native-currency aggregate grain. Each currency remains separate; UIF5F performs no FX conversion, recomputation, allocation, accounting close, or ROI calculation.</p>
      </div>
      <span class="live-badge">${state.backendOnline&&surface.status==="success"?"● ECONOMIC PROJECTION LIVE":"● ECONOMIC DATA UNAVAILABLE"}</span>
    </div>

    <div class="grid operations-kpi-grid">
      ${kpi("Currency Buckets",rows.length,"One frozen projection row per native currency")}
      ${kpi("Profitable",profitable,"Operating profit above zero")}
      ${kpi("Loss",loss,"Operating profit below zero")}
      ${kpi("Zero",zero,"Operating profit exactly zero")}
    </div>

    ${surface.status==="error"?`<div class="operations-error">${esc(surface.error||"Economic performance API unavailable.")}</div>`:""}

    <section class="card">
      <div class="card-head">
        <div>
          <h4>Frozen Operating-Profit Projection</h4>
          <p>Net realized commission → direct cost → contribution profit → shared allocation → global allocation → operating profit</p>
        </div>
        <span class="state-badge">${rows.length} currency ${rows.length===1?"bucket":"buckets"}</span>
      </div>
      <div class="card-body table-wrap">
        ${rows.length?`<table class="data-table operations-table">
          <thead><tr><th>Currency</th><th>Net Realized</th><th>Direct Cost</th><th>Contribution Profit</th><th>Shared Cost</th><th>Allocated Contribution</th><th>Global Cost</th><th>Operating Profit</th></tr></thead>
          <tbody>${rows.map(row=>`<tr>
            <td><strong>${esc(row.currency||"—")}</strong></td>
            <td>${esc(row.net_realized_commission??"—")}</td>
            <td>${esc(row.directly_attributable_cost??"—")}</td>
            <td>${esc(row.contribution_profit??"—")}</td>
            <td>${esc(row.allocated_shared_cost??"—")}</td>
            <td>${esc(row.allocated_contribution_profit??"—")}</td>
            <td>${esc(row.allocated_global_cost??"—")}</td>
            <td><strong>${esc(row.operating_profit??"—")}</strong></td>
          </tr>`).join("")}</tbody>
        </table>`:`<div class="empty">${surface.status==="success"?"The frozen operating-profit projection is live and currently returned no native-currency buckets.":"No economic performance projection is available."}</div>`}
      </div>
    </section>

    ${rows.length?`<section class="card"><div class="card-head"><div><h4>Projection Semantics</h4><p>Frozen M10 authority carried through the transport unchanged</p></div><span class="state-badge">READ ONLY</span></div><div class="card-body"><div class="mini-list">${rows.map(row=>`<div class="mini-row"><span>${esc(row.currency||"—")}</span><span>${esc(row.semantics||"—")}</span></div>`).join("")}</div></div></section>`:""}

    <div class="authority-wall"><strong>Projection visibility only.</strong> UIF5F calls frozen M10 operating-profit projection authority at aggregate native-currency grain. It does not create or finalize costs, allocate shared or global costs, convert FX, produce accounting-final P&amp;L or ROI, alter attribution, infer recommendations or approvals, allocate budget, assign traffic, or execute anything.</div>
  </div>`;
}

/* UIF5A — Existing Operations Visibility */
function operationStatusClass(status){
  const value=String(status||"").toLowerCase();
  if(["published","paid","completed","approved","succeeded","success"].includes(value))return "status-online";
  if(["queued","pending","processing","scheduled","running","created"].includes(value))return "status-busy";
  if(["failed","rejected","cancelled","canceled","error"].includes(value))return "status-offline";
  return "";
}

function dateTime(value){
  if(!value)return "—";
  const parsed=new Date(value);
  return Number.isNaN(parsed.getTime())?String(value):parsed.toLocaleString();
}

function distribution(){
  const surface=state.distribution;
  const rows=surface.queue||[];
  const published=rows.filter(row=>String(row.status||"").toLowerCase()==="published").length;
  const waiting=rows.filter(row=>["queued","pending","scheduled","processing"].includes(String(row.status||"").toLowerCase())).length;
  const failed=rows.filter(row=>["failed","error","cancelled","canceled"].includes(String(row.status||"").toLowerCase())).length;

  return `<div class="section-stack">
    <div class="hero">
      <div>
        <h3>Distribution</h3>
        <p>Read-only visibility into the existing publisher queue. UIF5A does not expose publish, retry, schedule, dispatch, or execution controls.</p>
      </div>
      <span class="live-badge">${state.backendOnline&&surface.status==="success"?"● PUBLISHER QUEUE LIVE":"● QUEUE UNAVAILABLE"}</span>
    </div>

    <div class="grid operations-kpi-grid">
      ${kpi("Loaded Queue Items",rows.length,"Live /publisher/queue records")}
      ${kpi("Published",published,"Status reported by publisher queue")}
      ${kpi("Waiting",waiting,"Queued, pending, scheduled or processing")}
      ${kpi("Failed",failed,"Failed or cancelled queue records")}
    </div>

    ${surface.status==="error"?`<div class="operations-error">${esc(surface.error||"Publishing queue API unavailable.")}</div>`:""}

    <section class="card">
      <div class="card-head">
        <div><h4>Publishing Queue</h4><p>Existing backend records only</p></div>
        <span class="state-badge">${rows.length} loaded</span>
      </div>
      <div class="card-body table-wrap">
        ${rows.length?`<table class="data-table operations-table">
          <thead><tr><th>Queue</th><th>Asset</th><th>Title</th><th>Channel</th><th>Status</th><th>Created</th><th>Published URL</th></tr></thead>
          <tbody>${rows.map(row=>`<tr>
            <td>#${esc(row.queue_id??"—")}</td>
            <td>#${esc(row.content_asset_id??"—")}</td>
            <td>${esc(row.title||"—")}</td>
            <td>${esc(row.channel||"—")}</td>
            <td><span class="status-pill ${operationStatusClass(row.status)}">${esc(row.status||"UNKNOWN")}</span></td>
            <td>${esc(dateTime(row.created_at))}</td>
            <td class="operations-reference">${esc(row.published_url||"—")}</td>
          </tr>`).join("")}</tbody>
        </table>`:`<div class="empty">${surface.status==="success"?"The publisher queue is live and currently empty.":"No publisher queue data is available."}</div>`}
      </div>
    </section>

    <div class="authority-wall"><strong>Visibility only.</strong> UIF5A intentionally does not expose the existing publisher mutation endpoint. Publishing authority remains where the backend already defines it.</div>
  </div>`;
}

function commissions(){
  const surface=state.commissions;
  const earnings=surface.earnings||[];
  const payouts=surface.payouts||[];
  const paidEarnings=earnings.filter(row=>String(row.status||"").toLowerCase()==="paid").length;
  const completedPayouts=payouts.filter(row=>["paid","completed"].includes(String(row.status||"").toLowerCase())).length;
  const hasError=surface.earningsStatus==="error"||surface.payoutsStatus==="error";

  return `<div class="section-stack">
    <div class="hero">
      <div>
        <h3>Commissions & Payouts</h3>
        <p>Read-only settlement visibility from the existing affiliate earnings and payout APIs. Monetary values are displayed in their recorded native currency; UIF5A performs no FX conversion.</p>
      </div>
      <span class="live-badge">${state.backendOnline&&!hasError?"● SETTLEMENT DATA LIVE":"● PARTIAL / UNAVAILABLE"}</span>
    </div>

    <div class="grid operations-kpi-grid">
      ${kpi("Loaded Earnings",earnings.length,"Latest up to 100 records")}
      ${kpi("Paid Earnings",paidEarnings,"Status reported by earnings API")}
      ${kpi("Loaded Payouts",payouts.length,"Latest up to 100 records")}
      ${kpi("Completed Payouts",completedPayouts,"Paid or completed payout status")}
    </div>

    ${surface.earningsStatus==="error"?`<div class="operations-error">Affiliate earnings API unavailable.</div>`:""}
    ${surface.payoutsStatus==="error"?`<div class="operations-error">Affiliate payouts API unavailable.</div>`:""}

    <section class="card">
      <div class="card-head">
        <div><h4>Affiliate Earnings</h4><p>Commission records returned by /affiliate-earnings/</p></div>
        <span class="state-badge">${earnings.length} loaded</span>
      </div>
      <div class="card-body table-wrap">
        ${earnings.length?`<table class="data-table operations-table">
          <thead><tr><th>Earning</th><th>Program</th><th>Conversion</th><th>Commission</th><th>Currency</th><th>Status</th><th>Payout Reference</th><th>Paid / Created</th></tr></thead>
          <tbody>${earnings.map(row=>`<tr>
            <td>#${esc(row.id??"—")}</td>
            <td>#${esc(row.affiliate_program_id??"—")}</td>
            <td>#${esc(row.conversion_id??"—")}</td>
            <td>${esc(row.commission_amount??"—")}</td>
            <td>${esc(row.currency||"—")}</td>
            <td><span class="status-pill ${operationStatusClass(row.status)}">${esc(row.status||"UNKNOWN")}</span></td>
            <td class="operations-reference">${esc(row.payout_reference||"—")}</td>
            <td>${esc(dateTime(row.paid_at||row.created_at))}</td>
          </tr>`).join("")}</tbody>
        </table>`:`<div class="empty">${surface.earningsStatus==="success"?"The earnings API is live and currently returned no records.":"No earnings data is available."}</div>`}
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <div><h4>Affiliate Payouts</h4><p>Payout records returned by /affiliate-payouts/</p></div>
        <span class="state-badge">${payouts.length} loaded</span>
      </div>
      <div class="card-body table-wrap">
        ${payouts.length?`<table class="data-table operations-table">
          <thead><tr><th>Payout</th><th>Program</th><th>Amount</th><th>Currency</th><th>Status</th><th>Payout Reference</th><th>Paid / Created</th></tr></thead>
          <tbody>${payouts.map(row=>`<tr>
            <td>#${esc(row.id??"—")}</td>
            <td>#${esc(row.affiliate_program_id??"—")}</td>
            <td>${esc(row.total_amount??"—")}</td>
            <td>${esc(row.currency||"—")}</td>
            <td><span class="status-pill ${operationStatusClass(row.status)}">${esc(row.status||"UNKNOWN")}</span></td>
            <td class="operations-reference">${esc(row.payout_reference||"—")}</td>
            <td>${esc(dateTime(row.paid_at||row.created_at))}</td>
          </tr>`).join("")}</tbody>
        </table>`:`<div class="empty">${surface.payoutsStatus==="success"?"The payout API is live and currently returned no records.":"No payout data is available."}</div>`}
      </div>
    </section>

    <div class="authority-wall"><strong>Read-only settlement surface.</strong> UIF5A does not expose mark-paid, create payout, process, complete, fail, or retry mutations. It only displays records already returned by the backend.</div>
  </div>`;
}

function agents(){return `<div class="section-stack"><div><h3 class="section-title">AI Agents</h3><p class="section-copy">Read-only visibility into the registered workforce.</p></div><section class="card"><div class="card-head"><div><h4>Runtime Workers</h4><p>Shared workforce registry</p></div><span class="state-badge">${state.workers.length} workers</span></div><div class="card-body">${workers(30)}</div></section><section class="card"><div class="card-head"><div><h4>Service Execution</h4><p>Restricted automation boundary</p></div></div><div class="card-body"><div class="callout">Service execution is restricted to authenticated automation workers.</div></div></section></div>`}
function activity(){return `<div class="section-stack"><div><h3 class="section-title">Activity</h3><p class="section-copy">Latest runtime events from /system/events.</p></div><section class="card"><div class="card-body">${events(50)}</div></section></div>`}

function utcInputValue(){const now=new Date();const localOffset=now.getTimezoneOffset()*60000;return new Date(now.getTime()-localOffset).toISOString().slice(0,16)}
function dimensionLabel(dimensions){return dimensions.map(item=>`${item.name}: ${item.value===null?"null":item.value}`).join(" · ")}
function recommendationRows(){
  const rec=state.recommendations;
  if(rec.status==="loading")return `<div class="recommendation-state"><div class="spinner"></div><strong>Projecting frozen M11A8 recommendations…</strong><span>Read-only calculation. Nothing is being approved or executed.</span></div>`;
  if(rec.status==="error")return `<div class="recommendation-state error-state"><strong>Projection failed</strong><span>${esc(rec.error||"The recommendation projection could not be completed.")}</span></div>`;
  if(rec.status==="success"&&rec.rows.length===0)return `<div class="recommendation-state"><strong>No Tier-1 recommendations</strong><span>The frozen projection returned an empty recommendation set for this exact request.</span></div>`;
  if(rec.status!=="success")return `<div class="recommendation-state"><strong>Ready for projection</strong><span>Enter the exact grain, currency, evaluation time and policy values, then project the frozen M11A8 recommendation set.</span></div>`;
  const tied=rec.rows.length>1;
  return `<div class="recommendation-results"><div class="result-banner"><div><span class="result-kicker">${tied?"Equal Tier-1 recommendations":"Tier-1 recommendation"}</span><strong>${rec.rows.length} ${rec.rows.length===1?"candidate":"candidates"} returned</strong></div><span class="state-badge status-online">READ ONLY</span></div>
  <div class="recommendation-grid">${rec.rows.map((row,index)=>`<article class="recommendation-card"><div class="recommendation-card-head"><div><span class="tier-badge">TIER ${esc(row.preference_tier)}</span><h4>Recommendation ${index+1}</h4><p>${esc(dimensionLabel(row.dimensions||[]))}</p></div><div class="profit-block"><span>Operating Profit</span><strong>${esc(row.currency)} ${esc(row.operating_profit)}</strong></div></div>
  <div class="recommendation-detail-grid"><div><span>Evaluated at</span><strong>${esc(row.evaluated_at)}</strong></div><div><span>Eligibility policy</span><strong>${esc(row.eligibility_policy_version)}</strong></div><div><span>Comparison policy</span><strong>${esc(row.comparison_policy_version)}</strong></div><div><span>Recommendation policy</span><strong>${esc(row.recommendation_policy_version)}</strong></div></div>
  <details class="provenance"><summary>Frozen provenance</summary><dl><div><dt>Eligibility fingerprint</dt><dd>${esc(row.eligibility_policy_fingerprint)}</dd></div><div><dt>Source preference contract</dt><dd>${esc(row.source_ordered_preference_contract_version)}</dd></div><div><dt>Recommendation contract</dt><dd>${esc(row.recommendation_proposal_contract_version)}</dd></div><div><dt>Recommendation semantics</dt><dd>${esc(row.recommendation_proposal_semantics)}</dd></div></dl></details></article>`).join("")}</div>
  ${tied?`<div class="tie-notice"><strong>No winner selected.</strong> Every returned row is equally Tier-1 according to frozen M11A8. Presentation order is preserved and is not an economic preference between tied rows.</div>`:""}</div>`
}

function recommendations(){return `<div class="section-stack"><div class="hero recommendation-hero"><div><h3>Economic Recommendations</h3><p>Project the frozen M11A8 recommendation set through the UIF2A read-only API. Every semantic input is visible and operator supplied.</p></div><span class="live-badge">${state.backendOnline?"● UIF2A API READY":"● BACKEND OFFLINE"}</span></div>
<div class="recommendation-layout"><section class="card recommendation-form-card"><div class="card-head"><div><h4>Projection Request</h4><p>No policy values are silently supplied by the server.</p></div><span class="state-badge">M11A8 → UIF2A</span></div><div class="card-body"><form id="recommendation-form" class="recommendation-form"><div class="form-grid">
<label class="field"><span>Dimensions <em>required</em></span><input id="rec-dimensions" type="text" placeholder="affiliate_program" required><small>Comma-separated dimension grain.</small></label>
<label class="field"><span>Currency <em>required</em></span><input id="rec-currency" type="text" placeholder="USD" required><small>Exact native currency; no FX conversion.</small></label>
<label class="field span-2"><span>Evaluated at <em>required</em></span><div class="inline-field"><input id="rec-evaluated-at" type="datetime-local" required><button class="secondary compact" type="button" data-action="utc-now">Use current time</button></div><small>Sent as an explicit UTC timestamp.</small></label>
<label class="field span-2"><span>Eligibility policy version <em>required</em></span><input id="rec-eligibility-version" type="text" placeholder="qualification" required></label>
<label class="field"><span>Minimum settled earnings <em>required</em></span><input id="rec-earning-count" type="number" min="0" step="1" placeholder="1" required></label>
<label class="field"><span>Minimum settled conversions <em>required</em></span><input id="rec-conversion-count" type="number" min="0" step="1" placeholder="1" required></label>
<label class="field"><span>Minimum settlement links <em>required</em></span><input id="rec-link-count" type="number" min="0" step="1" placeholder="1" required></label>
<label class="field"><span>Minimum attribution clicks <em>optional</em></span><input id="rec-click-count" type="number" min="0" step="1" placeholder="null"><small>Blank is explicitly null.</small></label>
<label class="field"><span>Maximum observation age (hours) <em>optional</em></span><input id="rec-observation-hours" type="number" min="0" step="1" placeholder="null"><small>Blank is null; otherwise ISO-8601 duration.</small></label>
<label class="field"><span>Comparison policy version <em>required</em></span><input id="rec-comparison-version" type="text" placeholder="qualification-pairwise-v1" required></label>
<label class="field span-2"><span>Recommendation policy version <em>required</em></span><input id="rec-recommendation-version" type="text" placeholder="qualification-recommendation-v1" required></label>
</div><div class="form-actions"><button class="primary" type="submit">Project Recommendations</button><span class="authority-note">Read-only projection · no approval · no allocation · no execution</span></div></form></div></section>
<section class="card recommendation-output-card"><div class="card-head"><div><h4>Tier-1 Output</h4><p>All and only rows returned by frozen M11A8.</p></div><span class="state-badge">${state.recommendations.status==="success"?"LIVE RESULT":"WAITING"}</span></div><div class="card-body">${recommendationRows()}</div></section></div></div>`}

function renderRecommendationOutput(){
  const card=document.querySelector(".recommendation-output-card");

  if(!card){
    render();
    return;
  }

  const badge=card.querySelector(".card-head .state-badge");
  if(badge){
    badge.textContent=
      state.recommendations.status==="loading"?"PROJECTING":
      state.recommendations.status==="success"?"LIVE RESULT":
      state.recommendations.status==="error"?"ERROR":
      "WAITING";
  }

  const body=card.querySelector(".card-body");
  if(body){
    body.innerHTML=recommendationRows();
  }
}

async function projectRecommendations(){
  const form=document.getElementById("recommendation-form");if(!form||!form.reportValidity())return;
  const dimensions=document.getElementById("rec-dimensions").value.split(",").map(v=>v.trim()).filter(Boolean);
  if(!dimensions.length){toast("Enter at least one dimension.");return}
  const clickRaw=document.getElementById("rec-click-count").value.trim();
  const observationRaw=document.getElementById("rec-observation-hours").value.trim();
  const payload={dimensions,currency:document.getElementById("rec-currency").value.trim(),evaluated_at:new Date(document.getElementById("rec-evaluated-at").value).toISOString(),eligibility_policy:{policy_version:document.getElementById("rec-eligibility-version").value.trim(),minimum_settled_earning_count:Number(document.getElementById("rec-earning-count").value),minimum_settled_conversion_count:Number(document.getElementById("rec-conversion-count").value),minimum_settlement_link_count:Number(document.getElementById("rec-link-count").value),minimum_attribution_click_count:clickRaw===""?null:Number(clickRaw),maximum_settlement_observation_age:observationRaw===""?null:`PT${Number(observationRaw)}H`},comparison_policy_version:document.getElementById("rec-comparison-version").value.trim(),recommendation_policy_version:document.getElementById("rec-recommendation-version").value.trim()};
  state.approvals={
    status:"idle",
    outcome:null,
    error:null,
    request:null,
    form:{
      decisionState:"",
      selected:[],
      actorReference:"",
      decisionReference:"",
      decidedAt:"",
      policyVersion:""
    }
  };
  state.experiments=emptyExperimentState();
  state.recommendations={status:"loading",rows:[],error:null,request:payload};renderRecommendationOutput();
  try{
    const response=await requestApi("/optimization/recommendations/project",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!response||response.status===401)return;
    const body=await response.json().catch(()=>null);
    if(!response.ok){state.recommendations={status:"error",rows:[],error:typeof body?.detail==="string"?body.detail:`Projection failed with HTTP ${response.status}.`,request:payload};renderRecommendationOutput();return}
    state.recommendations={status:"success",rows:Array.isArray(body?.recommendations)?body.recommendations:[],error:null,request:payload};renderRecommendationOutput();
  }catch(error){console.error("Recommendation projection error:",error);state.recommendations={status:"error",rows:[],error:"The UIF2A recommendation API is unreachable.",request:payload};renderRecommendationOutput()}
}

function renderApprovalOutput(){
  const card=document.querySelector(".approval-output-card");
  if(!card){render();return}

  const badge=card.querySelector(".card-head .state-badge");
  if(badge){
    badge.textContent=
      state.approvals.status==="loading"?"PROJECTING":
      state.approvals.status==="success"?"LIVE RESULT":
      state.approvals.status==="error"?"ERROR":
      "WAITING";
  }

  const body=card.querySelector(".card-body");
  if(body)body.innerHTML=approvalOutcome();
}

function captureApprovalForm(){
  const form=state.approvals.form;
  const actor=document.getElementById("approval-actor");
  const reference=document.getElementById("approval-reference");
  const decided=document.getElementById("approval-decided-at");
  const policy=document.getElementById("approval-policy-version");

  if(actor)form.actorReference=actor.value;
  if(reference)form.decisionReference=reference.value;
  if(decided)form.decidedAt=decided.value;
  if(policy)form.policyVersion=policy.value;

  form.selected=Array.from(document.querySelectorAll(".approval-row-select:checked"))
    .map(input=>Number(input.dataset.index))
    .filter(Number.isInteger)
    .sort((a,b)=>a-b);
}

async function projectApprovalDecision(){
  const rec=state.recommendations;
  const formElement=document.getElementById("approval-form");
  if(!formElement||!formElement.reportValidity())return;

  captureApprovalForm();
  const form=state.approvals.form;

  if(rec.status!=="success"||!rec.request){
    toast("Project Recommendations first.");
    return;
  }

  if(!["APPROVED","REJECTED","DEFERRED"].includes(form.decisionState)){
    toast("Select APPROVED, REJECTED, or DEFERRED.");
    return;
  }

  if(form.decisionState==="APPROVED"&&form.selected.length===0){
    toast("APPROVED requires at least one Tier-1 selection.");
    return;
  }

  const approvedDimensions=form.decisionState==="APPROVED"
    ? rec.rows
        .map((row,index)=>({row,index}))
        .filter(item=>form.selected.includes(item.index))
        .map(item=>(item.row.dimensions||[]).map(dim=>({name:dim.name,value:dim.value})))
    : [];

  const payload={
    proposal_request:rec.request,
    approval_decision:{
      decision_state:form.decisionState,
      approved_dimensions:approvedDimensions,
      actor_reference:form.actorReference.trim(),
      decision_reference:form.decisionReference.trim(),
      decided_at:new Date(form.decidedAt).toISOString()
    },
    approval_policy:{
      policy_version:form.policyVersion.trim()
    }
  };

  state.experiments=emptyExperimentState();
  state.approvals.request=payload;
  state.approvals.status="loading";
  state.approvals.outcome=null;
  state.approvals.error=null;
  renderApprovalOutput();

  try{
    const response=await requestApi("/optimization/approvals/decide",{
      method:"POST",
      cache:"no-store",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });

    if(!response||response.status===401)return;
    const body=await response.json().catch(()=>null);

    if(!response.ok){
      state.approvals.status="error";
      state.approvals.error=typeof body?.detail==="string"
        ? body.detail
        : `Approval projection failed with HTTP ${response.status}.`;
      renderApprovalOutput();
      return;
    }

    state.approvals.status="success";
    state.approvals.outcome=body;
    state.approvals.error=null;
    renderApprovalOutput();
  }catch(error){
    console.error("Approval projection error:",error);
    state.approvals.status="error";
    state.approvals.outcome=null;
    state.approvals.error="The UIF3A approval API is unreachable.";
    renderApprovalOutput();
  }
}

const renderers={overview,offers,opportunities,audience:audienceIntelligence,content:contentOperations,distribution,attribution:attributionLineage,commissions,performance:economicPerformance,recommendations,approvals,experiments,agents,activity};

function render(){if(state.auth.status!=="authenticated")return;document.getElementById("page-title").textContent=viewMeta[state.activeView]||"Overview";document.getElementById("view-container").innerHTML=(renderers[state.activeView]||overview)();bindActions()}
function activate(view){if(state.auth.status!=="authenticated")return;state.activeView=view;document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));document.getElementById("sidebar").classList.remove("open");if(view==="approvals"&&!state.approvals.form.decidedAt)state.approvals.form.decidedAt=utcInputValue();render();if(view==="recommendations"){const input=document.getElementById("rec-evaluated-at");if(input&&!input.value)input.value=utcInputValue()}}
function bindActions(){
  document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{
    const a=b.dataset.action;
    if(a==="activity")activate("activity");
    if(a==="opportunity-run")await loadOpportunityRun(b.dataset.runId);
    if(a==="opportunity-evidence")await loadOpportunityEvidence(b.dataset.candidateId);
    if(a==="go-recommendations")activate("recommendations");
    if(a==="go-approvals")activate("approvals");
    if(a==="go-experiments")activate("experiments");
    if(a==="utc-now"){
      const input=document.getElementById("rec-evaluated-at");
      if(input)input.value=utcInputValue();
    }
    if(a==="approval-now"){
      state.approvals.form.decidedAt=utcInputValue();
      const input=document.getElementById("approval-decided-at");
      if(input)input.value=state.approvals.form.decidedAt;
    }
    if(a==="experiment-now"){
      captureExperimentForm();
      const index=Number(b.dataset.index);
      ensureExperimentDesignForms();
      if(Number.isInteger(index)&&state.experiments.form.designs[index]){
        state.experiments.form.designs[index].designedAt=utcInputValue();
        const input=document.getElementById(`exp-designed-at-${index}`);
        if(input)input.value=state.experiments.form.designs[index].designedAt;
      }
    }
  });

  const recommendationForm=document.getElementById("recommendation-form");
  if(recommendationForm)recommendationForm.onsubmit=async event=>{
    event.preventDefault();
    await projectRecommendations();
  };

  const approvalForm=document.getElementById("approval-form");
  if(approvalForm){
    approvalForm.onsubmit=async event=>{
      event.preventDefault();
      await projectApprovalDecision();
    };

    approvalForm.querySelectorAll('input[name="approval-state"]').forEach(input=>{
      input.onchange=()=>{
        captureApprovalForm();
        state.approvals.form.decisionState=input.value;
        if(input.value!=="APPROVED")state.approvals.form.selected=[];
        render();
      };
    });

    approvalForm.querySelectorAll(".approval-row-select").forEach(input=>{
      input.onchange=()=>{
        captureApprovalForm();
        input.closest(".approval-candidate")?.classList.toggle("selected",input.checked);
      };
    });

    ["approval-actor","approval-reference","approval-decided-at","approval-policy-version"].forEach(id=>{
      const input=document.getElementById(id);
      if(input)input.oninput=captureApprovalForm;
    });
  }

  const experimentForm=document.getElementById("experiment-form");
  if(experimentForm){
    experimentForm.onsubmit=async event=>{
      event.preventDefault();
      await projectExperimentDesigns();
    };

    experimentForm.querySelectorAll(".experiment-row-select").forEach(input=>{
      input.onchange=()=>{
        captureExperimentForm();
        render();
      };
    });

    const policy=document.getElementById("experiment-policy-version");
    if(policy)policy.oninput=captureExperimentForm;

    experimentForm.querySelectorAll(
      'input[id^="exp-"], textarea[id^="exp-"]'
    ).forEach(input=>{
      input.oninput=captureExperimentForm;
    });
  }
}
document.addEventListener("DOMContentLoaded",()=>{document.querySelectorAll(".nav-item").forEach(b=>b.onclick=()=>activate(b.dataset.view));document.getElementById("refresh-button").onclick=()=>refreshData();document.getElementById("sign-out-button").onclick=logout;document.getElementById("menu-button").onclick=()=>document.getElementById("sidebar").classList.toggle("open");bootstrapSession();setInterval(()=>{if(state.auth.status==="authenticated")refreshData({silent:true})},8000)});
