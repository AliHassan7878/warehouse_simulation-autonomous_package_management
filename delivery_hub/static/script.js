const socket = io();

// UI Elements
const slotsUsedEl = document.getElementById('slots_used_kpi');
const totalSlotsEl = document.getElementById('total_slots_kpi');
const processedCountEl = document.getElementById('processed_count_kpi');
const liveLogsEl = document.getElementById('live_logs');
const slotVisualEl = document.getElementById('slot-visual');

// --- Visualization Functions (Simplified) ---

function renderSlots(used, total) {
    slotVisualEl.innerHTML = '';
    for (let i = 0; i < total; i++) {
        const slot = document.createElement('div');
        slot.className = 'slot ' + (i < used ? 'used' : 'free');
        slotVisualEl.appendChild(slot);
    }
}

// --- Logging Function ---

function log(msg, type = "info") {
    const p = document.createElement('div');
    p.textContent = msg;

    // Apply CSS classes based on log content
    if (msg.includes("[ERROR]")) {
        p.className = "log-warning";
    } else if (msg.includes("[WARNING]")) {
        p.className = "log-warning";
    } else if (type === "accepted") {
        p.className = "log-accepted";
    } else {
        p.className = "log-info";
    }

    liveLogsEl.appendChild(p);
    liveLogsEl.scrollTop = liveLogsEl.scrollHeight;
}


// --- SocketIO Listeners ---

// 1. Python Live Logs
socket.on("live_log", (data) => {
    log(data.msg);
});

// 2. Initial Data Load
socket.on("initial_data", (data) => {
    log("Received initial state from server.", "info");
    slotsUsedEl.innerText = data.slots_used;
    totalSlotsEl.innerText = data.total_slots;
    processedCountEl.innerText = data.processed_count;
    renderSlots(data.slots_used, data.total_slots);
});

// 3. Hub updates (on package processing)
socket.on("hub_update", data => {
    // Update KPIs and visuals
    slotsUsedEl.innerText = data.slots_used;
    totalSlotsEl.innerText = data.total_slots;
    processedCountEl.innerText = data.processed_count;
    renderSlots(data.slots_used, data.total_slots);

    // Update the processed list
    const list = document.getElementById("processed-list");
    if (list && data.event === "processed") {
        const item = document.createElement("li");
        item.textContent = `Package ${data.package.packageId} processed (${data.package.weight}kg, ${data.package.dimension})`;
        list.prepend(item); // Prepend to show newest first
    }
});

// 4. Slot Status Broadcast
socket.on("slot_status", (data) => {
    renderSlots(data.slots_used, data.total_slots);
    slotsUsedEl.innerText = data.slots_used;
    totalSlotsEl.innerText = data.total_slots;
});

// 5. Hub Event (Accepted, Full, SLOT_FREED)
socket.on("hub_event", (data) => {
    if (data.event === "accepted") {
        log(`🚚 Delivery ACCEPTED: Robot ${data.robot_id} for Package ${data.package_id}`, "accepted");
        renderSlots(data.slots_used, data.total_slots);
        slotsUsedEl.innerText = data.slots_used;
    } else if (data.event === "full") {
        log(`🛑 Delivery DENIED: Slots FULL for Package ${data.package_id}`, "warning");
    } else if (data.event === "SLOT_FREED") {
        log(`✅ SLOT FREED after processing Package ${data.package_id}`, "accepted");
        renderSlots(data.slots_used, data.total_slots);
        slotsUsedEl.innerText = data.slots_used;
    }
});

// 6. Connection status
socket.on("connect", () => {
    log("📡 Connected to Delivery Hub");
    // Request initial data immediately upon connection
    socket.emit("request_initial_data");
});
socket.on("disconnect", () => log("❌ Disconnected from Delivery Hub", "warning"));