/*
    ETM Affiliate OS
    Mission Control Frontend

    Connects dashboard UI
    with FastAPI backend.
*/


const API_URL = "http://127.0.0.1:8000";



async function api(endpoint) {

    try {

        const response = await fetch(
            `${API_URL}${endpoint}`
        );

        return await response.json();

    }

    catch(error) {

        console.error(
            "API Error:",
            error
        );

        return null;

    }

}





function setText(
    id,
    value
){

    const element =
        document.getElementById(id);


    if(element){

        element.innerText = value;

    }

}





async function loadSystem(){

    const data =
        await api(
            "/system/status"
        );


    if(!data) return;


    setText(
        "system-status",
        "🟢 ONLINE"
    );

}





async function loadWorkers(){

    const container =
        document.getElementById(
            "workers"
        );


    const data =
        await api(
            "/system/workers"
        );


    if(!container || !data)
        return;


    container.innerHTML = "";


    if(data.length === 0){

        container.innerHTML =
            "No workers registered.";

        return;

    }


    data.forEach(worker => {


        const item =
            document.createElement(
                "div"
            );


        item.innerHTML = `

            <strong>
                ${worker.name}
            </strong>

            <br>

            Status:
            ${worker.status}

            <br>

            Missions:
            ${worker.missions_completed}

        `;


        container.appendChild(
            item
        );


    });

}





async function loadEvents(){

    const container =
        document.getElementById(
            "events"
        );


    const data =
        await api(
            "/system/events"
        );


    if(!container || !data)
        return;


    container.innerHTML = "";


    data.slice(-10)
    .reverse()
    .forEach(event => {


        const item =
            document.createElement(
                "div"
            );


        item.innerText =
            "• " + event.event;


        container.appendChild(
            item
        );


    });

}





async function loadExecutions(){

    const data =
        await api(
            "/system/executions"
        );


    if(!data)
        return;


    setText(
        "mission-count",
        data.length
    );


}





async function loadQueue(){

    const data =
        await api(
            "/system/queue"
        );


    if(!data)
        return;


    setText(
        "worker-count",
        data.completed || 0
    );


}





async function launchAffiliate(){

    const button =
        document.getElementById(
            "run-affiliate"
        );


    if(button){

        button.innerText =
            "Launching...";

        button.disabled = true;

    }


    await fetch(
        `${API_URL}/system/command/run-affiliate`,
        {
            method:"POST"
        }
    );


    await refresh();


    if(button){

        button.innerText =
            "▶ Launch Affiliate Discovery";

        button.disabled = false;

    }


}





async function refresh(){

    await loadSystem();

    await loadWorkers();

    await loadEvents();

    await loadExecutions();

    await loadQueue();

}





document.addEventListener(
    "DOMContentLoaded",
    ()=>{


        const button =
            document.getElementById(
                "run-affiliate"
            );


        if(button){

            button.onclick =
                launchAffiliate;

        }


        refresh();


        setInterval(
            refresh,
            5000
        );


    }
);