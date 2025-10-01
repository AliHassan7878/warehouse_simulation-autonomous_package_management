import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO
import threading
import random
import time
import json
import logging
import os
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification

# --- Flask & SocketIO ---
app = Flask(__name__)
# Use eventlet to ensure non-blocking operation for SocketIO and Modbus polling
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# --- Modbus Register Addresses ---
REQUEST_START_ADDR = 10  # Robot ID (Reg 10), Package ID (Reg 11)
RESPONSE_STATUS_ADDR = 12 # Status (1=Accepted, 2=Full)

# --- Data storage ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

PACKAGES_FILE = os.path.join(DATA_DIR, "packages.json")
if not os.path.isfile(PACKAGES_FILE):
    with open(PACKAGES_FILE, "w") as f:
        json.dump([], f, indent=2)

print(f"packages.json created at: {PACKAGES_FILE}")

TOTAL_SLOTS = 1 # Total delivery slots in hub

# --- Logging setup ---
class LiveLogHandler(logging.Handler):
    """Emit logs to SocketIO clients in real-time."""
    def emit(self, record):
        try:
            socketio.emit("live_log", {"msg": self.format(record)})
        except Exception:
            pass

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s - %(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.addHandler(LiveLogHandler())

# --- Delivery Hub ---
class DeliveryHub:
    def __init__(self, total_slots):
        self.total_slots = total_slots
        self.slots_used = 0
        self.processed_packages = []          # store full package info after processing
        self.processed_package_ids = set()    # track processed package IDs
        self.lock = threading.Lock()
        self.socketio = socketio
        self.context = None
        self.load_packages()
        logging.info("Delivery Hub initialized with %d slots", total_slots)
        self.emit_slot_status() # Emit initial status

    def load_packages(self):
        """Load processed packages from file on startup."""
        try:
            with open(PACKAGES_FILE, "r") as f:
                self.processed_packages = json.load(f)
                self.processed_package_ids = set(pkg["packageId"] for pkg in self.processed_packages)
        except Exception as e:
            logging.warning(f"Failed to load packages file: {e}")
            self.processed_packages = []
            self.processed_package_ids = set()

    def save_packages(self):
        try:
            with open(PACKAGES_FILE, "w") as f:
                json.dump(self.processed_packages, f, indent=2)
        except Exception as e:
            logging.error(f"Failed to save packages file: {e}")

    def emit_slot_status(self):
        """Send current slot availability status via SocketIO."""
        status = "FREE_SLOT_AVAILABLE" if self.slots_used < self.total_slots else "NO_FREE_SLOTS"
        
        # Log and emit the status
        logging.info(f"Slot Status: {status} ({self.slots_used}/{self.total_slots})")
        try:
            self.socketio.emit("slot_status", {
                "status": status,
                "slots_used": self.slots_used,
                "total_slots": self.total_slots,
            })
        except Exception as e:
            logging.debug(f"emit_slot_status failed: {e}")


    def try_deliver(self, robot_id, package_id):
        """
        Attempts to accept a package. Returns the Modbus status code (1 or 2).
        1: Accepted (or already processed, which is treated as success)
        2: Full (denied)
        """
        with self.lock:
            if package_id in self.processed_package_ids:
                logging.info(f"Package {package_id} already processed, returning ACCEPTED (1).")
                return 1 # Treat already processed as success for robot state

            if self.slots_used < self.total_slots:
                self.slots_used += 1

                # Only mark as processed ID, do NOT append placeholder
                self.processed_package_ids.add(package_id)

                logging.info(f"Package {package_id} from Robot {robot_id} ACCEPTED ({self.slots_used}/{self.total_slots})")
                
                # Start background task for simulated processing
                self.socketio.start_background_task(self.process_package, robot_id, package_id)

                self.update_modbus_status_registers()

                self.emit_hub_event({
                    "event": "accepted",
                    "robot_id": robot_id,
                    "package_id": package_id,
                    "slots_used": self.slots_used,
                    "total_slots": self.total_slots,
                })
                # Check and emit slot status after taking a slot
                self.emit_slot_status() 
                return 1 # Modbus Status: Accepted
            
            if self.slots_used == self.total_slots:
                logging.info(f"No free slots for package {package_id} from Robot {robot_id}. DENIED (2).")
                
                self.update_modbus_status_registers()
                
                self.emit_hub_event({
                    "event": "full",
                    "robot_id": robot_id,
                    "package_id": package_id,
                    "slots_used": self.slots_used,
                    "total_slots": self.total_slots,
                })
                # Emit slot status (will be NO_FREE_SLOTS)
                self.emit_slot_status() 
                return 2 # Modbus Status: NO_FREE_SLOTS/Denied
            else:
                logging.info(f"No free slots for package {package_id} from Robot {robot_id}. DENIED (2).")
                
                self.update_modbus_status_registers()
                
                self.emit_hub_event({
                    "event": "full",
                    "robot_id": robot_id,
                    "package_id": package_id,
                    "slots_used": self.slots_used,
                    "total_slots": self.total_slots,
                })
                # Emit slot status (Slot Available)
                self.emit_slot_status() 
                return 3 # Modbus Status: Slots Available

    def process_package(self, robot_id, package_id):
        """Simulate actual package processing."""
        processing_time = random.randint(1,5)
        logging.info(f"Processing package {package_id} from Robot {robot_id} for {processing_time}s...")
        eventlet.sleep(processing_time)

        # Build package info
        package_info = {
            "packageId": package_id,
            "weight": round(random.uniform(0.5,5.0),2),
            "dimension": f"{random.randint(5,40)}x{random.randint(5,40)}x{random.randint(5,40)} cm",
            "timestamp": time.time()
        }

        with self.lock:
            self.slots_used -= 1
            self.processed_packages.append(package_info)  # append only once here
            self.save_packages()
            
            # 1. Emit SLOT_FREED event (for robot app retry logic)
            self.emit_hub_event({
                "event": "SLOT_FREED",
                "robot_id": robot_id,
                "package_id": package_id,
                "slots_used": self.slots_used,
                "total_slots": self.total_slots,
            })

            self.update_modbus_status_registers()
            
            logging.info(f"Package {package_id} processed ({self.slots_used}/{self.total_slots}) | Total processed: {len(self.processed_packages)}")

            # 2. Emit general slot status (should now be FREE_SLOT_AVAILABLE if total_slots > 0)
            self.emit_slot_status() 
            
            # 3. Emit to UI
            try:
                self.socketio.emit("hub_update", {
                    "event": "processed",
                    "package": package_info,
                    "slots_used": self.slots_used,
                    "total_slots": self.total_slots,
                    "processed_count": len(self.processed_packages)
                })
            except Exception as e:
                logging.warning(f"SocketIO emit failed: {e}")

    def emit_hub_event(self, payload):
        """Send real-time events to UI (used for ACCEPTED, FULL, SLOT_FREED)."""
        try:
            self.socketio.emit("hub_event", payload)
        except Exception as e:
            logging.debug(f"emit_hub_event failed: {e}")

    def update_modbus_status_registers(self):
        """Write current slots_used and total_slots to Modbus HRegs 0 and 1."""
        try:
            if self.context is not None:
                # Write slots_used to HReg 0, total_slots to HReg 1
                values = [self.slots_used, self.total_slots]
                # Function code 3 (Holding Registers), starting at address 0
                self.context[0].setValues(3, 0, values)
                logging.debug(f"Modbus HRegs 0/1 updated to: {values}")
        except Exception as e:
            logging.warning(f"update_modbus_status_registers failed: {e}")


# --- Initialize hub ---
hub = DeliveryHub(TOTAL_SLOTS)

# --- Flask routes ---
@app.route("/")
def index():
    # Load packages from JSON
    try:
        with open(PACKAGES_FILE, "r") as f:
            packages = json.load(f)
    except Exception:
        packages = []

    total_packages = len(packages)
    return render_template("hub.html", total_packages=total_packages)


@app.route("/processed_packages")
def get_packages():
    try:
        with open(PACKAGES_FILE, "r") as f:
            packages = json.load(f)
    except Exception as e:
        packages = []
    return jsonify(packages)

# --- Modbus TCP Server ---
def start_modbus_server():
    # Initialize 100 holding registers starting at address 0
    store = ModbusSlaveContext(hr=ModbusSequentialDataBlock(0, [0]*100))
    context = ModbusServerContext(slaves=store, single=True)
    hub.context = context

    identity = ModbusDeviceIdentification()
    identity.VendorName = 'DeliveryHub'
    identity.ProductCode = 'DH'
    identity.VendorUrl = 'http://example.com'
    identity.ProductName = 'DeliveryHub Modbus'
    identity.ModelName = 'DH1'
    identity.MajorMinorRevision = '1.0'

    logging.info("Starting synchronous Modbus TCP server on 0.0.0.0:502")

    def poll_registers():
        """
        Continuously poll Modbus registers 10 and 11 for new requests.
        The Modbus server itself doesn't offer "on_write" hooks easily in this sync context,
        so polling is necessary to react to client writes.
        """
        seen_requests = set()  # track (robot_id, package_id) already handled
        
        while True:
            try:
                # Read 3 values: Reg 10 (Robot ID), Reg 11 (Package ID), Reg 12 (Status)
                hr_values = context[0].getValues(3, REQUEST_START_ADDR, count=3) 
                robot_id, package_id, status_check = hr_values[0], hr_values[1], hr_values[2]
                
                if package_id != 0:
                    req_key = (robot_id, package_id)
                    
                    if req_key not in seen_requests:
                        
                        # 1. Clear Request Registers immediately (10 and 11)
                        context[0].setValues(3, REQUEST_START_ADDR, [0, 0])
                        
                        logging.info(f"Received delivery request from Robot {robot_id}, Package {package_id}. Processing...")
                        
                        # 2. Process request and get Modbus status code (1 or 2)
                        modbus_status_code = hub.try_deliver(robot_id, package_id)
                        
                        # 3. Write Response Status to Register 12
                        context[0].setValues(3, RESPONSE_STATUS_ADDR, [modbus_status_code])
                        logging.info(f"Modbus Response: Wrote status {modbus_status_code} to Register 12.")

                        seen_requests.add(req_key) 
                        
                # 4. Clear Status Register (12) when the request registers are clear, 
                # to reset the hub state for the next Modbus transaction.
                if package_id == 0 and status_check != 0:
                     context[0].setValues(3, RESPONSE_STATUS_ADDR, [0]) # Clear status register
                     logging.info("Modbus Status Register (12) cleared.")
                     
            except Exception as e:
                # Log only the first few chars of the exception to keep logs clean
                logging.warning(f"poll_registers exception: {str(e)[:100]}")
            
            # Short sleep to prevent busy-waiting while keeping the reaction time fast
            time.sleep(0.05) 

    # Start polling thread
    threading.Thread(target=poll_registers, daemon=True).start()

    # Start the Modbus TCP server
    try:
        StartTcpServer(context, identity=identity, address=("0.0.0.0", 502))
    except Exception as e:
        logging.exception(f"StartTcpServer failed: {e}")


# --- Main ---
if __name__ == "__main__":
    # Start Modbus server in a separate daemon thread
    threading.Thread(target=start_modbus_server, daemon=True).start()
    logging.info("Starting Flask-SocketIO server...")
    # Use eventlet's start function for the main server
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', 5500)), app)
