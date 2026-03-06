# Warehouse Simulation: Autonomous Package Management

A modular simulation demonstrating a **Warehouse Robot Delivery System** built with a microservices architecture.  
Robots, hubs, and communication nodes interact through **gRPC** and **Modbus** protocols within containerized environments.

---


### 🧩 Overview

The project simulates a distributed warehouse robot delivery workflow consisting of three main services:

- **Robot Simulation (Python/Flask)**  
  Simulates robot movement, package handling, and visualization through a web interface.

- **Communication Hub (Rust)**  
  Handles communication between nodes using gRPC and Modbus TCP Slave.

- **Delivery Hub (Python/Flask)**  
  Central coordination service managing message queues, delivery slots, and real-time status updates.

All services are containerized using **Docker** and orchestrated with **Docker Compose**.

---

### 🧱 Architecture

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

### 🧠 Features

- Simulated robot delivery system with visual interface

- Message-based communication using gRPC and Modbus

- Central delivery coordination hub

- Fully containerized and orchestrated with Docker Compose

- Modular design for easy extension and experimentation

---

### Development

Modify hub.py (Delivery Hub) or app.py (Robot Simulation) or main.rs → rebuild containers:

```bash
./build.sh

./simulation.sh restart
```
---

📜 License

This project is released under the MIT License.
You’re free to use, modify, and distribute it with proper attribution.

---

### 💬 Note
This project was initially developed as part of a technical evaluation and has been adapted for educational and portfolio purposes.
All code and architecture are original contributions.

---
