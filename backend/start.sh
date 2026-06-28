#!/bin/sh
# Start Redis server in background
redis-server --bind 0.0.0.0 --protected-mode no --daemonize yes

# Wait until Redis is accepting connections (up to 30 seconds)
echo "Waiting for Redis to be ready..."
for i in $(seq 1 30); do
    if redis-cli ping | grep -q PONG; then
        echo "Redis is ready after ${i}s"
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 1
done

# Start the FastAPI application
echo "Starting Gunicorn..."
exec gunicorn app.main:app \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT:-8000}" \
    --timeout 120 \
    --log-level info
