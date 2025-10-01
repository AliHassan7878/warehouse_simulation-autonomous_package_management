use std::net::SocketAddr;
use std::convert::TryInto;
use std::sync::Arc;
use tokio::sync::broadcast;
use tokio::time; 
use tokio_modbus::prelude::*;
use tokio_modbus::client::tcp;

use tonic::{transport::Server, Request, Response, Status};
use tonic::async_trait;
use tracing::{info, error, warn};
use std::net::ToSocketAddrs;                 

use tokio_stream::wrappers::BroadcastStream;
use tokio_stream::wrappers::errors::BroadcastStreamRecvError;
use futures_util::StreamExt;
use futures_util::stream::BoxStream;             

pub mod delivery {
    tonic::include_proto!("delivery");
}

use delivery::delivery_hub_server::{DeliveryHub, DeliveryHubServer};
use delivery::{DeliveryRequest, DeliveryResponse, EventSubscriptionRequest, HubEvent};

// --- MODBUS CONSTANTS ---
const HUB_STATUS_ADDR: u16 = 0; // HReg 0: slots_used, HReg 1: total_slots
const REQUEST_START_ADDR: u16 = 10; // HReg 10: Robot ID, HReg 11: Package ID
const RESPONSE_STATUS_ADDR: u16 = 12; // HReg 12: 0=Pending, 1=Accepted, 2=Full, 3=Other (Transient response)

const MODBUS_TIMEOUT_SECS: u64 = 10;
const MODBUS_POLL_INTERVAL_MS: u64 = 50;
const STATUS_POLL_INTERVAL_MS: u64 = 500; // Slower poll for continuous status

const DELIVERY_HUB_ADDRESS: &str = "delivery_hub";
const DELIVERY_HUB_PORT: u16 = 502;


#[derive(Debug)]
pub struct MyDeliveryHub {
    tx: broadcast::Sender<HubEvent>,
}

impl MyDeliveryHub {
    fn new() -> Arc<Self> { // Returns Arc<Self> to simplify main/server setup
        let (tx, _rx) = broadcast::channel(16);
        let hub = Arc::new(Self { tx });

        // Start the continuous status monitor task
        tokio::spawn(run_status_monitor(hub.clone()));

        hub
    }

    async fn broadcast_event(&self, robot_id: i32, package_id: i32, event_type: &str, slots_used: i32, total_slots: i32) {
        let _ = self.tx.send(HubEvent {
            robot_id,
            package_id,
            event_type: event_type.into(),
            slots_used,
            total_slots,
        });
    }

    // Modbus transaction function
    async fn execute_modbus_transaction(&self, robot_id: u16, package_id: u16) -> Result<u16, Box<dyn std::error::Error + Send + Sync>> {
        let socket_addr: SocketAddr = (DELIVERY_HUB_ADDRESS, DELIVERY_HUB_PORT).to_socket_addrs()?.next().unwrap();
        
        let mut ctx: tokio_modbus::client::Context = tcp::connect(socket_addr).await?;

        // 1. Write Request
        ctx.write_multiple_registers(REQUEST_START_ADDR, &vec![robot_id, package_id]).await?;
        
        info!(event = "modbus_write_success", robot_id, package_id, "Wrote request to Modbus registers.");

        // 2. Poll for Status Response
        let poll_interval = time::Duration::from_millis(MODBUS_POLL_INTERVAL_MS);
        let timeout_duration = time::Duration::from_secs(MODBUS_TIMEOUT_SECS);

        let status = time::timeout(timeout_duration, async move {
            loop {
                // Read only the status register
                let response = match ctx.read_holding_registers(RESPONSE_STATUS_ADDR, 1).await {
                    Ok(res) => res,
                    Err(e) => return Err(Box::new(e) as Box<dyn std::error::Error + Send + Sync>),
                };

                let status = response[0];

                if status == 1 || status == 2 {
                    // Status is 1 (Accepted) or 2 (Denied/Full)
                    return Ok(status);
                }
                
                // Wait briefly before polling again
                time::sleep(poll_interval).await;
            }
        })
        .await
        .map_err(|_| {
            warn!(event = "modbus_timeout", "Modbus status poll timed out.");
            Box::<dyn std::error::Error + Send + Sync>::from("Modbus status poll timed out")
        })
        .and_then(|res| res)?;

        
        Ok(status)
    }
}

// -----------------------------------------------------
// Continuous Modbus Polling Task for Status Broadcast  (One-to-Many)
// -----------------------------------------------------
async fn run_status_monitor(hub: Arc<MyDeliveryHub>) {
    // State to track previous status
    let mut last_slots_used: Option<u16> = None;
    let poll_interval = time::Duration::from_millis(STATUS_POLL_INTERVAL_MS);

    info!(event="status_monitor_start", "Starting continuous Modbus status monitor.");

    loop {
        time::sleep(poll_interval).await;

        match read_hub_status().await {
            Ok(values) => {
                let slots_used = values[0];
                let total_slots = values[1];

                let current_state = if slots_used < total_slots { 
                    "FREE_SLOTS_AVAILABLE" 
                } else { 
                    "SLOTS_FULL" 
                };

                // Check if the slots_used count has changed since the last poll
                if last_slots_used.map_or(true, |last| last != slots_used) {
                    
                    info!(
                        event="delivery_hub_status_changed",
                        slots_used,
                        total_slots,
                        state=current_state,
                        "Broadcasting general hub status change."
                    );

                    // Broadcast the new status to all gRPC subscribers
                    hub.broadcast_event(
                        0, // Use 0 for Robot/Package ID to signify a general hub event
                        0,
                        current_state,
                        slots_used as i32,
                        total_slots as i32
                    ).await;

                    last_slots_used = Some(slots_used);
                }
            },
            Err(e) => {
                error!(event="delivery_hub_status_error", error=?e, "Failed to read hub status from Modbus.");
            }
        }
    }
}

// -------------------------------------------------------------
// Implementation of DeliveryHub for the Arc<MyDeliveryHub> wrapper
// -------------------------------------------------------------
#[async_trait]
impl DeliveryHub for Arc<MyDeliveryHub> {
    type SubscribeEventsStream = BoxStream<'static, Result<HubEvent, Status>>;

    async fn send_delivery(
        &self,
        request: Request<DeliveryRequest>,
    ) -> Result<Response<DeliveryResponse>, Status> {
        // Delegate to the main logic
        (**self).send_delivery(request).await
    }

    async fn subscribe_events(
        &self,
        request: Request<EventSubscriptionRequest>,
    ) -> Result<Response<Self::SubscribeEventsStream>, Status> {
        // Delegate to the main logic
        (**self).subscribe_events(request).await
    }
}
// -------------------------------------------------------------


// ------------------------------------------------
// Implementation of DeliveryHub for MyDeliveryHub
// ------------------------------------------------
#[async_trait]
impl DeliveryHub for MyDeliveryHub {
    type SubscribeEventsStream = BoxStream<'static, Result<HubEvent, Status>>;

    async fn send_delivery(
        &self,
        request: Request<DeliveryRequest>,
    ) -> Result<Response<DeliveryResponse>, Status> {
        let req = request.into_inner();

        info!(
            service="communication_hub",
            event="request_received",
            robot_id=?req.robot_id,
            package_id=?req.package_id,
            "Received delivery request"
        );

        let robot_id: u16 = req.robot_id.try_into()
            .map_err(|_| Status::invalid_argument("robot_id out of range"))?;
        let package_id: u16 = req.package_id.try_into()
            .map_err(|_| Status::invalid_argument("package_id out of range"))?;

        // Main Modbus Write-Poll-Read Transaction
        let result = self.execute_modbus_transaction(robot_id, package_id).await;

        match result {
            Ok(status) => {
                // The gRPC response should only reflect the Modbus transaction result (one-to-one)
                if status == 1 { // ACCEPTED
                    info!(
                        service="communication_hub",
                        event="delivery_accepted",
                        "Delivery accepted by hub. Replying to robot."
                    );

                    Ok(Response::new(DeliveryResponse {
                        success: true,
                        message: "ACCEPTED".into(),
                    }))
                } else if status == 2 { // DENIED / FULL
                    info!(
                        service="communication_hub",
                        event="delivery_denied",
                        "Delivery denied: slots_full. Replying to robot."
                    );

                    Ok(Response::new(DeliveryResponse {
                        success: false,
                        message: "SLOT_FULL".into(),
                    }))
                } else {
                    // Catch for other cases
                    warn!(event="unexpected_modbus_status", status, "Received unexpected Modbus status code.");
                    Ok(Response::new(DeliveryResponse {
                        success: false,
                        message: format!("UNEXPECTED_MODBUS_STATUS: {}", status).into(),
                    }))
                }
            }
            Err(e) => {
                // Modbus failure handling
                error!(
                    service="communication_hub",
                    event="modbus_failure",
                    robot_id,
                    package_id,
                    error=?e,
                    "Modbus transaction failed (Timeout/Connection error)."
                );
                Err(Status::deadline_exceeded(format!("Modbus transaction failed: {}", e)))
            }
        }
    }

    // SubscribeEvents: receives events from the background monitor
    async fn subscribe_events(
        &self,
        _request: Request<EventSubscriptionRequest>,
    ) -> Result<Response<Self::SubscribeEventsStream>, Status> {
        let rx = self.tx.subscribe();

        let stream = BroadcastStream::new(rx)
            .map(|res| match res {
                Ok(event) => Ok(event),
                Err(BroadcastStreamRecvError::Lagged(_)) => { 
                    Err(Status::internal("broadcast lagged; restarting stream"))
                }
            })
            .boxed(); 

        Ok(Response::new(stream))
    }
}


// Helper function to read the current status of the hub from Modbus HReg 0 and 1
async fn read_hub_status() -> Result<Vec<u16>, Box<dyn std::error::Error + Send + Sync>> {
    let socket_addr: SocketAddr = (DELIVERY_HUB_ADDRESS, DELIVERY_HUB_PORT).to_socket_addrs()?.next().unwrap();
    let mut ctx: tokio_modbus::client::Context = tcp::connect(socket_addr).await?;
    
    // Read HReg 0 (slots_used) and HReg 1 (total_slots)
    let response = ctx.read_holding_registers(HUB_STATUS_ADDR, 2).await?;
    Ok(response)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tracing_subscriber::fmt().with_env_filter("info").init();

    info!(service="communication_hub", event="startup", "Communication Hub is starting...");

    let addr: SocketAddr = "0.0.0.0:50051".parse()?;
    
    // MyDeliveryHub::new() returns Arc<Self> and spawns the monitor
    let hub = MyDeliveryHub::new(); 

    info!(service="communication_hub", event="listen", addr=?addr, "Listening for gRPC requests");

    Server::builder()
        .add_service(DeliveryHubServer::new(hub.clone()))
        .serve(addr)
        .await?;

    Ok(())
}