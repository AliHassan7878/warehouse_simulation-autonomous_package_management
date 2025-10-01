import multiprocessing
from multiprocessing import Process, Queue
import queue
import eventlet
eventlet.monkey_patch()  # Patch standard libraries for async compatibility

from flask import Flask, render_template
from flask_socketio import SocketIO
import random
import logging
import grpc
import threading
import time
import sys

# ==============================================================================
#                      GRPC IMPORTS (REQUIRES YOUR GENERATED FILES)
# ==============================================================================
# 🛑 IMPORTANT: These imports must correctly point to your compiled protobuf files.
try:
    import delivery_pb2
    import delivery_pb2_grpc
except ImportError:
    # This block will execute if your generated files aren't available,
    # and the application will crash as desired (no mock fallback).
    print("FATAL ERROR: Failed to import generated gRPC files (delivery_pb2 or delivery_pb2_grpc).", file=sys.stderr)
    print("Please ensure your protobuf files are compiled and accessible on the Python path.", file=sys.stderr)
    sys.exit(1)


# ==============================================================================
#                                  CONSTANTS
# ==============================================================================
PATH_LENGTHS = [31.0, 13.0, 9.0, 21.0]  # Length of available paths (in meters)
NUM_ROBOTS = 4                          # Initial number of robots
STEP_TIME = 0.05                        # Simulation time step (seconds per loop tick)
SAFE_GAP = 2.0                          # Minimum safe distance between robots (in meters)
MIN_SPEED_FACTOR = 0.2                  # Minimum fraction of original speed for collision avoidance
HUB_ADDR = "communication_hub:50051"    # Address of the gRPC Communication Hub
LOG_FILE = "robot_sim.log"

# ==============================================================================
#                                  LOGGING SETUP
# ==============================================================================
def setup_logging():
    """Configures the logging system with file and stream handlers."""
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s - %(message)s"
    ))
    file_handler.setLevel(logging.DEBUG)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] - %(message)s"
    ))
    stream_handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger

logger = setup_logging()

# --- gRPC Connection (No Mock Fallback) ---
try:
    # Initialize the real gRPC channel
    channel = grpc.insecure_channel(HUB_ADDR)
    
    # Initialize the real gRPC stub
    hub_stub = delivery_pb2_grpc.DeliveryHubStub(channel)
    
    logger.info("gRPC channel to Communication Hub established successfully.")

except Exception as e:
    # If the connection, gRPC library, or channel setup fails, the application exits.
    logger.critical(f"FATAL ERROR: Failed to initialize gRPC connection to {HUB_ADDR}. Application halting.", exc_info=True)
    sys.exit(1)


# ==============================================================================
#                             ROBOT SIMULATION CLASS
# ==============================================================================

class RobotSimulation:
    """Manages the state and movement logic for all robots and packages."""
    
    def __init__(self, path_lengths: list[float], num_robots: int, shared_event_queue):
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
        self.event_queue = shared_event_queue
        
        logger.info("RobotSimulation initialized with %d robots.", num_robots)

    # --------------------------------------------------------------------------
    # Utility & Communication
    # --------------------------------------------------------------------------

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
        
        # NOTE: 'socketio' is defined globally below
        socketio.emit("state_update", {
            "packages": self.state["packages"],
            "delivered_count": len(self.state["delivered_packages"]),
            "robots": robots_ui,
        })
        logger.debug("State emitted to UI.")
        
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
            # Uses the real gRPC message type
            req = delivery_pb2.DeliveryRequest(robot_id=robotId, package_id=packageId)
            
            # Uses the real gRPC stub
            resp = hub_stub.SendDelivery(req, timeout=5)
            
            status = "UNKNOWN"
            if hasattr(resp, "message") and resp.message:
                status = resp.message
            elif hasattr(resp, "success"):
                status = "ACK" if resp.success else "FAIL"

            logger.info(f"Robot {robotId} delivery request for package {packageId} received response: {status}")
            return status
            
        except grpc.RpcError as e:
            # This is the expected way to handle hub rejection or communication loss
            logger.warning(f"gRPC delivery for robot {robotId} failed with RpcError: {e.details()}")
            return "failed"
        except Exception as e:
            logger.error(f"Unexpected error in try_deliver for robot {robotId}: {e}")
            return "failed"

    def poll_hub_events(self):
        """Processes events from the event queue in a non-blocking manner."""
        if self.event_queue is None:
            return
            
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error while polling hub events: {e}")
                break
            else:
                self._handle_hub_event(event)

    def _handle_hub_event(self, event):
        """Update robot states based on hub broadcast events (e.g., slot freed)."""
        # Event object now comes from the real gRPC stream
        robot_id = event.robot_id
        package_id = event.package_id
        status = event.status.upper() if hasattr(event, 'status') else ""

        for r in self.state["robots"]:
            if r["id"] == robot_id and r["status"] == "waiting_at_A_with_package" and r["packageId"] == package_id:
                if status in ("ACK", "ACCEPTED", "SLOT_FREED"):
                    # Set the internal flag to trigger a delivery retry on the next loop tick
                    r["_retry_flag"] = True
                    logger.info(f"Hub event {status} received for Robot {r['id']} (Pkg {package_id}). Setting retry flag.")

    # --------------------------------------------------------------------------
    # User-Triggered Functions (via SocketIO)
    # --------------------------------------------------------------------------

    def add_package(self):
        """Adds a new package to the queue for assignment."""
        self.state["last_package_id"] += 1
        package_id = self.state["last_package_id"]
        
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
    
    # --------------------------------------------------------------------------
    # Robot State Logic (Functions called from the main loop)
    # --------------------------------------------------------------------------
    
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
            
            # FIX: Decrement the package counter as it moves from 'waiting' to 'assigned/in-transit'
            self.state["packages"] -= 1
            
            logger.info(
                f"Robot {r['id']} assigned package {pkg_id} on path {r['path']} "
                f"(speed={r['speed']:.2f}m/s)"
            )
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
                # Success: Clears package, returns without it
                r["status"] = "returning"
                r["packageId"] = None
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
        r["speed"] = 0.0
        r["path"] = r["id"] % len(self.path_lengths) # Keep path for consistency
        r["distance"] = 0.0
        if r.get("_retry_flag"):
            r["_retry_flag"] = False
            pkg_id = r["packageId"]
            logger.info(f"Robot {r['id']} attempting delivery retry for package {pkg_id}.")
            
            status = self.try_deliver(r["id"], pkg_id)
            status_upper = (status or "").upper()
            
            if status_upper in ("ACK", "OK", "ACCEPTED", "ACCEPT"):
                # Successful retry
                r["status"] = "returning" 
                r["packageId"] = None
                self.state["pending_packages"].pop(pkg_id, None)
                self.state["delivered_packages"].add(pkg_id)
                r["direction"] = "None"
                logger.info(f"Robot {r['id']} successfully retried delivery.")
            else:
                logger.warning(f"Robot {r['id']} retry failed. Status: {status}. Waiting again.")

            self.emit_state()

    # --------------------------------------------------------------------------
    # Main Robot Movement Loop
    # --------------------------------------------------------------------------

    def robot_loop(self):
        """The main simulation loop, executing robot state logic."""
        logger.info("Robot simulation loop started.")
        while True:
            try:
                self.poll_hub_events()

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

                self.emit_state() 
                eventlet.sleep(STEP_TIME)
                
            except Exception as e:
                logger.critical(f"FATAL ERROR in robot_loop: {e}", exc_info=True)
                eventlet.sleep(2)


# ==============================================================================
#                             GRPC LISTENER FUNCTION
# ==============================================================================

def hub_listener(shared_queue):
    """
    Subscribes to gRPC events from the Communication Hub in a separate process
    and pushes them onto the event queue.
    """
    process_name = multiprocessing.current_process().name
    logger.info(f"Hub listener process ({process_name}) started.")
    
    while True:
        try:
            # Uses the real gRPC EventSubscriptionRequest and receives real events
            for event in hub_stub.SubscribeEvents(delivery_pb2.EventSubscriptionRequest()):
                shared_queue.put(event)
                logger.debug(f"Event received from Hub: Pkg {event.package_id}, Status: {event.status}")
                print(f"Event received from Hub: Pkg {event.package_id}, Status: {event.status}")
                
        except grpc.RpcError as e:
            # If the gRPC stream breaks (e.g., hub restart or network issue), reconnect.
            logger.warning(f"gRPC event stream error: {e.details()}, reconnecting in 5s.")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error in hub_listener: {e}", exc_info=True)
            time.sleep(5)


# ==============================================================================
#                             FLASK & SOCKETIO SETUP
# ==============================================================================

# --- Initialization ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Initialize Simulation (Accessing the global sim object)
hub_event_queue = multiprocessing.Queue()
sim = RobotSimulation(PATH_LENGTHS, NUM_ROBOTS, hub_event_queue)


# --------------------------------------------------------------------------
# Flask Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    """Renders the main simulation UI page."""
    return render_template("index.html", path_lengths=PATH_LENGTHS, MIN_ROBOTS=NUM_ROBOTS)

# --------------------------------------------------------------------------
# SocketIO Event Handlers (outside class)
# --------------------------------------------------------------------------

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


# ==============================================================================
#                                MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    logger.info("Starting Robot Simulation Application...")

    # Create the shared queue that all processes can access
    SHARED_EVENT_QUEUE = Queue() 
    # 1. Start gRPC Hub Listener Process
    listener_process = multiprocessing.Process(
        target=hub_listener, 
        args=(SHARED_EVENT_QUEUE,), 
        daemon=True,
        name="HubListenerProcess"
    )
    listener_process.start()
    logger.info("Started Hub Listener process (PID: %d).", listener_process.pid)

    # 2. Start Robot Simulation Loop (Eventlet thread)
    socketio.start_background_task(sim.robot_loop)
    logger.info("Started robot simulation loop in background thread.")

    # 3. Start Flask/SocketIO Server
    try:
        socketio.run(app, host="0.0.0.0", port=5000, log_output=False)
    except Exception as e:
        logger.critical(f"Server failed to start: {e}")