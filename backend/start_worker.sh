#!/bin/sh
# Wait for Redis (on the backend container) to be ready before starting Celery
echo "Waiting for Redis at $REDIS_URL to be ready..."

# Extract host and port from REDIS_URL
REDIS_HOST=$(echo $REDIS_URL | sed 's|redis://||' | sed 's|/.*||' | cut -d: -f1)
REDIS_PORT=$(echo $REDIS_URL | sed 's|redis://||' | sed 's|/.*||' | cut -d: -f2)
REDIS_PORT=${REDIS_PORT:-6379}

for i in $(seq 1 60); do
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG; then
        echo "Redis is ready after ${i}s"
        break
    fi
    echo "Waiting for Redis... ($i/60)"
    sleep 1
done

echo "Starting Celery worker..."
exec celery -A celery_app worker --loglevel=info --concurrency=1
