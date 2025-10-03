# warehouse_robot_simulation

The project simulates a **Warehouse Robot Delivery System** consisting of three main services:

- **Communication Hub (Rust)**  
  Handles communication between nodes using gRPC and Modbus.

- **Delivery Hub (Python/Flask)**  
  Central hub managing message queues, delivery slots, and real-time status.

- **Robot Simulation (Python/Flask)**  
  Simulates robot movement, package handling, and visualization.

All services are containerized with **Docker** and orchestrated with **Docker Compose**.

### Project Structure

Robot simulation <--------> (gRPC) Communication Hub <--------> (ModBus) Delivery Hub

---

### Prerequisites

- [Git](https://git-scm.com/)  
- [Docker](https://docs.docker.com/get-docker/)  
- [Docker Compose](https://docs.docker.com/compose/)  

If you don’t have Docker or Docker Compose installed, the provided script (`build.sh`) will install them.

---

### Important Note Before Running Shell Scripts

***⚠️ WARNING:*** Please ***open and read each shell script (`build.sh`, `simulation.sh`, etc.) before executing them***.  
Verify all commands, paths, and configurations to ensure they are safe for your environment.

---

###  Build the Project

Run the provided build script:

```bash
./build.sh
```

### Start the simulation:

```bash
./simulation.sh start
```

### Stop the simulation:

```bash
./simulation.sh stop
```
### Restart the simulation:

```bash
./simulation.sh restart
```
### Check the docker container status:

```bash
./simulation.sh status
```

---

### Accessing the Services

Robot Simulation UI → http://localhost:5000

Delivery Hub Web UI → http://localhost:5500

Communication Hub → Runs as a backend service (no direct UI).

---

### Development

Modify hub.py (Delivery Hub) or app.py (Robot Simulation) or main.rs → rebuild containers:

```bash
./build.sh
```
```
./simulation.sh restart
```
---
