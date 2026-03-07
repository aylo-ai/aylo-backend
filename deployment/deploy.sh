#!/bin/bash
set -e

NGINX_CONF="/etc/nginx/sites-available/api.repli.uz"
HEALTH_CHECK_RETRIES=30
HEALTH_CHECK_INTERVAL=2

# Determine which color is currently active by checking nginx config
get_active_color() {
    if grep -q "localhost:8001" "$NGINX_CONF"; then
        echo "blue"
    elif grep -q "localhost:8002" "$NGINX_CONF"; then
        echo "green"
    else
        echo "none"
    fi
}

get_port() {
    case "$1" in
        blue) echo 8001 ;;
        green) echo 8002 ;;
    esac
}

# Wait for the new deployment to be healthy
wait_for_health() {
    local port=$1
    local retries=$HEALTH_CHECK_RETRIES

    echo "Waiting for health check on port $port..."
    while [ $retries -gt 0 ]; do
        if curl -sf "http://localhost:${port}/health/" > /dev/null 2>&1; then
            echo "Health check passed!"
            return 0
        fi
        retries=$((retries - 1))
        echo "Health check failed, retrying in ${HEALTH_CHECK_INTERVAL}s... ($retries attempts left)"
        sleep $HEALTH_CHECK_INTERVAL
    done

    echo "ERROR: Health check failed after all retries"
    return 1
}

# Switch nginx to point to the new port
switch_nginx() {
    local old_port=$1
    local new_port=$2

    echo "Switching nginx from port $old_port to port $new_port..."
    sudo sed -i "s/localhost:${old_port}/localhost:${new_port}/g" "$NGINX_CONF"
    sudo nginx -t && sudo systemctl reload nginx
    echo "Nginx switched successfully!"
}

# Main deployment logic
main() {
    ACTIVE_COLOR=$(get_active_color)

    if [ "$ACTIVE_COLOR" = "blue" ]; then
        NEW_COLOR="green"
        OLD_COLOR="blue"
    else
        # If none or green is active, deploy blue
        NEW_COLOR="blue"
        OLD_COLOR="green"
    fi

    NEW_PORT=$(get_port "$NEW_COLOR")
    OLD_PORT=$(get_port "$OLD_COLOR")

    echo "============================================"
    echo "  Blue/Green Deployment"
    echo "  Active: $ACTIVE_COLOR -> New: $NEW_COLOR"
    echo "============================================"

    # Step 1: Build and start the new color
    echo ""
    echo "[1/5] Building and starting $NEW_COLOR..."
    docker compose --profile "$NEW_COLOR" build
    docker compose --profile "$NEW_COLOR" up -d

    # Step 2: Wait for health check
    echo ""
    echo "[2/5] Running health checks..."
    if ! wait_for_health "$NEW_PORT"; then
        echo "Deployment failed! Rolling back..."
        docker compose --profile "$NEW_COLOR" stop "web-${NEW_COLOR}"
        docker compose --profile "$NEW_COLOR" rm -f "web-${NEW_COLOR}"
        exit 1
    fi

    # Step 3: Switch nginx
    echo ""
    echo "[3/5] Switching traffic to $NEW_COLOR..."
    if [ "$ACTIVE_COLOR" = "none" ]; then
        # First deployment: replace localhost:8000 with the new port
        sudo sed -i "s/localhost:8000/localhost:${NEW_PORT}/g" "$NGINX_CONF"
        sudo nginx -t && sudo systemctl reload nginx
    else
        switch_nginx "$OLD_PORT" "$NEW_PORT"
    fi

    # Step 4: Stop old color
    echo ""
    echo "[4/5] Stopping old $OLD_COLOR deployment..."
    if [ "$ACTIVE_COLOR" != "none" ]; then
        docker compose --profile "$OLD_COLOR" stop "web-${OLD_COLOR}"
        docker compose --profile "$OLD_COLOR" rm -f "web-${OLD_COLOR}"
    fi

    # Step 5: Rebuild celery workers
    echo ""
    echo "[5/5] Rebuilding celery workers..."
    docker compose up -d --build celery_worker celery_beat

    # Cleanup
    echo ""
    echo "Pruning old images..."
    yes | docker image prune

    echo ""
    echo "============================================"
    echo "  Deployment complete!"
    echo "  Active: $NEW_COLOR (port $NEW_PORT)"
    echo "============================================"
}

main
