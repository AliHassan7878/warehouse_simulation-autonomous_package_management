const socket = io();

const slotsUsedEl = document.getElementById('slots_used');
const totalSlotsEl = document.getElementById('total_slots');
const processedCountEl = document.getElementById('processed_count');
const liveLogsEl = document.getElementById('live_logs');

function log(msg) {
  const p = document.createElement('div');
  p.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  liveLogsEl.appendChild(p);
  liveLogsEl.scrollTop = liveLogsEl.scrollHeight;
}

// Hub updates: slots used & packages processed
socket.on("hub_update", (data) => {
    console.log("Hub update:", data);
    document.getElementById("slots").innerText = 
        `Slots Used: ${data.slots_used}/${data.total_slots}`;

    const list = document.getElementById("processed-list");
    if (list) {
        const item = document.createElement("li");
        item.textContent = `Package ${data.package.packageId} processed (${data.package.weight}kg, ${data.package.dimension})`;
        list.appendChild(item);
    }
});


// No free slots broadcast
socket.on("no_free_slots", data => {
  log(`No free slots for package ${data.packageId}`);
});

// Individual robot delivery accepted
socket.onAny((event, data) => {
  if(event.startsWith("delivery_accepted_")){
    log(`Package ${data.packageId} accepted by hub`);
  }
});

// Optional: show connection status
socket.on("connect", () => log("Connected to Delivery Hub"));
socket.on("disconnect", () => log("Disconnected from Delivery Hub"));
