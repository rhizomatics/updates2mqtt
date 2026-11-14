#!/bin/bash

# Health Check Script
#
# Reads the heartbeat file the app writes on every heartbeat, rather than subscribing to the
# heartbeat topic, so it doesn't open a second MQTT connection. Brokers set to use the username
# as the client id, such as EMQX with `use_username_as_clientid`, treat a second connection with
# the same username as the same client, and kick the app off its session.
#
# The file holds `<alive epoch> <mqtt acknowledged epoch>`:
#   - alive is written on every heartbeat, so if it's stale the app is wedged, and is restarted
#   - mqtt is written only when the broker acknowledged the heartbeat publish, so if it's stale
#     the MQTT connection is down, reported as unhealthy, without restarting, as that won't help
#
# Arguments, both optional, as before:
#   $1 heartbeat topic, no longer used, kept so existing compose healthchecks still work
#   $2 how old a heartbeat can be before failing, in seconds, default 480
# Environment:
#   U2M_HEARTBEAT_FILE, as for the app, else updates2mqtt.heartbeat in $TMPDIR or /tmp, the app's default

TIMEOUT_SECONDS=${2:-480}
HEARTBEAT_FILE="${U2M_HEARTBEAT_FILE:-${TMPDIR:-/tmp}/updates2mqtt.heartbeat}"

EXIT_SUCCESS=0
EXIT_STALE_HEARTBEAT=1
EXIT_NO_HEARTBEAT=2
EXIT_INVALID_DATA=3

info() {
    echo "$1" >&2
}

error() {
    echo "ERROR: $1" >&2
}

if [ ! -f "$HEARTBEAT_FILE" ]; then
    # nothing to judge yet, e.g. still starting, which the compose start_period allows for
    error "No heartbeat file at $HEARTBEAT_FILE yet"
    exit $EXIT_NO_HEARTBEAT
fi

read -r alive mqtt_acked < "$HEARTBEAT_FILE"
if ! [[ "$alive" =~ ^[0-9]+$ && "$mqtt_acked" =~ ^[0-9]+$ ]]; then
    error "Unexpected heartbeat file contents: $(head -c 100 "$HEARTBEAT_FILE")"
    exit $EXIT_INVALID_DATA
fi

current_time=$(date +%s)
alive_age=$((current_time - alive))
mqtt_age=$((current_time - mqtt_acked))
info "Heartbeat age ${alive_age}s, last acknowledged by MQTT broker ${mqtt_age}s ago"

if [ $alive_age -gt $TIMEOUT_SECONDS ]; then
    error "Heartbeat is ${alive_age}s old (threshold: ${TIMEOUT_SECONDS}s)"
    # Docker does not restart containers solely because a healthcheck fails, it just
    # marks them unhealthy. If the main process is wedged (e.g. a self-update via
    # `docker compose up` blocked waiting for this container to stop), kill PID 1 so
    # the container exits and "restart: always" brings it back up.
    error "Killing main process (PID 1) to force a restart"
    kill -TERM 1 2>/dev/null
    exit $EXIT_STALE_HEARTBEAT
fi

if [ "$mqtt_acked" -eq 0 ] || [ $mqtt_age -gt $TIMEOUT_SECONDS ]; then
    error "MQTT broker hasn't acknowledged a heartbeat in ${TIMEOUT_SECONDS}s, check the broker and MQTT settings"
    exit $EXIT_STALE_HEARTBEAT
fi

info "SUCCESS: Heartbeat is fresh and acknowledged by the MQTT broker"
exit $EXIT_SUCCESS
