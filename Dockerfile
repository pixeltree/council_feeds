FROM python:3.11-slim

# Install ffmpeg
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir yt-dlp

# Copy application code
COPY main.py .

# Create recordings directory
RUN mkdir -p /recordings

# Run the application
CMD ["python", "-u", "main.py"]
