![updates2mqtt](../images/updates2mqtt-dark-256x256.png){ align=left }

# updates2mqtt

[![Rhizomatics Open Source](https://img.shields.io/badge/rhizomatics%20open%20source-lightseagreen)](https://github.com/rhizomatics)

[![PyPI - Version](https://img.shields.io/pypi/v/updates2mqtt)](https://pypi.org/project/updates2mqtt/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/rhizomatics/updates2mqtt)
[![Coverage](https://raw.githubusercontent.com/rhizomatics/updates2mqtt/refs/heads/badges/badges/coverage.svg)](https://updates2mqtt.rhizomatics.org.uk/developer/coverage/)
![Tests](https://raw.githubusercontent.com/rhizomatics/updates2mqtt/refs/heads/badges/badges/tests.svg)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/rhizomatics/updates2mqtt/main.svg)](https://results.pre-commit.ci/latest/github/rhizomatics/updates2mqtt/main)
[![Publish Python 🐍 distribution 📦 to PyPI and TestPyPI](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/pypi-publish.yml)
[![Github Deploy](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml/badge.svg?branch=main)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/python-package.yml)
[![CodeQL](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/github-code-scanning/codeql)
[![Dependabot Updates](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates/badge.svg)](https://github.com/rhizomatics/updates2mqtt/actions/workflows/dependabot/dependabot-updates)


<br/>
<br/>


## Zusammenfassung

Lassen Sie Home Assistant Sie über neue Updates zu Docker-Images für Ihre Container informieren.

![Beispiel Home Assistant Update-Seite](../images/ha_update_detail.png "Home Assistant Updates")![Beispiel Home Assistant Versionshinweise](../images/ha_release_notes.png "Home Assistant Versionshinweise"){width=300}

Lesen Sie die Versionshinweise und klicken Sie optional auf *Aktualisieren*, um einen Docker *pull* (oder optional *build*) und eine *Aktualisierung* auszulösen.

![Beispiel Home Assistant Aktualisierungsdialog](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Beschreibung

Updates2MQTT prüft regelmäßig auf neue Versionen verfügbarer Komponenten und veröffentlicht neue Versionsinformationen über MQTT. Die automatische HomeAssistant-Erkennung wird unterstützt, sodass alle Updates an derselben Stelle wie Home Assistants eigene Komponenten und Add-ins angezeigt werden können.

Derzeit werden nur Docker-Container unterstützt, entweder über eine Image-Registry-Prüfung (unter Verwendung von v1 Docker-APIs oder der OCI v2 API) oder einem Git-Repository als Quelle (siehe [Lokale Builds](local_builds.md)), mit spezifischer Unterstützung für Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay und LinuxServer Registry, mit adaptivem Verhalten für die meisten anderen. Das Design ist modular, sodass weitere Update-Quellen hinzugefügt werden können, zumindest für Benachrichtigungen. Als nächstes ist **apt** für Debian-basierte Systeme geplant.

Komponenten können auch aktualisiert werden, entweder automatisch oder ausgelöst über MQTT, zum Beispiel durch Klicken auf die Schaltfläche *Installieren* im HomeAssistant-Aktualisierungsdialog. Icons und Versionshinweise können für ein besseres HA-Erlebnis angegeben werden. Weitere Details unter [Home Assistant Integration](home_assistant.md).

Lesen Sie zum Einstieg die Seiten [Installation](installation.md) und [Konfiguration](configuration/index.md).

Für einen schnellen Einstieg versuchen Sie Folgendes:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

oder ohne Docker mit [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

Es enthält auch ein einfaches Befehlszeilentool, das die Analyse für einen einzelnen laufenden Container durchführt oder Manifeste, JSON-Blobs und Tag-Listen aus Remote-Registries abruft (funktioniert nachweislich mit GitHub, GitLab, Codeberg, Quay, LSCR und Microsoft MCR).

## Release-Unterstützung

Derzeit werden nur Docker-Container unterstützt, andere sind geplant, wahrscheinlich mit Priorität für `apt`.

| Ökosystem | Unterstützung | Anmerkungen                                                                                                     |
|-----------|---------------|-----------------------------------------------------------------------------------------------------------------|
| Docker    | Scan, Fetch   | Fetch ist nur ``docker pull``. Neustart-Unterstützung nur für ``docker-compose`` image-basierte Container.     |

## Heartbeat

Ein Heartbeat-JSON-Payload wird optional regelmäßig an ein konfigurierbares MQTT-Topic veröffentlicht, standardmäßig `healthcheck/{node_name}/updates2mqtt`. Es enthält die aktuelle Version von Updates2MQTT, den Node-Namen, einen Zeitstempel und einige grundlegende Statistiken.

## Gesundheitsprüfung

Ein `healthcheck.sh`-Skript ist im Docker-Image enthalten und kann als Docker-Healthcheck verwendet werden, wenn die Container-Umgebungsvariablen `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` und `MQTT_PASS` gesetzt sind. Es verwendet das Linux-Paket `mosquitto-clients`, das den Befehl `mosquitto_sub` zum Abonnieren von Topics bereitstellt.

!!! tip

    Überprüfen Sie, ob der Healthcheck funktioniert, mit `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (Sie können `| jq` weglassen, wenn Sie jsonquery nicht installiert haben, aber es ist viel leichter zu lesen)

Ein weiterer Ansatz ist die Verwendung eines Restarter-Dienstes direkt in Docker Compose, um einen Neustart zu erzwingen, in diesem Fall einmal täglich:

```yaml title="Beispiel Compose-Dienst"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Ziel-Container

Während `updates2mqtt` alle unter dem Docker-Daemon laufenden Container erkennt und überwacht, gibt es einige Optionen, um das Verhalten für diese Container anzupassen.

Dies geschieht durch Hinzufügen von Umgebungsvariablen oder Docker-Labels zu den Containern, typischerweise in einer `.env`-Datei oder als `environment`-Optionen in `docker-compose.yaml`.

### Automatische Updates

Wenn Docker-Container sofort aktualisiert werden sollen, ohne Bestätigung oder Auslöser, z.B. aus dem HomeAssistant-Aktualisierungsdialog, dann setzen Sie die Umgebungsvariable `UPD2MQTT_UPDATE` im Ziel-Container auf `Auto` (Standard ist `Passive`). Wenn Sie ohne MQTT-Veröffentlichung und ohne Sichtbarkeit für Home Assistant aktualisieren möchten, verwenden Sie `Silent`.

```yaml title="Beispiel Compose-Ausschnitt"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Automatische Updates können auch für lokale Builds gelten, bei denen ein `git_repo_path` definiert wurde – wenn remote Commits zum Abrufen verfügbar sind, werden `git pull`, `docker compose build` und `docker compose up` ausgeführt.


## Verwandte Projekte

Weitere nützliche Apps für Self-Hosting mit MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Systemeigenschaften und Metriken über MQTT melden

Mehr unter [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Für einen leistungsstärkeren Docker-fokussierten Update-Manager probieren Sie [What's Up Docker](https://getwud.github.io/wud/)

## Entwicklung

Diese Komponente basiert auf mehreren Open-Source-Paketen:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) Python SDK für den Zugriff auf Docker-APIs
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) MQTT-Client
- [OmegaConf](https://omegaconf.readthedocs.io) für Konfiguration und Validierung
- [structlog](https://www.structlog.org/en/stable/) für strukturiertes Logging und [rich](https://rich.readthedocs.io/en/stable/) für bessere Ausnahmeberichte
- [hishel](https://hishel.com/) zum Cachen von Metadaten
- [httpx](https://www.python-httpx.org) zum Abrufen von Metadaten
- Die Astral-Tools [uv](https://docs.astral.sh/uv/) und [ruff](https://docs.astral.sh/ruff/) für Entwicklung und Build
- [pytest](https://docs.pytest.org/en/stable/) und unterstützende Add-ins für automatisierte Tests
- [usingversion](https://pypi.org/project/usingversion/) zur Protokollierung aktueller Versionsinformationen

## Rhizomatics Open Source für Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Automatisches Scharf- und Unscharfschalten von Home Assistant Alarmzentralen mit physischen Tasten, Anwesenheit, Kalendern, Sonne und mehr
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - OpenTelemetry (OTLP) und Syslog-Ereigniserfassung für Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Einheitliche Benachrichtigung für einfaches Multi-Kanal-Messaging, einschließlich leistungsstarker Türklingel- und Sicherheitskamera-Integration.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integration mit ANPR/ALPR-Kennzeichenkameras über Dateisystem (NAS/FTP) zu MQTT mit optionaler Bildanalyse und UK-DVLA-Integration.
