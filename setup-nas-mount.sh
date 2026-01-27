#!/bin/bash
# Quick NAS mount setup for Calgary Council Recorder

set -e

echo "================================================"
echo "NAS Mount Setup for Calgary Council Recorder"
echo "================================================"
echo ""

# Choose protocol
echo "Choose mount type:"
echo "1) NFS (recommended - faster)"
echo "2) SMB/CIFS (Windows shares)"
read -p "Choice [1-2]: " MOUNT_TYPE

# Get NAS details
read -p "NAS IP address: " NAS_IP
read -p "Share name/path (e.g., /volume1/recordings or recordings): " SHARE_PATH

MOUNT_POINT="/mnt/nas"

if [ "$MOUNT_TYPE" = "1" ]; then
    # NFS setup
    echo ""
    echo "📦 Installing NFS client..."
    sudo apt-get update && sudo apt-get install -y nfs-common
    sudo mkdir -p $MOUNT_POINT
    
    # Test mount
    echo "🔍 Testing NFS mount..."
    if sudo mount -t nfs ${NAS_IP}:${SHARE_PATH} $MOUNT_POINT; then
        echo "✅ Test mount successful!"
        sudo umount $MOUNT_POINT
        
        # Add to fstab
        echo "${NAS_IP}:${SHARE_PATH} $MOUNT_POINT nfs defaults,auto,nofail,_netdev 0 0" | sudo tee -a /etc/fstab
        sudo mount -a
        echo "✅ Added to /etc/fstab for auto-mount on boot"
    else
        echo "❌ Mount failed. Check NAS NFS settings and try again."
        exit 1
    fi
    
elif [ "$MOUNT_TYPE" = "2" ]; then
    # SMB setup
    echo ""
    echo "📦 Installing SMB/CIFS client..."
    sudo apt-get update && sudo apt-get install -y cifs-utils
    sudo mkdir -p $MOUNT_POINT
    
    # Get credentials
    read -p "NAS username: " NAS_USER
    read -s -p "NAS password: " NAS_PASS
    echo ""
    
    # Create credentials file
    echo "username=$NAS_USER" | sudo tee /root/.smbcredentials > /dev/null
    echo "password=$NAS_PASS" | sudo tee -a /root/.smbcredentials > /dev/null
    sudo chmod 600 /root/.smbcredentials
    
    # Test mount
    echo "🔍 Testing SMB mount..."
    if sudo mount -t cifs //${NAS_IP}/${SHARE_PATH} $MOUNT_POINT -o credentials=/root/.smbcredentials; then
        echo "✅ Test mount successful!"
        sudo umount $MOUNT_POINT
        
        # Add to fstab
        echo "//${NAS_IP}/${SHARE_PATH} $MOUNT_POINT cifs credentials=/root/.smbcredentials,uid=1000,gid=1000,nofail,_netdev 0 0" | sudo tee -a /etc/fstab
        sudo mount -a
        echo "✅ Added to /etc/fstab for auto-mount on boot"
    else
        echo "❌ Mount failed. Check NAS SMB settings and try again."
        exit 1
    fi
fi

# Create recordings directory
sudo mkdir -p $MOUNT_POINT/recordings
sudo chown -R $USER:$USER $MOUNT_POINT

echo ""
echo "✅ NAS mount setup complete!"
echo ""
echo "Mount point: $MOUNT_POINT"
echo "Recordings will be saved to: $MOUNT_POINT/recordings"
echo ""
df -h $MOUNT_POINT
echo ""
echo "Next steps:"
echo "1. Update docker-compose.nas.yml if needed"
echo "2. Run: docker-compose -f docker-compose.nas.yml up -d --build"
