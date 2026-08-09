# Heltec V4 — standalone Reticulum-node: firmware + bron

Twee dingen in dit pakket:

1. **`heltec_v4_reticulum_TechInc_merged.bin`** — kant-en-klare firmware (één bestand),
   nu ingesteld op WiFi **TechInc**. Direct flashen, niks bouwen.
2. **`heltec_v4_reticulum_bron.tar.gz`** — de complete broncode om zelf te herbouwen
   (bijv. met een ander WiFi-netwerk). Offline buildbaar, geen upstream clonen nodig.

De node draait de volledige Reticulum-stack op het board zelf:
- LoRa lokaal (869.463 MHz / SF8 / BW125 / CR5)
- WiFi → TCP-uplink naar de VPS (`node.reticulumnet.nl:4242`) = LoRa↔internet-bridge
- op een USB-lader volautonoom.

---

## 1. Alleen flashen (geen WiFi-wijziging nodig)

Merged image gaat op offset **0x0**. Heb je `esptool` (`pip install esptool`):

```
esptool --chip esp32s3 -p /dev/ttyACM0 -b 460800 \
  --before default_reset --after hard_reset \
  write_flash 0x0 heltec_v4_reticulum_TechInc_merged.bin
```

Let op: na flashen boot de ESP32-S3 niet altijd vanzelf → USB los/vast of RST-knop.

---

## 2. Zelf herbouwen met ander WiFi (uit de bron)

Uitpakken:

```
tar xzf heltec_v4_reticulum_bron.tar.gz
cd src
```

Je krijgt drie mappen naast elkaar (die verwachten elkaar als sibling):
`microReticulum_Firmware/`, `microReticulum/`, `microStore/`.

### Eenmalig: PlatformIO
```
pipx install platformio        # of: pip install platformio
```

### WiFi instellen — de makkelijke manier (script)
Maak een tekstbestand `wifi.txt`:
```
SSID=NaamVanJouwWiFi
PASS=jouw-wachtwoord
# optioneel (default = het standaard Reticulum-netwerk):
VPS=node.reticulumnet.nl
PORT=4242
```
Sluit de Heltec via USB aan en draai:
```
cd microReticulum_Firmware
./flash-node.sh ../wifi.txt          # schrijft node_config.h, bouwt én flasht
```

### Of handmatig
Bewerk `microReticulum_Firmware/node_config.h`:
```c
#define NODE_WIFI_SSID "JouwWiFi"
#define NODE_WIFI_PSK  "jouw-wachtwoord"
```
Bouwen (en flashen):
```
cd microReticulum_Firmware
~/.local/bin/pio run -e heltec_wifi_lora_32_V4-local-udp -t upload --upload-port /dev/ttyACM0
```
Alleen bouwen (zonder flashen): laat `-t upload ...` weg. De losse binary komt dan in
`.pio/build/heltec_wifi_lora_32_V4-local-udp/rnode_firmware_heltec32v4pa_local.bin`.

> Belangrijk: bij DEZE firmware zit de WiFi **compile-time** ingebakken; er is geen
> portal/serial-manier om het op het board zelf te wijzigen. Ander netwerk = opnieuw bouwen.

---

## Pinned versies (zitten al in de tarball, hier ter referentie)
- microReticulum_Firmware @ `1926f15`
- microReticulum @ `0e318e8` (platte header-layout)
- microStore @ `e18b827`

## Wat de CBA-patches doen (kort)
1. SX1262 TCXO-fix — radio komt online.
2. Signature-bypass (`Device.h`) — vertrouwde zelf-build.
3. Provisioning optioneel + geforceerde TNC (`validate_status()`) — start radio ook op een
   onprovisioneerd board (hardcoded V4-identiteit, model C8, hwrev 1).
4. Console-modus uit (headless).
5. WiFi STA + creds uit `node_config.h`.
6. TCP-client naar de VPS (`TCPClientInterface.h`) — de internet-uplink.

Volledige patchset: `microReticulum_Firmware/` bevat de al-toegepaste wijzigingen;
`cba-patches.diff` (indien meegeleverd) toont het verschil t.o.v. upstream.
