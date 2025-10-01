#!/bin/bash

set -e

PROJECT_NAME="warehouse_robot_simulation"

if [ $# -eq 0 ]; then
    echo -e "No argument provided. Use: $0 {start|stop|restart|status}"
    exit 1
fi

case "$1" in
    start)
        echo -e "Starting simulation containers..."
        docker compose -p $PROJECT_NAME up -d
        echo -e "$Project started."
        ;;
    stop)
        echo -e "Stopping project containers..."
        docker compose -p $PROJECT_NAME down
        echo -e "Project stopped."
        ;;
    restart)
        echo -e "Restarting project containers..."
        docker compose -p $PROJECT_NAME down
        docker compose -p $PROJECT_NAME up -d
        echo -e "Project restarted."
        ;;
    status)
        echo -e "Project container status:"
        docker compose -p $PROJECT_NAME ps
        ;;
    *)
        echo -e "Invalid option. Use: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
