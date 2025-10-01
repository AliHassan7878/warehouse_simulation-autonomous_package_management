const socket = io();

// UI buttons
document.getElementById('btnAddPackage').onclick = () => socket.emit('add_package');
document.getElementById('btnRemovePackage').onclick = () => socket.emit('remove_package');
document.getElementById('btnAddRobot').onclick = () => socket.emit('add_robot');
document.getElementById('btnRemoveRobot').onclick = () => socket.emit('remove_robot');

// Paths
const pathsEl = document.getElementById('paths');

function buildPaths() {
  pathsEl.innerHTML = '';
  PATH_LENGTHS.forEach((len, i) => {
    const pathDiv = document.createElement('div');
    pathDiv.className = 'path';
    pathDiv.id = 'path_' + i;
    pathDiv.innerHTML = `
      <div class="path-label">Path ${i + 1} — ${len} m</div>
      <div class="lane top"><div class="arrows">→→→</div></div>
      <div class="lane bottom"><div class="arrows">←←←</div></div>
      <div class="robot-progress"><div class="bar" id="progressbar_${i}"></div></div>
    `;
    pathsEl.appendChild(pathDiv);
  });
}
buildPaths();

// --- Remove queue updates ---
// function updateQueue(len, cap){ … }  <- remove this

function updateRobots(robots){
  const pool = document.getElementById('robot_pool');
  pool.innerHTML = '';
  const sarea = document.getElementById('robot_status_area');
  sarea.innerHTML = '';

  // remove old robot chips
  document.querySelectorAll('.robot-chip').forEach(el => el.remove());

  robots.forEach(r => {
    // --- Update Status Area ---
    const d = document.createElement('div');
    d.className = 'status';

    let distance = '-';
    let packageId = r.packageId || '-';
    if (r.path !== null) {
      // NOTE: We use r.distance directly as it's already in meters (Python code)
      distance = Math.round(r.distance); 
    }

    const speed = r.speed ? r.speed.toFixed(1) : '0.0';
    const pathLabel = r.path === null ? '-' : (r.path + 1);

    d.innerText = `R${r.id} — Package: ${packageId} — Status: ${r.status} — Path: ${pathLabel} — Distance: ${distance} m — Speed: ${speed} m/s`;
    sarea.appendChild(d);

    // --- Update Path Visualization ---
    if (r.path !== null) {
      let chip = document.getElementById('chip_' + r.id);
      if (!chip) {
        chip = document.createElement('div');
        chip.className = 'robot-chip small';
        chip.id = 'chip_' + r.id;
        chip.innerText = 'R' + r.id;
        const parent = document.getElementById('path_' + r.path);
        parent.appendChild(chip);
      }

      // Horizontal position based on distance / path length
      // Since r.distance is 0.0 when waiting at A, progressPercent is 0, keeping it at the start.
      const progressPercent = Math.min((r.distance / PATH_LENGTHS[r.path]) * 100, 100);
      chip.style.left = progressPercent + '%';

      // 🛑 FIX: Lane based on status (Top lane for moving to B and WAITING at A)
      let chipTop;
      if (r.status === 'moving_to_B' || r.status === 'waiting_at_A_with_package') {
          // Top lane (forward lane)
          chipTop = '8px';
      } else {
          // Bottom lane (return lane, includes 'returning' and 'returning_with_package')
          chipTop = '30px';
      }
      chip.style.top = chipTop;

      chip.title = `Package: ${packageId}, Status: ${r.status}, Speed: ${speed} m/s, Distance: ${distance} m`;
    } else {
      // Robot is idle, remove chip from path
      const chip = document.getElementById('chip_' + r.id);
      if (chip) chip.remove();
    }
  });
}

socket.on('state_update', data=>{
  document.getElementById('packages').innerText = data.packages;
  updateRobots(data.robots);
});
