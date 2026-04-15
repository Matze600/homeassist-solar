# homeassist-solar

Home Assistant Setup zur zentralen Überwachung und Steuerung einer PV-Anlage mit **Hoymiles HMS-1600-4T** (Mikrowechselrichter) und **SMA Wechselrichter** — inkl. automatischer Heizstab-Steuerung per Solar-Überschuss, BL-Net Monitoring, Mosquitto MQTT Broker und Solar-Dashboard.

## Hardware

| Gerät | Modell | IP |
|---|---|---|
| Hoymiles Mikrowechselrichter | HMS-1600-4T | — |
| Hoymiles DTU-Lite | ESP32-basiert | 192.168.178.65 |
| SMA Wechselrichter | SN: XXXXXXXXXX | 192.168.178.51 |
| SMA Sunny Home Manager 2.0 | SN: XXXXXXXXXX | 192.168.178.45 |
| Heizungssteuerung | Technische Alternative UVR1611 + BL-Net V2.19 | 192.168.178.150 |
| Ökofen Pellematic | Pelletheizung | 192.168.178.99 |
| Home Server | Linux Mint 22.3 Notebook | 192.168.178.71 |

## Stack

- **Home Assistant** `homeassistant/home-assistant:stable`
- **Mosquitto MQTT Broker** `eclipse-mosquitto:latest`
- **BL-Net Proxy** Python 3, läuft als systemd-Dienst auf Port 8765
- **Docker Compose** für einfaches Deployment

## Integrationen

| Integration | Beschreibung |
|---|---|
| [SMA Solar](https://www.home-assistant.io/integrations/sma/) | SMA Wechselrichter via Webconnect (SSL) |
| [hoymiles-wifi](https://github.com/suaveolent/ha-hoymiles-wifi) | Hoymiles DTU-Lite via lokale API (HACS) |
| [HACS](https://hacs.xyz/) | Home Assistant Community Store |
| BL-Net Proxy (`blnet-proxy/`) | Eigener HTTP-Proxy für BL-Net V2.19, liest UVR1611-Zustände aus |
| MQTT | Mosquitto Broker für zukünftige Erweiterungen |

## Berechnete Sensoren

| Sensor | Berechnung |
|---|---|
| `sensor.pv_gesamtleistung` | Hoymiles AC-Leistung + SMA PV-Leistung |
| `sensor.hausverbrauch` | PV Gesamt − Netzleistung (nur positive Werte) |
| `sensor.solar_ueberschuss` | Einspeisung ins Netz (positive Netzleistung) |
| `sensor.grundlast` | Netzbezug (negative Netzleistung, invertiert) |

Alle Werte in Watt, basierend auf `sensor.sn_XXXXXXXXXX_grid_power` des SMA Wechselrichters.

## Heizstab-Steuerung

Der Heizstab (Boiler) wird automatisch eingeschaltet wenn genug Solar-Überschuss vorhanden ist — statt ins Netz einzuspeisen wird die Energie thermisch gespeichert.

**Endlösung: Shelly Relais in der Zuleitung des Heizstabs**
- HA steuert `switch.shelly_heizstab` direkt per lokaler API
- BL-Net/Proxy nur noch für Monitoring (UVR1611 Ausgang 7 = Brenneranforderung Heizstab)

**Automations-Logik** (`config/automations.yaml`):
| Automation | Bedingung | Aktion |
|---|---|---|
| Heizstab EIN | Überschuss > 500 W für 5 Min, 07–19 Uhr, Automation aktiv | Shelly EIN |
| Heizstab AUS | Überschuss < 100 W für 2 Min | Shelly AUS |
| Heizstab Abend-AUS | Täglich 19:00 Uhr | Shelly AUS |

Die Automation lässt sich per `input_boolean.heizstab_automation_aktiv` im Dashboard deaktivieren.

## BL-Net Proxy

BL-Net V2.19 erlaubt nur **eine aktive Session gleichzeitig** und sperrt bei Missbrauch für 5–30 Minuten. Der Proxy löst das:

- Einmaliger Login beim Start, Session wird wiederverwendet
- Keepalive-Request alle 20 Sekunden verhindert Session-Timeout
- Mutex verhindert parallele HTTP-Anfragen ans BL-Net
- HA-eigene blnet-Integration ist deaktiviert (Konkurrenz würde Lockouts verursachen)

**Protokoll-Details BL-Net V2.19:**
- Login: `POST /main.html` mit `blu=1&blp=<passwort>&bll=Login` → `Set-Cookie: TAID`
- Funktioniert **nur** mit HTTP/1.1 Keep-Alive (`requests`-Library), nicht mit curl (HTTP/1.0)
- UVR1611 Digitale Ausgänge: `GET /d_ein.htm?blaE={1-16}&blaF=1` (blaF=1 = CAN-Knoten UVR1611)
- Parser sucht `aktueller Wert: AN` / `aktueller Wert: AUS` im Seitentext
- Ausgänge **AUS** setzen: `GET /d_aus.htm?blaE={nr}&blaS=0` — Remote **EIN** ist nicht möglich (Sicherheitsdesign)

**API** (Port 8765):
```
GET  /blnet              → JSON mit allen Schaltzuständen
GET  /blnet/raw?path=... → Diagnose: beliebige BL-Net Seite durchreichen
```

**Proxy starten:**
```bash
python3 -u blnet-proxy/blnet_proxy.py &
```

Beim Start wartet der Proxy 60 Sekunden damit eine eventuell noch aktive alte Session ablaufen kann.

## Dashboard

Solar-Dashboard mit zwei Views:

**Übersicht:**
- PV Gesamtleistung (Hoymiles + SMA kombiniert) als Live-Wert
- Aktuelle Leistung je Panel (Hoymiles Port 1–4) als Gauges
- Tages- und Gesamtertrag pro Panel
- SMA: PV-Leistung, Ertrag, Netzleistung, Status
- Wechselrichter-Details (Temperatur, Spannung, Frequenz)

**Energie & Heizstab:**
- Gauges: PV Gesamt / Hausverbrauch / Solar-Überschuss / Grundlast
- Detailliste aller Leistungswerte
- Heizstab-Steuerung: Automation-Toggle, Shelly-Schalter, BL-Net Monitoring

## Fernzugriff via Cloudflare Tunnel

Home Assistant ist von außen erreichbar über `https://ha.alab247.de` — ohne offene Ports im Router, gesichert durch Cloudflare Zero Trust Access.

### Architektur

```
Heimnetz  → http://192.168.178.71:8123   → kein Login (trusted_network)
Internet  → https://ha.alab247.de        → Cloudflare Access → CF Tunnel → HA
```

### Komponenten

| Komponente | Beschreibung |
|---|---|
| **cloudflared** | Systemdienst, baut ausgehenden Tunnel zu Cloudflare auf |
| **Cloudflare Access** | Zero Trust Schutz — nur autorisierte Nutzer dürfen durch |
| **Service Token** | Statischer Key für die HA Companion App (Custom Headers) |
| **E-Mail OTP** | Einmaliger Login im Browser, Session 1 Monat gültig |

### cloudflared installieren

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared
chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/cloudflared

cloudflared tunnel login
cloudflared tunnel create homeassist
cloudflared tunnel route dns homeassist ha.example.de
```

Config `/etc/cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL-ID>
credentials-file: /etc/cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: ha.example.de
    service: http://localhost:8123
  - service: http_status:404
```

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

### Home Assistant konfigurieren

In `config/configuration.yaml`:

```yaml
homeassistant:
  auth_providers:
    - type: trusted_networks
      trusted_networks:
        - 192.168.178.0/24
      allow_bypass_login: true
    - type: homeassistant

http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
    - ::1
```

### Cloudflare Access einrichten

1. **Zero Trust → Access → Applications → Add → Self-hosted**
   - Domain: `ha.example.de`
   - Session Duration: `1 month`

2. **Policies** (Reihenfolge beachten):

| Policy | Action | Rule |
|---|---|---|
| `Bypass Token` | Bypass | Service Token (für Companion App) |
| `Mein Zugang` | Allow | Emails → deine@email.de |
| `Block All` | Block | Everyone |

3. **Service Token** anlegen: Zero Trust → Access → Service Auth → Service Tokens → Create
   - Token-Werte sicher speichern (werden nur einmal angezeigt)
   - `CF-Access-Client-Id` und `CF-Access-Client-Secret` in der Companion App als Custom Headers eintragen

### HA Companion App (Android)

- External URL: `https://ha.example.de`
- Beim ersten Start: CF E-Mail OTP einmalig bestätigen → danach 1 Monat gültig

### Hinweise Sicherheit

- Cloudflared-Credentials liegen in `/etc/cloudflared/` — **nicht** ins Repository committen
- Service Token sicher aufbewahren (z.B. `~/.config/cf-access/`) — ebenfalls nicht committen
- Mosquitto ist ohne Auth konfiguriert — nur im lokalen Netz erreichbar, nicht über den Tunnel

## Installation

### Voraussetzungen

- Docker & Docker Compose
- Python 3 (für BL-Net Proxy)
- Linux (getestet auf Linux Mint 22.3)

### Setup

```bash
git clone https://github.com/Matze600/homeassist-solar.git
cd homeassist-solar
docker compose up -d
```

Home Assistant ist dann erreichbar unter `http://<IP>:8123`

### BL-Net Proxy starten

```bash
cd homeassist-solar
python3 -u blnet-proxy/blnet_proxy.py &
```

Für dauerhaften Betrieb als systemd-Service einrichten.

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
- **BL-Net V2.19** kann digitale Ausgänge remote nur auf HAND AUS setzen, nicht auf HAND EIN — deswegen der Shelly als eigentlicher Schalter.
- Mosquitto ist ohne Authentifizierung konfiguriert — nur für lokales Netzwerk geeignet.
- `config/secrets.yaml` und `config/.storage/` (außer Lovelace-Dashboards) sind in `.gitignore` ausgeschlossen.
