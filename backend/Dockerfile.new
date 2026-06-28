FROM python:3.11-slim-bullseye

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libffi-dev \
    libssl-dev \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (essential for scraping fallback)
RUN playwright install --with-deps chromium

COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE $PORT

# Run Redis in the background, then start the FastAPI server
CMD ["/bin/sh", "start.sh"]
