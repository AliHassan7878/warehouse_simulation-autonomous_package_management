#!/bin/bash

set -e

echo -e "Checking for Docker..."

# --- Install Docker if missing ---
if ! command -v docker &> /dev/null
then
    echo -e "Docker not found. Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm -f get-docker.sh
    echo -e "Docker installed."
else
    echo -e "Docker already installed."
fi

# --- Install Docker Compose if missing ---
echo -e "Checking for Docker Compose..."

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null
then
    echo -e "Docker Compose not found. Installing Docker Compose v2..."
    DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
    mkdir -p $DOCKER_CONFIG/cli-plugins
    curl -SL https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64 \
        -o $DOCKER_CONFIG/cli-plugins/docker-compose
    chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
    echo -e "Docker Compose installed."
else
    echo -e "Docker Compose already installed."
fi

# --- Build project ---
echo -e "$Building project with Docker Compose (no cache)..."

docker compose build --no-cache

echo -e "Build completed successfully."