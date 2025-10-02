const socket = io();

// UI buttons
document.getElementById('btnAddPackage').onclick = () => socket.emit('add_package');
document.getElementById('btnRemovePackage').onclick = () => socket.emit('remove_package');
document.getElementById('btnAddRobot').onclick = () => socket.emit('add_robot');
document.getElementById('btnRemoveRobot').onclick = () => socket.emit('remove_robot');

// UI KPI elements
const totalPackagesEl = document.getElementById('total_packages');
const totalRobotsEl = document.getElementById('total_robots');
const pathsEl = document.getElementById('paths');
const poolEl = document.getElementById('robot_pool');
const statusAreaEl = document.getElementById('robot_status_area');
const logsAreaEl = document.getElementById('robot_live_logs_area');

// ...

// --- Path Setup ---
function buildPaths() {
  pathsEl.innerHTML = '';
  PATH_LENGTHS.forEach((len, i) => {
    const pathDiv = document.createElement('div');
    pathDiv.className = 'path';
    pathDiv.id = 'path_' + i;
    // NOTE: Updated path rendering to match new styles
    pathDiv.innerHTML = `
      <div class="path-label">Path ${i + 1} — ${len} m</div>
      <div class="lane top"><div class="arrows">→→→→→</div></div>
      <div class="lane bottom"><div class="arrows">←←←←←</div></div>
      <div class="robot-progress"><div class="bar" id="progressbar_${i}"></div></div>
    `;
    pathsEl.appendChild(pathDiv);
  });
}
buildPaths();

function robotLog(msg) {
    if (!logsAreaEl) return;
    const p = document.createElement('div');
    p.textContent = msg; 

    // Basic coloring based on Python log level string
    if (msg.includes("[ERROR]")) {
        p.className = "log-error";
    } else if (msg.includes("[WARNING]")) {
        p.className = "log-warning";
    } else {
        p.className = "log-info";
    }

    logsAreaEl.appendChild(p);
    logsAreaEl.scrollTop = logsAreaEl.scrollHeight;
}

function updateRobots(robots){
  const totalRobotsEl = document.getElementById('total_robots');
  const poolEl = document.getElementById('robot_pool');
  const statusAreaEl = document.getElementById('robot_status_area');
    
  poolEl.innerHTML = '';
  statusAreaEl.innerHTML = '';

  // 1. Remove all existing path chips before updating
  document.querySelectorAll('.robot-chip').forEach(el => el.remove());
  
  // 2. Insert new chips/status lines
  robots.forEach(r => {
    
    const distance = r.path !== null ? Math.round(r.distance) : 0;
    const packageId = r.packageId;
    const speed = r.speed ? r.speed.toFixed(1) : '0.0';
    const pathLabel = r.path === null ? '-' : (r.path + 1);

    // --- A. Update Live Robot Status Area ---
    const d = document.createElement('div');
    d.className = 'robot-status-item';
    d.innerHTML = `
        <span class="robot-id">R${r.id}</span>
        <span class="status-line">
            <span class="label">Status:</span> 
            <strong class="status-value">${r.status.replace(/_/g, ' ').toUpperCase()}</strong>
        </span>
        <span class="status-line">
            <span class="label">Package:</span> 
            <strong>${packageId || '-'}</strong>
        </span>
        <span class="status-line">
            <span class="label">Path:</span> 
            <strong>${pathLabel}</strong>
            <span class="label">Dist:</span> 
            <strong>${distance} m</strong>
            <span class="label">Speed:</span> 
            <strong>${speed} m/s</strong>
        </span>
    `;
    statusAreaEl.appendChild(d);

    // --- B. Update Path Visualization / Parked Pool ---
    if (r.path !== null) {
      // Robot is ON A PATH
      
      let chip = document.getElementById('chip_' + r.id);
      if (!chip) {
        chip = document.createElement('div');
        chip.className = 'robot-chip';
        chip.id = 'chip_' + r.id;
        const parent = document.getElementById('path_' + r.path);
        parent.appendChild(chip);
      }
      
      // Determine package visibility based on status
      const isCarryingPackage = (
          r.status.includes('moving_to_B') || 
          r.status.includes('waiting_at_A_with_package') || 
          r.status.includes('returning_with_package') // Denied delivery returns with package
      );
      
      const packageLabel = isCarryingPackage ? 'P' : '';
      
      // Update Chip Content (Robot ID + Package Chip based on status)
      chip.innerHTML = `R${r.id}` + (packageLabel ? `<div class="package-chip">${packageLabel}</div>` : '');

      // Horizontal position based on distance / path length
      const progressPercent = Math.min((r.distance / PATH_LENGTHS[r.path]) * 100, 100);
      chip.style.left = `calc(${progressPercent}% - 20px)`; 

      // Lane Logic: Top (Forward) vs. Bottom (Return)
      const isForward = (
          r.status.includes('moving_to_B') || 
          r.status.includes('waiting_at_A')
      );
      
      let chipTop;
      if (isForward) {
          // Top lane: Moving A -> B
          chipTop = '12px';
      } else {
          // Bottom lane: Returning B -> A (status='returning' or 'returning_with_package')
          chipTop = '42px';
      }
      chip.style.top = chipTop;

      // Update progress bar
      const barEl = document.getElementById(`progressbar_${r.path}`);
      if (barEl) {
          barEl.style.width = progressPercent + '%';
      }

    } else {
      // Robot is IDLE (Parked)
      const parkedChip = document.createElement('div');
      parkedChip.className = 'parked-robot';
      parkedChip.innerText = 'R' + r.id;
      poolEl.appendChild(parkedChip);
    }
  });
  
  // Update total robot count KPI
  totalRobotsEl.innerText = robots.length;
}


// --- SocketIO Listener ---
socket.on('state_update', data=>{
  // Update total package KPI
  totalPackagesEl.innerText = data.packages;
  
  // Update robots (handles both status area and path/pool visualization)
  updateRobots(data.robots);
});

socket.on("robot_live_log", (data) => {
    robotLog(data.msg); 
});