#!/bin/bash
set -euo pipefail

echo "Stopping service on port 8899..."

PID=$(lsof -t -i:8899 2>/dev/null)

if [ -z "$PID" ]; then
    echo "No process found on port 8899"
else
    kill $PID
    echo "Killed process $PID"
fi

sleep 1

PID=$(lsof -t -i:8899 2>/dev/null)
if [ -z "$PID" ]; then
    echo "Service stopped successfully"
else
    echo "Force killing process $PID..."
    kill -9 $PID
    echo "Service stopped"
fi
