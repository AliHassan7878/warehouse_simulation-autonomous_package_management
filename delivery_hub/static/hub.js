const socket = io();

// Get the element where logs will be displayed
const slotsUsedEl = document.getElementById('slots_used');
const totalSlotsEl = document.getElementById('total_slots');
const processedCountEl = document.getElementById('processed_count');
const liveLogsEl = document.getElementById('live_logs'); // Assuming this is the log container

function log(msg) {
  const p = document.createElement('div');
  p.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  liveLogsEl.appendChild(p);
  // Keep the log scrolled to the bottom
  liveLogsEl.scrollTop = liveLogsEl.scrollHeight;
}

// =======================================================
// 🚀 FIX: Listener for logs sent from the Python backend 🚀
// =======================================================
socket.on("live_log", (data) => {
    // 'data' contains the dictionary sent by LiveLogHandler: {"msg": "..."}
    log(data.msg); 
});

// =======================================================
// Existing Listeners (Using log function for visibility)
// =======================================================

// Hub updates: slots used & packages processed
socket.on("hub_update", (data) => {
    log(`HUB UPDATE: ${data.event.toUpperCase()} | Slots: ${data.slots_used}/${data.total_slots}`); 
    
    document.getElementById("slots").innerText = 
        `Slots Used: ${data.slots_used}/${data.total_slots}`;

    const list = document.getElementById("processed-list");
    if (list && data.event === "processed") {
        const item = document.createElement("li");
        item.textContent = `Package ${data.package.packageId} processed (${data.package.weight}kg, ${data.package.dimension})`;
        list.appendChild(item);
    }
});


// Slot Status Broadcast (Free or Full)
socket.on("slot_status", (data) => {
    log(`STATUS: ${data.status} (${data.slots_used}/${data.total_slots})`);
    // Update individual elements if they exist
    if (slotsUsedEl) slotsUsedEl.innerText = data.slots_used;
    if (totalSlotsEl) totalSlotsEl.innerText = data.total_slots;
});

// Hub Event (Accepted, Full, SLOT_FREED)
socket.on("hub_event", (data) => {
    if (data.event === "accepted") {
        log(`🚚 Delivery ACCEPTED: Robot ${data.robot_id} for Package ${data.package_id}`);
    } else if (data.event === "full") {
        log(`🛑 Delivery DENIED: Slots FULL for Package ${data.package_id}`);
    } else if (data.event === "SLOT_FREED") {
        log(`✅ SLOT FREED after processing Package ${data.package_id}`);
    }
});


// Optional: show connection status
socket.on("connect", () => log("📡 Connected to Delivery Hub"));
socket.on("disconnect", () => log("❌ Disconnected from Delivery Hub"));