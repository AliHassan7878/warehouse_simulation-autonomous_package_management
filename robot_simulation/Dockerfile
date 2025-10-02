FROM python:3.12-slim

# --- Set workdir ---
WORKDIR /app

# --- Copy requirements ---
COPY requirements.txt .

# --- Install system dependencies ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        protobuf-compiler && \
    rm -rf /var/lib/apt/lists/*

# --- Install Python packages ---
RUN pip install --no-cache-dir -r requirements.txt

# --- Copy proto files ---
COPY proto ./proto

# --- Compile gRPC Python code ---
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/delivery.proto

# --- Copy app files ---
COPY . .

# --- Expose Flask port ---
EXPOSE 5000

CMD bash -c "python -u external_hub_listener.py & python -u app.py" 
