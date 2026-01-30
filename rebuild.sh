#!/bin/bash

# Script to rebuild and restart the Calgary Council Recorder Docker container

set -e  # Exit on error

echo "======================================"
echo "Rebuilding Calgary Council Recorder"
echo "======================================"
echo ""

# Stop and remove existing container
echo "→ Stopping existing container..."
docker stop calgary-council-recorder 2>/dev/null || echo "  (no container running)"
docker rm calgary-council-recorder 2>/dev/null || echo "  (no container to remove)"
echo ""

# Rebuild the Docker image
echo "→ Building Docker image..."
docker build -t calgary-council-recorder .
echo ""

# Start the container with environment variables
echo "→ Starting container..."
docker run -d \
  --name calgary-council-recorder \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/recordings:/app/recordings \
  --env-file .env \
  calgary-council-recorder

echo ""
echo "======================================"
echo "✅ Container rebuilt and started!"
echo "======================================"
echo ""
echo "Web UI: http://localhost:5000"
echo ""
echo "View logs: docker logs -f calgary-council-recorder"
echo "Stop:      docker stop calgary-council-recorder"
echo ""
