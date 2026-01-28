# Running on Raspberry Pi

This guide explains how to run the Calgary Council Stream Recorder on a Raspberry Pi.

## Hardware Requirements

### Recommended Setup ⭐
- **Raspberry Pi 4 (4GB or 8GB RAM)**
- **External USB 3.0 SSD or HDD** (500GB+ recommended)
- **Ethernet connection** (more reliable than WiFi)
- **Heatsink or fan** (optional but recommended)
- **Quality power supply** (official RPi power supply recommended)

### Also Works On:
- Raspberry Pi 5 (even better performance)
- Raspberry Pi 3B+ (4GB minimum, will be slower)

### NOT Recommended:
- Raspberry Pi Zero (insufficient RAM/CPU)
- SD card only setup (recordings will wear it out)

## Why Raspberry Pi?

Perfect fit because:
- ✅ Low power consumption (run 24/7 for ~$5/year)
- ✅ Just enough CPU for stream copying (no transcoding!)
- ✅ Quiet operation (no fans needed with heatsink)
- ✅ Small form factor (hide near router)
- ✅ Reliable Linux platform
- ✅ Remote access via SSH/web interface

## Quick Start

### 1. Mount External Drive
```bash
sudo mkdir -p /mnt/usb-drive
sudo mount /dev/sda1 /mnt/usb-drive
sudo chown -R $USER:$USER /mnt/usb-drive
```

### 2. Install Docker
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### 3. Start Recording
```bash
git clone https://github.com/pixeltree/council_feeds.git
cd council_feeds
docker-compose -f docker-compose.rpi.yml up -d --build
```

### 4. Access Dashboard
```
http://raspberrypi.local:5000
```

## Expected Performance

During recording:
- **CPU:** 5-15%
- **RAM:** 150-300 MB
- **Storage:** ~900 MB/hour
- **Power:** 3-5W
- **Temperature:** 45-65°C (with heatsink)

## Storage Estimates

- 4-hour meeting: ~3.6 GB
- Weekly (3 meetings): ~10-15 GB
- Monthly: ~40-60 GB
- Yearly: ~480-720 GB

**Recommendation:** 500GB+ USB drive

## Limitations

✅ **Works perfectly:** Recording, monitoring, web dashboard
❌ **Too heavy:** Transcription (use separate computer)
⚠️ **Slower:** Post-processing (works but slow)

See full documentation for detailed setup, troubleshooting, and optimization tips.
