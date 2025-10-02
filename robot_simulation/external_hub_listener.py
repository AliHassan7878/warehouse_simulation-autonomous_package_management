# Save this script as external_listener.py
import grpc
import time
import os
import json
import sys
import logging

# Set up simple logging for the external script
logging.basicConfig(level=logging.INFO, format='%(asctime)s [EXTERNAL] - %(message)s')

# --- CONFIGURATION (Match your hub constants) ---
HUB_ADDR = "communication_hub:50051"
EVENT_FILE = "/tmp/hub_events.log" # Shared file for IPC

try:
    import delivery_pb2
    import delivery_pb2_grpc
except ImportError:
    logging.critical("FATAL ERROR: Failed to import generated gRPC files.")
    sys.exit(1)


def run_listener():
    
    try:
        os.makedirs(os.path.dirname(EVENT_FILE), exist_ok=True)
        logging.debug(f"Ensured directory exists for {EVENT_FILE}")
    except Exception as e:
        logging.critical(f"FATAL: Could not create directory for event file. {e}")
        sys.exit(1)

    # 3. Clear the file on startup (Crucial for resetting IPC state)
    try:
        # Using "w" (write) mode immediately creates the file if it doesn't exist
        # and clears its contents if it does, setting up a clean start.
        with open(EVENT_FILE, "w") as f:
            f.write("") # Write an empty string to ensure it's empty
        logging.info(f"Cleared existing event file: {EVENT_FILE}")
    except Exception as e:
        logging.critical(f"FATAL: Could not create or clear event file for writing. {e}")
        sys.exit(1)
    
    logging.info(f"Starting external listener, connecting to {HUB_ADDR}")
    
    # 1. Initialize Connection (This is the process that works!)
    while True:
        try:
            channel = grpc.insecure_channel(HUB_ADDR)
            hub_stub = delivery_pb2_grpc.DeliveryHubStub(channel)
            break
        except Exception as e:
            logging.error(f"Failed to connect to gRPC hub: {e}. Retrying in 5s.")
            time.sleep(5)

    # 3. Consume the stream and write events to the file
    while True:
        try:
            logging.info("Subscribing to gRPC events...")
            for event in hub_stub.SubscribeEvents(delivery_pb2.EventSubscriptionRequest()):
                
                # Convert the gRPC event object to a JSON string
                event_data = {
                    "event_type": event.event_type,
                    "slots_used": event.slots_used,
                    "total_slots": event.total_slots,
                    "robot_id": event.robot_id,
                    "package_id": event.package_id
                }
                json_line = json.dumps(event_data)
                
                # Append the JSON line to the shared file
                with open(EVENT_FILE, "a") as f:
                    f.write(json_line + "\n")
                
                logging.debug(f"Event written to file: {event_data['event_type']}")

        except grpc.RpcError as e:
            logging.warning(f"gRPC stream error: {e.details()}. Reconnecting in 5s.")
            time.sleep(5) # Wait before re-running connection logic
        except Exception as e:
            logging.error(f"Unexpected error in listener loop: {e}", exc_info=True)
            time.sleep(5)


if __name__ == '__main__':
    run_listener()