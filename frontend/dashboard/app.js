const API="http://127.0.0.1:8000/system";

async function fetchJSON(endpoint){

    const response=await fetch(API+endpoint);

    return await response.json();

}

async function refresh(){

    const status=await fetchJSON("/status");

    document.getElementById("status").innerHTML=

    `<strong>${status.status}</strong>`;

    const workers=await fetchJSON("/workers");

    document.getElementById("workers").innerHTML=

    workers.map(worker=>

    `<div class="worker">

    <span>${worker.name}</span>

    <span class="online">

    ${worker.status}

    </span>

    </div>`

    ).join("");

    const queue=await fetchJSON("/queue");

    document.getElementById("queue").textContent=

    JSON.stringify(queue,null,2);

    const memory=await fetchJSON("/memory");

    document.getElementById("memory").innerText=

    memory.items;

    const events=await fetchJSON("/events");

    document.getElementById("events").innerHTML=

    events.map(event=>

    `<li>${event.event}</li>`

    ).join("");

    const executions=await fetchJSON("/executions");

    document.getElementById("executions").innerHTML=

    executions.map(execution=>

    `<li>

    ${execution.workflow}

    -

    ${execution.status}

    </li>`

    ).join("");

    document.getElementById("last-update").innerText=

    "Updated: "+new Date().toLocaleTimeString();

}

document.getElementById(

"run-affiliate"

).onclick=async()=>{

    const response=

    await fetch(

    API+"/command/run-affiliate",

    {

        method:"POST"

    }

    );

    const result=

    await response.json();

    document.getElementById(

    "command-status"

    ).innerText=

    result.message;

    refresh();

};

refresh();

setInterval(

refresh,

3000

);