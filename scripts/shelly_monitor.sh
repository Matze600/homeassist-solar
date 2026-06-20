#!/bin/bash
# System-Monitor: Shellys + Hoymiles Wechselrichter
# Läuft alle 5 Minuten via Cron

HA_URL="http://localhost:8123"
HA_TOKEN_FILE="/home/home/homeassistant/.env"
TIMEOUT=5
HOYMILES_ZERO_FLAG="/tmp/hoymiles_zero_flag"

HA_TOKEN=$(grep HA_BEARER_TOKEN "$HA_TOKEN_FILE" | cut -d= -f2)

notify() {
    local title="$1"
    local message="$2"
    local notification_id="$3"
    curl -s -X POST "$HA_URL/api/services/persistent_notification/create" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"title\": \"$title\", \"message\": \"$message\", \"notification_id\": \"$notification_id\"}" \
        > /dev/null
}

# ---------------------------------------------------------------------------
# Shelly Erreichbarkeit
# ---------------------------------------------------------------------------
declare -A SHELLYS=(
    ["Heizstab L1"]="192.168.178.86"
    ["Heizstab L2"]="192.168.178.91"
    ["Heizstab L3"]="192.168.178.94"
)

OFFLINE=()
for NAME in "${!SHELLYS[@]}"; do
    IP="${SHELLYS[$NAME]}"
    STATUS=$(curl -s --max-time $TIMEOUT "http://$IP/rpc/Switch.GetStatus?id=0" 2>/dev/null)
    if [ -z "$STATUS" ] || ! echo "$STATUS" | grep -q "output"; then
        OFFLINE+=("$NAME ($IP)")
    fi
done

if [ ${#OFFLINE[@]} -gt 0 ]; then
    MSG="Nicht erreichbar: $(IFS=', '; echo "${OFFLINE[*]}") — $(date '+%H:%M Uhr')"
    notify "Shelly offline" "$MSG" "shelly_offline"
    logger -t shelly_monitor "OFFLINE: ${OFFLINE[*]}"
fi

# ---------------------------------------------------------------------------
# Hoymiles Wechselrichter — 0W Erkennung tagsüber (09:00–18:00)
# Erst beim 2. Treffer in Folge melden (=10 Min. anhaltend)
# ---------------------------------------------------------------------------
HOUR=$(date +%H)
if [ "$HOUR" -ge 9 ] && [ "$HOUR" -lt 18 ]; then
    PV_STATE=$(curl -s --max-time $TIMEOUT \
        "$HA_URL/api/states/sensor.wechselrichter_ac_leistung" \
        -H "Authorization: Bearer $HA_TOKEN" 2>/dev/null | \
        python3 -c "import json,sys; print(json.load(sys.stdin)['state'])" 2>/dev/null)

    PV_WATT=$(echo "$PV_STATE" | python3 -c "import sys; print(float(sys.stdin.read().strip()))" 2>/dev/null || echo "999")

    if (( $(echo "$PV_WATT < 5" | python3 -c "import sys; print(int(eval(sys.stdin.read())))") )); then
        if [ -f "$HOYMILES_ZERO_FLAG" ]; then
            # Zweiter Treffer — jetzt melden
            MSG="Hoymiles zeigt seit >10 Min. 0W tagsüber — Wechselrichter prüfen! ($(date '+%H:%M Uhr'))"
            notify "Hoymiles 0W" "$MSG" "hoymiles_zero"
            logger -t shelly_monitor "HOYMILES 0W seit >10min"
        else
            # Erster Treffer — Flag setzen, noch nicht melden
            touch "$HOYMILES_ZERO_FLAG"
        fi
    else
        # Wechselrichter läuft — Flag löschen, evtl. alte Meldung wegräumen
        rm -f "$HOYMILES_ZERO_FLAG"
        curl -s -X POST "$HA_URL/api/services/persistent_notification/dismiss" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d '{"notification_id": "hoymiles_zero"}' > /dev/null
    fi
fi
