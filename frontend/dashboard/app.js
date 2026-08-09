/*
    ETM Affiliate OS
    Mission Control Frontend

    Connects dashboard UI
    with FastAPI backend.
*/


const API_URL = "http://127.0.0.1:8000";


/* =========================================================
   API
   ========================================================= */

async function api(endpoint, options = {}) {

    try {

        const response = await fetch(
            `${API_URL}${endpoint}`,
            options
        );


        if (!response.ok) {

            console.error(
                `API ${response.status}: ${endpoint}`
            );

            return null;

        }


        return await response.json();

    }

    catch (error) {

        console.error(
            "API Error:",
            error
        );

        return null;

    }

}


/* =========================================================
   HELPERS
   ========================================================= */

function setText(
    id,
    value
) {

    const element =
        document.getElementById(id);


    if (element) {

        element.innerText = value;

    }

}



function escapeHtml(value) {

    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");

}



function formatTime(timestamp) {

    if (!timestamp) {

        return "--:--:--";

    }


    const date =
        new Date(timestamp);


    if (Number.isNaN(
        date.getTime()
    )) {

        return "--:--:--";

    }


    return date.toLocaleTimeString(
        [],
        {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        }
    );

}



function eventIcon(type) {

    switch (
        String(type || "INFO").toUpperCase()
    ) {

        case "SUCCESS":

            return "✓";


        case "ERROR":

        case "FAILED":

            return "✕";


        case "WARNING":

        case "WARN":

            return "!";


        case "RUNNING":

            return "▶";


        default:

            return "•";

    }

}



function eventClass(type) {

    const normalized =
        String(
            type || "INFO"
        ).toLowerCase();


    return `event-${normalized}`;

}



/* =========================================================
   DASHBOARD
   ========================================================= */

async function loadDashboard() {

    const data =
        await api(
            "/system/dashboard"
        );


    if (!data) {

        return;

    }


    updateStats(data);

    updateActiveMission(data);

    updateLatestResults(data);

}



/* =========================================================
   STATS
   ========================================================= */

function updateStats(data) {

    setText(
        "system-status",
        "🟢 ONLINE"
    );


    setText(
        "worker-count",
        data.workers ?? 0
    );


    setText(
        "mission-count",
        data.running_missions ?? 0
    );


    /*
        Success rate is authoritative
        from the backend.

        The browser does NOT calculate
        this value.
    */

    const successRate =
        Number(
            data.success_rate ?? 100
        );


    setText(
        "success-rate",
        `${successRate}%`
    );

}



/* =========================================================
   WORKERS
   ========================================================= */

async function loadWorkers() {

    const container =
        document.getElementById(
            "workers"
        );


    if (!container) {

        return;

    }


    const data =
        await api(
            "/system/workers"
        );


    if (!data) {

        container.innerHTML =
            "Unable to load workers.";

        return;

    }


    container.innerHTML = "";


    if (data.length === 0) {

        container.innerHTML =
            "No workers registered.";

        return;

    }


    data.forEach(
        worker => {

            const item =
                document.createElement(
                    "div"
                );


            item.className =
                "worker-item";


            item.innerHTML = `

                <strong>
                    ${escapeHtml(
                        worker.name
                    )}
                </strong>

                <br>

                Status:
                ${escapeHtml(
                    worker.status
                )}

            `;


            container.appendChild(
                item
            );

        }
    );

}



/* =========================================================
   ACTIVE MISSION
   ========================================================= */

function updateActiveMission(data) {

    const container =
        document.getElementById(
            "active-mission"
        );


    if (!container) {

        return;

    }


    const execution =
        data.latest_execution;


    if (!execution) {

        container.innerHTML =
            "No active mission.";

        return;

    }


    const workflow =
        execution.workflow ||
        "Unknown";


    const status =
        execution.status ||
        "UNKNOWN";


    const normalizedStatus =
        String(
            status
        ).toUpperCase();


    const statusText =
        normalizedStatus === "SUCCESS"
            ? "COMPLETED"
            : normalizedStatus;


    container.innerHTML = `

        <div class="mission-status">

            <strong>
                ${escapeHtml(
                    workflow
                )}
            </strong>

            <br>

            Status:
            ${escapeHtml(
                statusText
            )}

            <br>

            Duration:
            ${Number(
                execution.duration || 0
            ).toFixed(3)}s

        </div>

    `;

}



/* =========================================================
   LATEST RESULTS
   ========================================================= */

function updateLatestResults(data) {

    const container =
        document.getElementById(
            "latest-results"
        );


    if (!container) {

        return;

    }


    const missionResult =
        data.latest_mission_result;


    if (!missionResult) {

        container.innerHTML =
            "No results yet.";

        return;

    }


    const workflow =
        missionResult.workflow ||
        "unknown";


    const success =
        missionResult.success;


    const workflowData =
        missionResult.data ||
        {};


    /*
        Current backend structure:

        mission_result
            ↓
        data
            ↓
        workflow result
            ↓
        data
            ↓
        products
    */


    const nestedData =
        workflowData.data ||
        {};


    const products =
        nestedData.products ||
        [];


    if (products.length === 0) {

        container.innerHTML = `

            <div class="result-summary">

                <strong>
                    ${escapeHtml(
                        workflow
                    )}
                </strong>

                <br>

                Status:
                ${success
                    ? "SUCCESS"
                    : "FAILED"
                }

                <br><br>

                No products discovered.

            </div>

        `;

        return;

    }


    const sortedProducts =
        [...products].sort(
            (a, b) =>
                Number(
                    b.opportunity_score || 0
                )
                -
                Number(
                    a.opportunity_score || 0
                )
        );


    const header = `

        <div class="result-header">

            <strong>
                TOP AFFILIATE OPPORTUNITIES
            </strong>

            <span>
                ${products.length}
                discovered
            </span>

        </div>

    `;


    const cards =
        sortedProducts
            .map(
                (
                    product,
                    index
                ) => {

                    const score =
                        Number(
                            product.opportunity_score || 0
                        );


                    const commission =
                        product.commission ?? 0;


                    const price =
                        product.price ?? 0;


                    return `

                        <div class="product-result">

                            <div class="product-rank">
                                #${index + 1}
                            </div>


                            <div class="product-info">

                                <strong>
                                    ${escapeHtml(
                                        product.name
                                    )}
                                </strong>

                                <span>
                                    ${escapeHtml(
                                        product.category
                                    )}
                                </span>

                            </div>


                            <div class="product-metrics">

                                <div>

                                    <small>
                                        Opportunity
                                    </small>

                                    <strong>
                                        ${score.toFixed(1)}
                                    </strong>

                                </div>


                                <div>

                                    <small>
                                        Commission
                                    </small>

                                    <strong>
                                        ${escapeHtml(
                                            commission
                                        )}%

                                    </strong>

                                </div>


                                <div>

                                    <small>
                                        Price
                                    </small>

                                    <strong>
                                        $${escapeHtml(
                                            price
                                        )}

                                    </strong>

                                </div>

                            </div>

                        </div>

                    `;

                }
            )
            .join("");


    container.innerHTML =
        header + cards;

}



/* =========================================================
   LIVE EVENTS
   ========================================================= */

async function loadEvents() {

    const container =
        document.getElementById(
            "events"
        );


    if (!container) {

        return;

    }


    const data =
        await api(
            "/system/events"
        );


    if (!data) {

        container.innerHTML =
            "Unable to load events.";

        return;

    }


    container.innerHTML = "";


    if (data.length === 0) {

        container.innerHTML =
            "Waiting...";

        return;

    }


    /*
        New structured event format:

        {
            event: "...",
            type: "SUCCESS",
            timestamp: "...",
            metadata: {}
        }
    */


    data
        .slice(-10)
        .reverse()
        .forEach(
            event => {

                const item =
                    document.createElement(
                        "div"
                    );


                const type =
                    String(
                        event.type ||
                        "INFO"
                    ).toUpperCase();


                const timestamp =
                    formatTime(
                        event.timestamp
                    );


                const icon =
                    eventIcon(
                        type
                    );


                item.className =
                    `event-item ${
                        eventClass(type)
                    }`;


                item.innerHTML = `

                    <div class="event-row">

                        <span class="event-time">
                            ${escapeHtml(
                                timestamp
                            )}
                        </span>


                        <span class="event-icon">
                            ${escapeHtml(
                                icon
                            )}
                        </span>


                        <span class="event-message">

                            ${escapeHtml(
                                event.event
                            )}

                        </span>

                    </div>


                    <div class="event-meta">

                        ${escapeHtml(
                            type
                        )}

                        ${
                            event.metadata?.workflow
                                ? " · " +
                                  escapeHtml(
                                      event.metadata.workflow
                                  )
                                : ""
                        }

                    </div>

                `;


                container.appendChild(
                    item
                );

            }
        );

}



/* =========================================================
   PRODUCT DISCOVERY
   ========================================================= */

async function launchProductDiscovery() {

    const button =
        document.getElementById(
            "run-product-discovery"
        );


    if (button) {

        button.innerText =
            "Launching...";

        button.disabled = true;

    }


    const response =
        await api(
            "/system/command/run-product-discovery",
            {
                method: "POST"
            }
        );


    if (response) {

        await refresh();

    }


    if (button) {

        button.innerText =
            "▶ Launch Product Discovery";

        button.disabled = false;

    }

}



/* =========================================================
   AFFILIATE DISCOVERY
   ========================================================= */

async function launchAffiliate() {

    const button =
        document.getElementById(
            "run-affiliate"
        );


    if (button) {

        button.innerText =
            "Launching...";

        button.disabled = true;

    }


    const response =
        await api(
            "/system/command/run-affiliate",
            {
                method: "POST"
            }
        );


    if (response) {

        await refresh();

    }


    if (button) {

        button.innerText =
            "▶ Launch Affiliate Discovery";

        button.disabled = false;

    }

}



/* =========================================================
   REFRESH
   ========================================================= */

async function refresh() {

    await loadDashboard();

    await loadWorkers();

    await loadEvents();

}



/* =========================================================
   STARTUP
   ========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        const affiliateButton =
            document.getElementById(
                "run-affiliate"
            );


        if (affiliateButton) {

            affiliateButton.onclick =
                launchAffiliate;

        }


        const productButton =
            document.getElementById(
                "run-product-discovery"
            );


        if (productButton) {

            productButton.onclick =
                launchProductDiscovery;

        }


        refresh();


        setInterval(
            refresh,
            5000
        );

    }
);