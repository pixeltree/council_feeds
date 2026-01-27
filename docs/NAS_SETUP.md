# Using NAS for Storage

Recording to your NAS is the ideal setup - you get unlimited storage, redundancy, and backups without any additional hardware!

## Why NAS is Perfect

✅ **Unlimited storage** - Use what you already have  
✅ **RAID protection** - Data is safe  
✅ **Automatic backups** - If your NAS already backs up  
✅ **No extra hardware cost** - Use existing infrastructure  
✅ **Network accessible** - Access recordings from any device  
✅ **Professional solution** - Like a real archival system  

## Setup Options

You have two options to connect Raspberry Pi to NAS:

### Option 1: NFS (Recommended - Faster) ⭐

**On your NAS:**
1. Enable NFS service
2. Create a shared folder (e.g., "council_recordings")
3. Set permissions to allow your RPi's IP address
4. Note the NFS path (e.g., `192.168.1.100:/volume1/council_recordings`)

**On Raspberry Pi:**
```bash
# Install NFS client
sudo apt-get update
sudo apt-get install -y nfs-common

# Create mount point
sudo mkdir -p /mnt/nas/recordings

# Test mount (replace with your NAS IP and path)
sudo mount -t nfs 192.168.1.100:/volume1/council_recordings /mnt/nas/recordings

# If it works, make it permanent
sudo nano /etc/fstab

# Add this line (replace with your details):
192.168.1.100:/volume1/council_recordings /mnt/nas/recordings nfs defaults,auto,nofail 0 0

# Mount it
sudo mount -a

# Verify
df -h /mnt/nas/recordings
```

### Option 2: SMB/CIFS (Windows Shares)

**On your NAS:**
1. Enable SMB/CIFS service
2. Create a shared folder
3. Create user with write permissions
4. Note the share path (e.g., `//192.168.1.100/council_recordings`)

**On Raspberry Pi:**
```bash
# Install CIFS utilities
sudo apt-get update
sudo apt-get install -y cifs-utils

# Create mount point
sudo mkdir -p /mnt/nas/recordings

# Create credentials file (more secure than fstab)
sudo nano /root/.smbcredentials

# Add these lines (replace with your credentials):
username=your_nas_user
password=your_nas_password

# Secure the file
sudo chmod 600 /root/.smbcredentials

# Test mount (replace with your NAS IP and share name)
sudo mount -t cifs //192.168.1.100/council_recordings /mnt/nas/recordings -o credentials=/root/.smbcredentials

# If it works, make it permanent
sudo nano /etc/fstab

# Add this line (all on one line):
//192.168.1.100/council_recordings /mnt/nas/recordings cifs credentials=/root/.smbcredentials,uid=1000,gid=1000,nofail 0 0

# Mount it
sudo mount -a

# Verify
df -h /mnt/nas/recordings
```

## Quick Setup Script

```bash
#!/bin/bash
# setup-nas-mount.sh

echo "NAS Mount Setup for Calgary Council Recorder"
echo "============================================"
echo ""

# Choose protocol
echo "Choose mount type:"
echo "1) NFS (recommended - faster)"
echo "2) SMB/CIFS (Windows shares)"
read -p "Choice [1-2]: " MOUNT_TYPE

# Get NAS details
read -p "NAS IP address: " NAS_IP
read -p "Share name/path: " SHARE_PATH

MOUNT_POINT="/mnt/nas/recordings"

if [ "$MOUNT_TYPE" = "1" ]; then
    # NFS setup
    echo "Setting up NFS mount..."
    sudo apt-get update && sudo apt-get install -y nfs-common
    sudo mkdir -p $MOUNT_POINT
    
    # Test mount
    if sudo mount -t nfs ${NAS_IP}:${SHARE_PATH} $MOUNT_POINT; then
        echo "✅ Test mount successful!"
        
        # Add to fstab
        echo "${NAS_IP}:${SHARE_PATH} $MOUNT_POINT nfs defaults,auto,nofail 0 0" | sudo tee -a /etc/fstab
        echo "✅ Added to /etc/fstab for auto-mount on boot"
    else
        echo "❌ Mount failed. Check NAS settings and try again."
        exit 1
    fi
    
elif [ "$MOUNT_TYPE" = "2" ]; then
    # SMB setup
    echo "Setting up SMB/CIFS mount..."
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
    if sudo mount -t cifs //${NAS_IP}/${SHARE_PATH} $MOUNT_POINT -o credentials=/root/.smbcredentials; then
        echo "✅ Test mount successful!"
        
        # Add to fstab
        echo "//${NAS_IP}/${SHARE_PATH} $MOUNT_POINT cifs credentials=/root/.smbcredentials,uid=1000,gid=1000,nofail 0 0" | sudo tee -a /etc/fstab
        echo "✅ Added to /etc/fstab for auto-mount on boot"
    else
        echo "❌ Mount failed. Check NAS settings and try again."
        exit 1
    fi
fi

# Create recordings directory
sudo mkdir -p $MOUNT_POINT/recordings
sudo chown -R $USER:$USER $MOUNT_POINT

echo ""
echo "✅ NAS mount setup complete!"
echo "Mount point: $MOUNT_POINT"
df -h $MOUNT_POINT
