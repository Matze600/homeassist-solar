# homeassist-solar

Home Assistant Setup zur zentralen Überwachung einer PV-Anlage mit **Hoymiles HMS-1600-4T** (Mikrowechselrichter) und **SMA Wechselrichter** — inkl. Mosquitto MQTT Broker, Solar-Dashboard und HACS-Integrationen.

## Hardware

| Gerät | Modell | IP |
|---|---|---|
| Hoymiles Mikrowechselrichter | HMS-1600-4T | — |
| Hoymiles DTU-Lite | ESP32-basiert | 192.168.178.65 |
| SMA Wechselrichter | SN: 3015681731 | 192.168.178.51 |
| SMA Sunny Home Manager 2.0 | SN: 3016913494 | 192.168.178.45 |
| Home Server | Linux Mint 22.3 Notebook | 192.168.178.71 |

## Stack

- **Home Assistant** `homeassistant/home-assistant:stable`
- **Mosquitto MQTT Broker** `eclipse-mosquitto:latest`
- **Docker Compose** für einfaches Deployment

## Integrationen

| Integration | Beschreibung |
|---|---|
| [SMA Solar](https://www.home-assistant.io/integrations/sma/) | SMA Wechselrichter via Webconnect (SSL) |
| [hoymiles-wifi](https://github.com/suaveolent/ha-hoymiles-wifi) | Hoymiles DTU-Lite via lokale API (HACS) |
| [HACS](https://hacs.xyz/) | Home Assistant Community Store |
| MQTT | Mosquitto Broker für zukünftige Erweiterungen |

## Dashboard

Solar-Dashboard mit:
- Aktuelle PV-Leistung (Gauge) für beide Wechselrichter
- Tages- und Gesamtertrag pro Panel (Hoymiles, 4 Ports)
- Netzleistung (Bezug/Einspeisung)
- Wechselrichter-Details (Temperatur, Spannung, Frequenz, Status)

## Installation

### Voraussetzungen
- Docker & Docker Compose
- Linux (getestet auf Linux Mint 22.3)

### Setup

```bash
git clone https://github.com/Matze600/homeassist-solar.git
cd homeassist-solar
docker compose up -d
```

Home Assistant ist dann erreichbar unter `http://<IP>:8123`

### HACS & hoymiles-wifi installieren

1. In HA: **Einstellungen → Geräte & Dienste → Integration hinzufügen → HACS**
2. GitHub-Account verknüpfen
3. HACS → Benutzerdefinierte Repositories → `suaveolent/ha-hoymiles-wifi` (Typ: Integration)
4. hoymiles-wifi herunterladen und HA neu starten
5. Integration einrichten mit IP der DTU-Lite

### SMA Solar einrichten

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → SMA Solar**
2. Host: IP des SMA Wechselrichters
3. SSL aktivieren, Zertifikat-Verifizierung deaktivieren
4. Passwort vom Geräteetikett eingeben

## Hinweise

- Der **SMA Sunny Home Manager 2.0** kommuniziert ausschließlich über Speedwire UDP Multicast und hat keine Webconnect-Schnittstelle. Die Netzleistung wird stattdessen über den SMA Wechselrichter (`sensor.sn_XXXXXXX_grid_power`) ausgelesen.
- Mosquitto ist ohne Authentifizierung konfiguriert — nur für lokales Netzwerk geeignet.
