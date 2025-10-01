# --- Builder stage ---
FROM rust:1.82 AS builder

# Install necessary system dependencies
RUN apt-get update && apt-get install -y \
    libssl-dev \
    pkg-config \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy Cargo.toml and Cargo.lock first to cache dependencies
COPY Cargo.toml ./

# Create empty src/main.rs to allow cargo fetch
RUN mkdir src && echo "fn main() {}" > src/main.rs

# Fetch dependencies
RUN cargo fetch

# Copy actual source code
COPY src ./src
COPY proto ./proto
COPY build.rs .

# Build the Rust project in release mode
RUN cargo build --release

# --- Runtime stage ---
FROM debian:bookworm-slim

# Install SSL libraries for tonic
RUN apt-get update && apt-get install -y \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy compiled binaries from builder
COPY --from=builder /app/target/release/communication_hub ./communication_hub

# Expose gRPC port
EXPOSE 50051

# Set entrypoint
CMD ["./communication_hub"]
