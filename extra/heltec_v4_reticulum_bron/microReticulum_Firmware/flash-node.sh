#!/bin/bash
# flash-node.sh — flash de standalone microReticulum Heltec V4-node met WiFi-creds
# uit een tekstbestand, zodat je 'm voor iemand anders kunt flashen zonder code te bewerken.
#
# Gebruik:   ./flash-node.sh <config.txt> [serieele-poort]
# Voorbeeld: ./flash-node.sh wifi.txt /dev/ttyACM0
#
# Formaat van het config-bestand (één per regel, volgorde maakt niet uit):
#   SSID=NetwerkNaam
#   PASS=wachtwoord
#   VPS=node.reticulumnet.nl     (optioneel, default node.reticulumnet.nl)
#   PORT=4242                    (optioneel, default 4242)
set -e
FWDIR="$HOME/src/microReticulum_Firmware"
ENV="heltec_wifi_lora_32_V4-local-udp"
PIO="$HOME/.local/bin/pio"
CONF="${1:?Geef een config-bestand op, bv: ./flash-node.sh wifi.txt}"
PORT="${2:-/dev/ttyACM0}"

SSID=""; PASS=""; VPS="node.reticulumnet.nl"; VPORT="4242"
while IFS='=' read -r k v; do
  k="$(echo "$k" | tr -d ' \t\r')"
  v="$(echo "$v" | sed 's/\r$//')"
  case "$k" in
    SSID)     SSID="$v" ;;
    PASS|PSK) PASS="$v" ;;
    VPS|HOST) VPS="$v"  ;;
    PORT)     VPORT="$v";;
  esac
done < "$CONF"

[ -z "$SSID" ] && { echo "FOUT: geen SSID= in $CONF"; exit 1; }
[ -z "$PASS" ] && { echo "FOUT: geen PASS= in $CONF"; exit 1; }

echo ">> Node-config:  SSID='$SSID'   VPS='$VPS:$VPORT'   poort=$PORT"

cat > "$FWDIR/node_config.h" <<EOF
// Gegenereerd door flash-node.sh uit '$CONF' — niet handmatig bewerken.
#ifndef NODE_CONFIG_H
#define NODE_CONFIG_H
#define NODE_WIFI_SSID "$SSID"
#define NODE_WIFI_PSK  "$PASS"
#define NODE_VPS_HOST  "$VPS"
#define NODE_VPS_PORT  $VPORT
#endif
EOF

echo ">> Bouwen + flashen ($ENV) ..."
cd "$FWDIR"
"$PIO" run -e "$ENV" -t upload --upload-port "$PORT"
echo ">> Klaar — node geflasht voor WiFi '$SSID'."
echo ">> Zet 'm op een USB-lader; hij verbindt zelf met WiFi en de VPS."
