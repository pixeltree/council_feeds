FROM python:3.11-slim

# Install ffmpeg and ffprobe
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
COPY database.py .
COPY web_server.py .
COPY services.py .
COPY config.py .
COPY post_processor.py .

# Create recordings directory
RUN mkdir -p /recordings

# Expose web interface port
EXPOSE 5000

# Run the application
CMD ["python", "-u", "main.py"]
