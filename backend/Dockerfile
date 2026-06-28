FROM python:3.11-slim-bullseye

# Install system dependencies for Playwright + redis-cli for health check
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libffi-dev \
    libssl-dev \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (essential for scraping fallback)
RUN playwright install --with-deps chromium

COPY . .

# Make startup script executable
RUN chmod +x start_worker.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Start the Celery worker via startup script (waits for Redis first)
CMD ["/bin/sh", "start_worker.sh"]
