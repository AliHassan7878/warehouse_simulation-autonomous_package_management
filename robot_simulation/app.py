import eventlet
from flask import Flask, render_template
from flask_socketio import SocketIO
import random
import logging
import grpc
import os
import json

# GRPC IMPORTS (REQUIRES YOUR GENERATED FILES)
import delivery_pb2
import delivery_pb2_grpc

# CONSTANTS
PATH_LENGTHS = [9, 13, 21, 31]          # Length of available paths (in meters)
NUM_ROBOTS = 4                          # Initial number of robots
STEP_TIME = 0.05                        # Simulation time step (seconds per loop tick)
SAFE_GAP = 3.0                          # Minimum safe distance between robots (in meters)
MIN_SPEED_FACTOR = 0.25                 # Minimum fraction of original speed for collision avoidance
HUB_ADDR = "communication_hub:50051"    # Address of the gRPC Communication Hub
LOG_FILE = "robot_sim.log"
EVENT_FILE = "/tmp/hub_events.log" # Shared file for IPC

# LOGGING SETUP
class LiveLogHandler(logging.Handler):
    """Emit logs to SocketIO clients in real-time."""
    def emit(self, record):
        try:
            socketio.emit("robot_live_log", {"msg": self.format(record)}) 
        except Exception:
            pass

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s - %(message)s")

# Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# SocketIO/Live Log Handler
live_log_handler = LiveLogHandler()
live_log_handler.setFormatter(formatter)
logger.addHandler(live_log_handler)

# --- gRPC Connection ---
try:
    # Initialize the gRPC channel
    channel_sync = grpc.insecure_channel(HUB_ADDR)
    
    # Initialize the gRPC stub
    hub_stub_sync = delivery_pb2_grpc.DeliveryHubStub(channel_sync)
    
    logger.info("gRPC channel to Communication Hub established successfully.")

except Exception as e:
    logger.critical(f"FATAL ERROR: Failed to initialize gRPC connection to {HUB_ADDR}. Application halting.", exc_info=True)


# ROBOT SIMULATION CLASS
class RobotSimulation:
    """Manages the state and movement logic for all robots and packages."""
    
    def __init__(self, path_lengths: list[float], num_robots: int):
        """Initialize the simulation state."""
        self.path_lengths = path_lengths
        self.state = {
            "packages": 0,                       # Count of packages waiting for assignment
            "last_package_id": 0,                # Counter for generating unique package IDs
            "pending_packages": {},              # {packageId: None (unassigned) or robotId}
            "delivered_packages": set(),         # Set of package IDs confirmed delivered
            "robots": [{
                "id": i,
                "status": "idle",                # Current state
                "path": None,                    # Assigned path index
                "distance": 0.0,                 # Distance traveled on the path
                "speed": 0.0,                    # Current speed (m/s)
                "direction": None,               # "forward" or "backward"
                "packageId": None,               # ID of the package currently carried
                "_retry_flag": False             # Internal flag for delivery retry
            } for i in range(num_robots)],
        }

        self.file_pointer = 0

        logger.info("RobotSimulation initialized with %d robots.", num_robots)

    
    # Utility & Communication

    def emit_state(self):
        """Emits the current simulation state to the connected clients via SocketIO."""
        robots_ui = []
        for r in self.state["robots"]:
            robots_ui.append({
                "id": r["id"],
                "status": r["status"],
                "path": r["path"],
                "distance": round(r["distance"], 2),
                "speed": round(r["speed"], 2),
                "direction": r["direction"],
                "packageId": r["packageId"] if r["packageId"] is not None else "-"
            })

        socketio.emit("state_update", {
            "packages": self.state["packages"],
            "delivered_count": len(self.state["delivered_packages"]),
            "robots": robots_ui,
        })
        logger.debug("State emitted to UI.")
        
    def check_file_events(self):
        """Reads new events from the shared log file."""
        if not os.path.exists(EVENT_FILE):
            return

        try:
            with open(EVENT_FILE, "r") as f:
                # Seek to the last known position
                f.seek(self.file_pointer)
                
                new_lines = f.readlines()
                
                if new_lines:
                    for line in new_lines:
                        if line.strip():
                            # Process the JSON string back into an object
                            event_data = json.loads(line)
                            # Call the existing handler with the dictionary data
                            self._handle_hub_event(event_data) 

                    # Update the pointer to the current end position
                    self.file_pointer = f.tell()
        
        except Exception as e:
            logger.error(f"Error reading shared event file: {e}")
    
    def _get_collision_avoidance_speed(self, current_robot: dict) -> float:
        """Calculates the effective speed for collision avoidance."""
        effective_speed = current_robot["speed"]
        current_status = current_robot["status"]
        current_path = current_robot["path"]
        current_distance = current_robot["distance"]

        for other in self.state["robots"]:
            if other is current_robot or other["path"] != current_path:
                continue

            # Check robots moving in the same direction (forward or backward)
            is_forward = current_status == "moving_to_B" and other["status"] == "moving_to_B"
            is_backward = current_status in ("returning", "returning_with_package") and \
                          other["status"] in ("returning", "returning_with_package")

            if is_forward:
                # Current robot is behind 'other' robot
                gap = other["distance"] - current_distance
            elif is_backward:
                # Current robot is behind 'other' robot (closer to B)
                gap = current_distance - other["distance"]
            else:
                continue # Ignore robots moving in opposite directions

            if 0 < gap < SAFE_GAP:
                factor = max(gap / SAFE_GAP, MIN_SPEED_FACTOR)
                effective_speed = min(effective_speed, current_robot["speed"] * factor)
                logger.debug(
                    f"Robot {current_robot['id']} slowed by Robot {other['id']}. "
                    f"Gap: {gap:.2f}m. New speed factor: {factor:.2f}"
                )

        return effective_speed
        
    def try_deliver(self, robotId: int, packageId: int) -> str:
        """Sends a delivery request to the Communication Hub via gRPC."""
        try:

            req = delivery_pb2.DeliveryRequest(robot_id=robotId, package_id=packageId)
            
            resp = hub_stub_sync.SendDelivery(req, timeout=5)
            
            # Status from communication hub
            status = "UNKNOWN"
            if hasattr(resp, "message") and resp.message:
                status = resp.message
            elif hasattr(resp, "success"):
                status = "ACK" if resp.success else "FAIL"

            logger.info(f"Robot {robotId} delivery request for package {packageId} received response: {status}")
            return status
            
        except grpc.RpcError as e:
            logger.warning(f"gRPC delivery for robot {robotId} failed with RpcError: {e.details()}")
            return "failed"
        except Exception as e:
            logger.error(f"Unexpected error in try_deliver for robot {robotId}: {e}")
            return "failed"

    def _handle_hub_event(self, event):
            """Update robot states based on hub broadcast events (e.g., slot freed)."""
            logger.info(f"Handle hub event triggered....")
            # The Rust server sends the event_type field as a string
            event_type = event.get('event_type', '').upper()
            
            logger.info(f"Hub event received: Type={event_type}")

            if event_type == "FREE_SLOTS_AVAILABLE":
                # This is the general broadcast from the communication hub
                
                # Find ALL robots waiting after a failed delivery
                waiting_robots = [
                    r for r in self.state["robots"] 
                    if r["status"] == "waiting_at_A_with_package" 
                ]

                if waiting_robots:
                    # Set the internal flag on all waiting robots to trigger a retry
                    for r in waiting_robots:
                        r["_retry_flag"] = True
                        logger.info(f"Hub status 'FREE' detected. Setting retry flag for Robot {r['id']} (Pkg {r['packageId']}).")

    def add_package(self):
        """Adds a new package to the queue for assignment."""
        while True:
            # Generate a random integer between 1000 and 9999 for packageId
            package_id = random.randint(1000, 9999) 
            # Check if this ID is already being tracked
            if package_id not in self.state["pending_packages"] and package_id not in self.state["delivered_packages"]:
                break
        
        self.state["pending_packages"][package_id] = None
        self.state["packages"] += 1

        logger.info(f"Package added. Total packages waiting: {self.state['packages']}, ID={package_id}")
        self.emit_state()


    def remove_package(self):
        """Removes the last pending package."""
        if self.state["packages"] > 0:
            latest_unassigned_pkg = None
            
            sorted_pkg_ids = sorted(self.state["pending_packages"].keys(), reverse=True)
            for pkg_id in sorted_pkg_ids:
                if self.state["pending_packages"].get(pkg_id) is None:
                    latest_unassigned_pkg = pkg_id
                    break
            
            if latest_unassigned_pkg:
                self.state["pending_packages"].pop(latest_unassigned_pkg)
                self.state["packages"] -= 1
                logger.info(f"Package {latest_unassigned_pkg} removed. Remaining waiting: {self.state['packages']}")
            else:
                logger.warning("Attempted to remove package but none were unassigned.")

        self.emit_state()

    def add_robot(self):
        """Adds a new robot to the simulation."""
        new_id = len(self.state["robots"])
        self.state["robots"].append({
            "id": new_id,
            "status": "idle",
            "path": None,
            "distance": 0.0,
            "speed": 0.0,
            "direction": None,
            "packageId": None,
            "_retry_flag": False
        })
        logger.info("Robot %d added to the simulation.", new_id)
        self.emit_state()

    def remove_robot(self):
        """Removes the last robot from the simulation, if it is idle."""
        if not self.state["robots"]:
            logger.warning("Attempted to remove robot but none exist.")
            return

        last_robot = self.state["robots"][-1]
        if last_robot["status"] == "idle":
            removed_robot = self.state["robots"].pop()
            logger.info("Robot %d removed from the simulation.", removed_robot["id"])
        else:
            logger.warning(f"Robot {last_robot['id']} is not idle ({last_robot['status']}). Cannot remove.")

        self.emit_state()
    
    # Robot State Logic (Functions called from the main loop)
    
    def state_idle(self, r: dict):
        """Logic for the 'idle' state: waits for a package assignment."""
        r["speed"] = 0.0
        r["direction"] = None
        r["path"] = None

        if self.state["pending_packages"]:
            try:
                # Find the first unassigned package
                pkg_id = next(iter(
                    k for k, v in self.state["pending_packages"].items() 
                    if v is None and k not in self.state["delivered_packages"]
                ))
            except StopIteration:
                return

            # Assign the package
            r["packageId"] = pkg_id
            r["status"] = "moving_to_B"
            r["path"] = r["id"] % len(self.path_lengths)
            r["speed"] = random.choice([1.5, 2.0])
            r["direction"] = "forward"
            self.state["pending_packages"][pkg_id] = r["id"]
            
            logger.info(
                f"Robot {r['id']} assigned package {pkg_id} on path {r['path']} "
                f"(speed={r['speed']:.2f}m/s)"
            )

            logging.info(f"Robot {r['id']} moving to point A for package pick-up")
            self.emit_state()

    def state_moving_to_B(self, r: dict):
        """Logic for the 'moving_to_B' state: travels towards the destination."""
        
        path_len = self.path_lengths[r["path"]]
        effective_speed = self._get_collision_avoidance_speed(r)
        
        r["distance"] += effective_speed * STEP_TIME
        r["distance"] = min(r["distance"], path_len)

        if r["distance"] >= path_len:
            r["distance"] = path_len
            pkg_id = r["packageId"]
            
            status = self.try_deliver(r["id"], pkg_id)
            status_upper = (status or "").upper()
            
            if status_upper in ("ACK", "OK", "ACCEPTED", "ACCEPT"):
                # Success: Clears package, returns without package
                r["status"] = "returning"
                r["packageId"] = None
                # Decrement the package counter as it shows delivered
                self.state["packages"] -= 1
                self.state["pending_packages"].pop(pkg_id, None)
                self.state["delivered_packages"].add(pkg_id)
                logger.info(f"Robot {r['id']} successfully delivered package {pkg_id}.")
            else:
                # Failure: Keeps package, returns with it
                r["status"] = "returning_with_package"
                # r["packageId"] remains pkg_id (not cleared)
                logger.warning(f"Robot {r['id']} failed to deliver package {pkg_id}. Returning to A.")
                
            r["direction"] = "backward"
            self.emit_state()
        
    def state_returning(self, r: dict):
        """Logic for the 'returning' state: travels back to the hub A without a package."""
        
        path_len = self.path_lengths[r["path"]]
        effective_speed = self._get_collision_avoidance_speed(r)

        r["distance"] -= effective_speed * STEP_TIME
        r["distance"] = max(r["distance"], 0.0)

        if r["distance"] <= 0:
            r["distance"] = 0.0
            r["status"] = "idle"
            r["path"] = None
            r["direction"] = None
            logger.info(f"Robot {r['id']} returned to hub A and is now idle.")
            self.emit_state()

    def state_returning_with_package(self, r: dict):
        """Logic for the 'returning_with_package' state: travels back to A after a failed delivery."""
        
        path_len = self.path_lengths[r["path"]]
        effective_speed = self._get_collision_avoidance_speed(r)
        r["distance"] -= effective_speed * STEP_TIME
        r["distance"] = max(r["distance"], 0.0)

        if r["distance"] <= 0:
            r["distance"] = 0.0
            r["status"] = "waiting_at_A_with_package"
            r["direction"] = None
            self.emit_state()

    def state_waiting_at_A_with_package(self, r: dict):
        """Logic for the 'waiting_at_A_with_package' state: Wait free slots."""
        r["speed"] = 0.0
        r["path"] = r["id"] % len(self.path_lengths)

        if r.get("_retry_flag"):
            r["_retry_flag"] = False
            logger.info(f"Robot {r['id']} attempting delivery retry for package {r['packageId']}.")
            r["status"] = "retry_delivery"

            self.emit_state()
    
    def state_retry_delivery(self, r: dict):
        """
        Logic for the 'retry_delivery' state: Re-initializes movement variables 
        and transitions the robot back to the 'moving_to_B' state.
        """
        pkg_id = r["packageId"]
        
        # Reset movement variables to start from point A
        r["distance"] = 0.0          # Must start at 0.0 distance
        r["direction"] = "forward"   # Must move toward B
        
        # Assign the speed again
        if r["speed"] == 0.0:
            r["speed"] = random.choice([1.5, 2.0])
            
        # Transition to the 'moving_to_B' state
        r["status"] = "moving_to_B"
        
        logger.info(
            f"Robot {r['id']} successfully entered retry state. "
            f"Restarting delivery for package {pkg_id} on path {r['path']}."
        )
        self.emit_state()

    # Main Robot Movement Loop

    def robot_loop(self):
        """The main simulation loop, executing robot state logic."""
        logger.info("Robot simulation loop started.")
        while True:
            try:
                # Check event from the file written by another process 
                self.check_file_events()

                for r in self.state["robots"]:
                    if r["status"] == "idle":
                        self.state_idle(r)
                    elif r["status"] == "moving_to_B":
                        self.state_moving_to_B(r)
                    elif r["status"] == "returning":
                        self.state_returning(r)
                    elif r["status"] == "returning_with_package":
                        self.state_returning_with_package(r)
                    elif r["status"] == "waiting_at_A_with_package":
                        self.state_waiting_at_A_with_package(r)
                    elif r["status"] == "retry_delivery":
                        self.state_retry_delivery(r)
                
                self.emit_state() 
                eventlet.sleep(STEP_TIME)
                
            except Exception as e:
                logger.critical(f"FATAL ERROR in robot_loop: {e}", exc_info=True)
                eventlet.sleep(2)


# FLASK, SHARED QUEUE & SOCKETIO SETUP

# Initialization FLASK app
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Initialize Simulation
sim = RobotSimulation(PATH_LENGTHS, NUM_ROBOTS)


# Flask Routes

@app.route("/")
def index():
    """Renders the main simulation UI page."""
    return render_template("index.html", path_lengths=PATH_LENGTHS, MIN_ROBOTS=NUM_ROBOTS)

# SocketIO Event Handlers (outside class)

@socketio.on("connect")
def on_connect():
    """Handles new client connections."""
    logger.info("Client connected.")
    sim.emit_state()

@socketio.on("add_package")
def on_add_package():
    """Handles 'add_package' event from client."""
    sim.add_package()

@socketio.on("remove_package")
def on_remove_package():
    """Handles 'remove_package' event from client."""
    sim.remove_package()

@socketio.on("add_robot")
def on_add_robot():
    """Handles 'add_robot' event from client."""
    sim.add_robot()

@socketio.on("remove_robot")
def on_remove_robot():
    """Handles 'remove_robot' event from client."""
    sim.remove_robot()


# MAIN EXECUTION
if __name__ == "__main__":
    logger.info("Starting Robot Simulation Application...")

    # Start Robot Simulation Loop (Eventlet thread)
    socketio.start_background_task(sim.robot_loop)
    logger.info("Started robot simulation loop in background thread.")

    # Start Flask/SocketIO Server
    try:
        socketio.run(app, host="0.0.0.0", port=5000, log_output=False)
    except Exception as e:
        logger.critical(f"Server failed to start: {e}")