#!/bin/bash

# MQTT Health Check Script
# Checks if the heartbeat timestamp in MQTT payload is recent enough
# Requires MQTT connection details to be available as environment variables
#   - MQTT_HOST (defaults to localhost)
#   - MQTT_PORT (defaults to 1883)
#   - MQTT_USER (no default)
#   - MQTT_PASS (no default)

# Arguments
MQTT_TOPIC=$1
TIMEOUT_SECONDS=${2:-480}  # How old the heartbeat can be before failing
log_file="/var/log/healthcheck.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a $log_file
}

if [ -z "$MQTT_TOPIC" ] ; then
    log "ERROR: MQTT topic not provided as first argument"
    exit $EXIT_DEPENDENCY_ERROR
fi

# Configuration
MQTT_HOST="${MQTT_HOST:-localhost}"
MQTT_PORT="${MQTT_PORT:-1883}"
SUBSCRIBE_TIMEOUT="${SUBSCRIBE_TIMEOUT:-10}"  # How long to wait for a message

# Exit codes
EXIT_SUCCESS=0
EXIT_STALE_HEARTBEAT=1
EXIT_NO_MESSAGE=2
EXIT_INVALID_DATA=3
EXIT_DEPENDENCY_ERROR=4

# Check if required commands are available
if ! command -v mosquitto_sub &> /dev/null; then
    log "ERROR: mosquitto_sub command not found"
    exit $EXIT_DEPENDENCY_ERROR
fi

if ! command -v jq &> /dev/null; then
    log "ERROR: jq command not found (required for JSON parsing)"
    exit $EXIT_DEPENDENCY_ERROR
fi

# Get current timestamp
current_time=$(date +%s)

# Subscribe to MQTT topic and get one message
echo "Subscribing to topic: $MQTT_TOPIC on $MQTT_HOST:$MQTT_PORT" >&2
mqtt_payload=$(mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASS" -t "$MQTT_TOPIC" -C 1 -W "$SUBSCRIBE_TIMEOUT" 2>&1)
sub_result=$?

# Check if mosquitto_sub succeeded
if [ $sub_result -ne 0 ]; then
    log "ERROR: Failed to receive message from MQTT broker"
    log "mosquitto_sub output: $mqtt_payload"
    exit $EXIT_NO_MESSAGE
fi

# Check if we got empty payload
if [ -z "$mqtt_payload" ]; then
    log "ERROR: No message received within ${SUBSCRIBE_TIMEOUT}s timeout"
    exit $EXIT_NO_MESSAGE
fi

echo "Received heartbeat payload: $mqtt_payload" >&2

# Extract heartbeat_raw timestamp from JSON
heartbeat_raw=$(echo "$mqtt_payload" | jq -r '.heartbeat_raw // empty' 2>/dev/null)

if [ -z "$heartbeat_raw" ] || [ "$heartbeat_raw" == "null" ]; then
    log "ERROR: Could not extract heartbeat_raw from payload"
    log "PAYLOAD: $mqtt_payload"
    exit $EXIT_INVALID_DATA
fi

# Convert to integer (remove decimal part)
heartbeat_timestamp=${heartbeat_raw%.*}

# Calculate age of the heartbeat
age=$((current_time - heartbeat_timestamp))

echo "Heartbeat timestamp: $heartbeat_timestamp" >&2
echo "Current timestamp: $current_time" >&2
echo "Heartbeat age: ${age}s" >&2

# Check if heartbeat is too old
if [ $age -gt $TIMEOUT_SECONDS ]; then
    log "FAILED: Heartbeat is ${age}s old (threshold: ${TIMEOUT_SECONDS}s)"
    # Docker does not restart containers solely because a healthcheck fails, it just
    # marks them unhealthy. If the main process is wedged (e.g. a self-update via
    # `docker compose up` blocked waiting for this container to stop), kill PID 1 so
    # the container exits and "restart: always" brings it back up.
    log "Killing main process (PID 1) to force a restart"
    kill -TERM 1 2>/dev/null
    exit $EXIT_STALE_HEARTBEAT
fi

echo "SUCCESS: Heartbeat is fresh (${age}s old)" >&2
exit $EXIT_SUCCESS
