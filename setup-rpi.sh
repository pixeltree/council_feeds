#!/bin/bash
# Setup script for Raspberry Pi

set -e

echo "================================================"
echo "Calgary Council Recorder - Raspberry Pi Setup"
echo "================================================"
echo ""

# Check if running on ARM
ARCH=$(uname -m)
if [[ ! "$ARCH" =~ (arm|aarch64) ]]; then
    echo "⚠️  Warning: This script is designed for Raspberry Pi (ARM architecture)"
    echo "   Detected: $ARCH"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for Docker
echo "📦 Checking for Docker..."
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "✅ Docker installed. Please logout and login for group membership to take effect."
    echo "   Then run this script again."
    exit 0
else
    echo "✅ Docker found"
fi

# Check for Docker Compose
echo "📦 Checking for Docker Compose..."
if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo apt-get update
    sudo apt-get install -y docker-compose
fi
echo "✅ Docker Compose found"

# Prompt for USB drive mount point
echo ""
echo "🔍 Looking for USB drives..."
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT | grep -v loop || true
echo ""
echo "Default mount point: /mnt/usb-drive"
read -p "USB drive mount point [/mnt/usb-drive]: " MOUNT_POINT
MOUNT_POINT=${MOUNT_POINT:-/mnt/usb-drive}

# Check if mount point exists
if [ ! -d "$MOUNT_POINT" ]; then
    echo "⚠️  Mount point $MOUNT_POINT does not exist"
    read -p "Create it? (Y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        sudo mkdir -p "$MOUNT_POINT"
        echo "✅ Created $MOUNT_POINT"
    fi
fi

# Create recordings directory
RECORDINGS_DIR="$MOUNT_POINT/recordings"
echo "📁 Setting up recordings directory: $RECORDINGS_DIR"
sudo mkdir -p "$RECORDINGS_DIR"
sudo chown -R $USER:$USER "$RECORDINGS_DIR" 2>/dev/null || true
echo "✅ Recordings directory ready"

# Update docker-compose.rpi.yml with correct mount
echo "⚙️  Updating docker-compose.rpi.yml..."
if [ -f "docker-compose.rpi.yml" ]; then
    sed -i.bak "s|/mnt/usb-drive/recordings|$RECORDINGS_DIR|g" docker-compose.rpi.yml
    echo "✅ Configuration updated"
fi

# Check available space
echo ""
echo "💾 Storage Information:"
df -h "$MOUNT_POINT" 2>/dev/null || echo "   Mount point not accessible"

# Estimate capacity
AVAILABLE_GB=$(df -BG "$MOUNT_POINT" 2>/dev/null | tail -1 | awk '{print $4}' | sed 's/G//' || echo "0")
if [ "$AVAILABLE_GB" -gt 100 ]; then
    ESTIMATED_HOURS=$((AVAILABLE_GB / 1))
    echo "   Estimated capacity: ~$ESTIMATED_HOURS hours of meetings"
fi

# Build and start
echo ""
read -p "🚀 Build and start the recorder now? (Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo "🏗️  Building Docker image (this may take 5-10 minutes)..."
    docker-compose -f docker-compose.rpi.yml up -d --build
    
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "📊 Access the dashboard:"
    IP=$(hostname -I | awk '{print $1}')
    echo "   http://$IP:5000"
    echo "   http://$(hostname).local:5000"
    echo ""
    echo "📋 View logs:"
    echo "   docker-compose -f docker-compose.rpi.yml logs -f"
    echo ""
    echo "🔧 Monitor resources:"
    echo "   docker stats calgary-council-recorder-rpi"
    echo ""
fi

echo "📖 See docs/RASPBERRY_PI.md for detailed documentation"
