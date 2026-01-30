FROM python:3.11-slim

# Install system dependencies in a single layer
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (changes least frequently)
COPY requirements.txt .

# Install Python dependencies with pip cache mount for faster rebuilds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout=1000 --retries=5 -r requirements.txt && \
    pip install yt-dlp

# Copy application code (changes most frequently)
COPY *.py ./
COPY services/ ./services/
COPY transcription/ ./transcription/
COPY database/ ./database/
COPY templates/ ./templates/

# Create recordings directory
RUN mkdir -p /recordings

# Expose web interface port
EXPOSE 5000

# Run the application
CMD ["python", "-u", "main.py"]
