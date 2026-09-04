const API_URL="http://127.0.0.1:8000";
const state={
  backendOnline:false,
  health:null,
  dashboard:null,
  workers:[],
  events:[],
  products:[],
  activeView:"overview",
  recommendations:{status:"idle",rows:[],error:null,request:null},
  approvals:{
    status:"idle",
    outcome:null,
    error:null,
    form:{
      decisionState:"",
      selected:[],
      actorReference:"",
      decisionReference:"",
      decidedAt:"",
      policyVersion:""
    }
  }
};
const viewMeta={overview:"Overview",offers:"Products & Offers",opportunities:"Opportunities",audience:"Audience",content:"Content Assets",distribution:"Distribution",attribution:"Attribution",commissions:"Commissions & Payouts",performance:"Economic Performance",recommendations:"Recommendations",approvals:"Approval Queue",experiments:"Experiments",agents:"AI Agents",activity:"Activity"};

async function api(endpoint,options={}){
  try{const response=await fetch(`${API_URL}${endpoint}`,{cache:"no-store",...options});if(!response.ok)throw new Error(`${response.status} ${response.statusText}`);return await response.json()}
  catch(error){console.error(`API error ${endpoint}:`,error);return null}
}
function esc(v){return String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;")}
function toast(message){const el=document.getElementById("toast");el.textContent=message;el.classList.add("show");clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove("show"),2400)}
function setBackendStatus(online){state.backendOnline=online;["sidebar-dot","top-dot"].forEach(id=>{const el=document.getElementById(id);el.classList.toggle("online",online);el.classList.toggle("offline",!online)});document.getElementById("sidebar-status").textContent=online?"Backend online":"Backend offline";document.getElementById("connection-text").textContent=online?"Live backend":"Disconnected"}
function normalizeProducts(data){if(Array.isArray(data))return data;if(Array.isArray(data?.items))return data.items;if(Array.isArray(data?.products))return data.products;return []}
function statusClass(status){const s=String(status||"").toUpperCase();return s==="ONLINE"?"status-online":s==="BUSY"?"status-busy":"status-offline"}
function eventClass(type){const t=String(type||"INFO").toUpperCase();return t==="SUCCESS"?"success":(t==="ERROR"||t==="FAILED")?"error":(t==="WARNING"||t==="WARN")?"warning":""}
function time(value){if(!value)return"--:--";const d=new Date(value);return Number.isNaN(d.getTime())?"--:--":d.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}

async function refreshData({silent=false}={}){
  const [health,dashboard,workersData,eventsData,productsData]=await Promise.all([api("/health"),api("/system/dashboard"),api("/system/workers"),api("/system/events"),api("/products/")]);
  state.health=health;state.dashboard=dashboard;state.workers=Array.isArray(workersData)?workersData:[];state.events=Array.isArray(eventsData)?eventsData:[];state.products=normalizeProducts(productsData);
  setBackendStatus(Boolean(health?.success));document.getElementById("sidebar-version").textContent=health?.success?"FastAPI connected":"127.0.0.1:8000";
  if(!["recommendations","approvals"].includes(state.activeView))render();
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
<section class="card"><div class="card-head"><div><h4>Operator Attention</h4><p>Human-visible boundaries</p></div></div><div class="card-body"><div class="mini-list"><div class="mini-row"><span>Recommendation API surface</span><span class="state-badge status-online">LIVE</span></div><div class="mini-row"><span>Approval API surface</span><span class="state-badge status-online">LIVE</span></div><div class="mini-row"><span>Experiment design API surface</span><span class="state-badge">Pending</span></div></div></div></section></div>`}
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
        <div class="card-head"><div><h4>Frozen M11A9 Outcome</h4><p>Exact UIF3A response</p></div><span class="state-badge">${state.approvals.status==="success"?"LIVE RESULT":"WAITING"}</span></div>
        <div class="card-body">${approvalOutcome()}</div>
      </section>
    </div>
  </div>`;
}
function experiments(){return `<div class="section-stack"><div><h3 class="section-title">Experiments</h3><p class="section-copy">Read-only experiment design from frozen M11A10.</p></div><section class="card"><div class="card-head"><div><h4>Experiment Design</h4><p>Hypothesis, control, treatment, success measure, observation window</p></div><span class="state-badge">DESIGN ONLY</span></div><div class="card-body"><div class="callout">There is deliberately no Launch button. M11A10 has no execution, traffic, budget, scheduling, or platform authority.</div></div></section></div>`}
function agents(){return `<div class="section-stack"><div><h3 class="section-title">AI Agents</h3><p class="section-copy">Live workforce plus existing discovery mission controls.</p></div><section class="card"><div class="card-head"><div><h4>Runtime Workers</h4><p>Shared workforce registry</p></div><span class="state-badge">${state.workers.length} workers</span></div><div class="card-body">${workers(30)}</div></section><section class="card"><div class="card-head"><div><h4>Mission Controls</h4><p>Existing system commands</p></div></div><div class="card-body"><div class="toolbar"><button class="primary" data-action="product-discovery">Launch Product Discovery</button><button class="secondary" data-action="affiliate-discovery">Launch Affiliate Discovery</button></div></div></section></div>`}
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
    form:{
      decisionState:"",
      selected:[],
      actorReference:"",
      decisionReference:"",
      decidedAt:"",
      policyVersion:""
    }
  };
  state.recommendations={status:"loading",rows:[],error:null,request:payload};renderRecommendationOutput();
  try{
    const response=await fetch(`${API_URL}/optimization/recommendations/project`,{method:"POST",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
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

  state.approvals.status="loading";
  state.approvals.outcome=null;
  state.approvals.error=null;
  renderApprovalOutput();

  try{
    const response=await fetch(`${API_URL}/optimization/approvals/decide`,{
      method:"POST",
      cache:"no-store",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });

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

const renderers={overview,offers,opportunities:()=>pending("Opportunities","Opportunity intelligence and scoring views."),audience:()=>pending("Audience","Audience intelligence, signals, profiles and qualification."),content:()=>pending("Content Assets","Research briefs, generated content, evaluations and repurposed assets."),distribution:()=>pending("Distribution","Prepared content, distribution runs and delivery status."),attribution:()=>pending("Attribution","Content → click → conversion → commission → payout → profit lineage.",true),commissions:()=>pending("Commissions & Payouts","Revenue settlement and payout visibility.",true),performance:()=>pending("Economic Performance","Revenue-rooted operating-profit and optimization evidence.",true),recommendations,approvals,experiments,agents,activity};

function render(){document.getElementById("page-title").textContent=viewMeta[state.activeView]||"Overview";document.getElementById("view-container").innerHTML=(renderers[state.activeView]||overview)();bindActions()}
function activate(view){state.activeView=view;document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));document.getElementById("sidebar").classList.remove("open");if(view==="approvals"&&!state.approvals.form.decidedAt)state.approvals.form.decidedAt=utcInputValue();render();if(view==="recommendations"){const input=document.getElementById("rec-evaluated-at");if(input&&!input.value)input.value=utcInputValue()}}
async function postCommand(endpoint,label){toast(`${label} requested…`);const r=await api(endpoint,{method:"POST"});toast(r?.message||`${label} failed. Check FastAPI console.`);if(r)await refreshData({silent:true})}
function bindActions(){
  document.querySelectorAll("[data-action]").forEach(b=>b.onclick=async()=>{
    const a=b.dataset.action;
    if(a==="activity")activate("activity");
    if(a==="product-discovery")await postCommand("/system/command/run-product-discovery","Product discovery");
    if(a==="affiliate-discovery")await postCommand("/system/command/run-affiliate","Affiliate discovery");
    if(a==="go-recommendations")activate("recommendations");
    if(a==="utc-now"){
      const input=document.getElementById("rec-evaluated-at");
      if(input)input.value=utcInputValue();
    }
    if(a==="approval-now"){
      state.approvals.form.decidedAt=utcInputValue();
      const input=document.getElementById("approval-decided-at");
      if(input)input.value=state.approvals.form.decidedAt;
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
}
document.addEventListener("DOMContentLoaded",()=>{document.querySelectorAll(".nav-item").forEach(b=>b.onclick=()=>activate(b.dataset.view));document.getElementById("refresh-button").onclick=()=>refreshData();document.getElementById("menu-button").onclick=()=>document.getElementById("sidebar").classList.toggle("open");refreshData({silent:true});setInterval(()=>refreshData({silent:true}),8000)});
