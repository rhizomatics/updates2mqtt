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


## Samenvatting

Laat Home Assistant u informeren over nieuwe updates voor Docker-images van uw containers.

![Voorbeeld Home Assistant updatepagina](../images/ha_update_detail.png "Home Assistant Updates")![Voorbeeld Home Assistant release-opmerkingen](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

Lees de release-opmerkingen en klik optioneel op *Bijwerken* om een Docker *pull* (of optioneel *build*) en *update* te starten.

![Voorbeeld Home Assistant updatevenster](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Beschrijving

Updates2MQTT controleert periodiek of er nieuwe versies van componenten beschikbaar zijn en publiceert nieuwe versie-informatie naar MQTT. HomeAssistant automatische detectie wordt ondersteund, zodat alle updates op dezelfde plek te zien zijn als Home Assistants eigen componenten en add-ins.

Momenteel worden alleen Docker-containers ondersteund, via een image registry controle (met v1 Docker API's of de OCI v2 API), of een git-repo als bron (zie [Lokale Builds](local_builds.md)), met specifieke verwerking voor Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay en LinuxServer Registry, met adaptief gedrag voor de meeste anderen. Het ontwerp is modulair, zodat andere updatebronnen kunnen worden toegevoegd, in ieder geval voor meldingen. De volgende geplande is **apt** voor op Debian gebaseerde systemen.

Componenten kunnen ook worden bijgewerkt, automatisch of getriggerd via MQTT, bijvoorbeeld door op de knop *Installeren* in het HomeAssistant-updatevenster te klikken. Pictogrammen en release-opmerkingen kunnen worden opgegeven voor een betere HA-ervaring. Zie [Home Assistant Integratie](home_assistant.md) voor details.

Lees de pagina's [Installatie](installation.md) en [Configuratie](configuration/index.md) om aan de slag te gaan.

Probeer dit voor een snelle proefrit:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

of zonder Docker, met [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

Het bevat ook een eenvoudig opdrachtregelprogramma dat de analyse uitvoert voor één actieve container, of manifests, JSON-blobs en taglijsten ophaalt uit externe registers (bekend werkend met GitHub, GitLab, Codeberg, Quay, LSCR en Microsoft MCR).

## Release Ondersteuning

Momenteel worden alleen Docker-containers ondersteund, hoewel andere gepland zijn, waarschijnlijk met prioriteit voor `apt`.

| Ecosysteem | Ondersteuning | Opmerkingen                                                                                                        |
|------------|---------------|--------------------------------------------------------------------------------------------------------------------|
| Docker     | Scan, Fetch   | Fetch is alleen ``docker pull``. Herstart-ondersteuning alleen voor ``docker-compose`` image-gebaseerde containers. |

## Heartbeat

Een heartbeat JSON-payload wordt optioneel periodiek gepubliceerd naar een configureerbaar MQTT-onderwerp, standaard `healthcheck/{node_name}/updates2mqtt`. Het bevat de huidige versie van Updates2MQTT, de knooppuntnaam, een tijdstempel en wat basisstatistieken.

## Gezondheidcontrole (Healthcheck)

Een `healthcheck.sh`-script is opgenomen in de Docker-image en kan worden gebruikt als Docker healthcheck als de containeromgevingsvariabelen `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` en `MQTT_PASS` zijn ingesteld. Het gebruikt het Linux-pakket `mosquitto-clients` dat de opdracht `mosquitto_sub` biedt om u te abonneren op onderwerpen.

!!! tip

    Controleer of de healthcheck werkt met `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (u kunt `| jq` weglaten als u jsonquery niet hebt geïnstalleerd, maar het is veel gemakkelijker te lezen mét)

Een andere aanpak is het gebruik van een herstarterservice direct in Docker Compose om een herstart te forceren, in dit geval eenmaal per dag:

```yaml title="Voorbeeld Compose Service"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Doelcontainers

Hoewel `updates2mqtt` alle containers die onder de Docker-daemon draaien zal ontdekken en bewaken, zijn er enkele opties om het gedrag voor die containers af te stemmen.

Dit gebeurt door omgevingsvariabelen of Docker-labels aan de containers toe te voegen, doorgaans in een `.env`-bestand of als `environment`-opties in `docker-compose.yaml`.

### Geautomatiseerde Updates

Als Docker-containers onmiddellijk moeten worden bijgewerkt zonder bevestiging of trigger, bijv. vanuit het HomeAssistant-updatevenster, stel dan de omgevingsvariabele `UPD2MQTT_UPDATE` in de doelcontainer in op `Auto` (standaard is `Passive`). Als u wilt bijwerken zonder publicatie naar MQTT en zichtbaarheid voor Home Assistant, gebruik dan `Silent`.

```yaml title="Voorbeeld Compose Fragment"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Geautomatiseerde updates kunnen ook gelden voor lokale builds, waarbij een `git_repo_path` is gedefinieerd - als er externe commits beschikbaar zijn om te pullen, worden `git pull`, `docker compose build` en `docker compose up` uitgevoerd.


## Gerelateerde Projecten

Andere nuttige apps voor zelfhosting met MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Systeemgezondheid en statistieken rapporteren via MQTT

Vind meer op [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Voor een krachtigere Docker-gerichte updatemanager, probeer [What's Up Docker](https://getwud.github.io/wud/)

## Ontwikkeling

Dit component maakt gebruik van verschillende open source-pakketten:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) Python SDK voor toegang tot Docker API's
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) MQTT-client
- [OmegaConf](https://omegaconf.readthedocs.io) voor configuratie en validatie
- [structlog](https://www.structlog.org/en/stable/) voor gestructureerde logging en [rich](https://rich.readthedocs.io/en/stable/) voor betere uitzonderingsrapportage
- [hishel](https://hishel.com/) voor het cachen van metadata
- [httpx](https://www.python-httpx.org) voor het ophalen van metadata
- De Astral [uv](https://docs.astral.sh/uv/) en [ruff](https://docs.astral.sh/ruff/) tools voor ontwikkeling en build
- [pytest](https://docs.pytest.org/en/stable/) en ondersteunende add-ins voor geautomatiseerd testen
- [usingversion](https://pypi.org/project/usingversion/) om huidige versie-informatie te loggen

## Rhizomatics Open Source voor Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Automatisch in- en uitschakelen van Home Assistant alarmbedieningspanelen met fysieke knoppen, aanwezigheid, kalenders, zon en meer
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - OpenTelemetry (OTLP) en Syslog-gebeurtenisopname voor Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Uniforme notificatie voor eenvoudige multi-channel messaging, inclusief krachtige integratie van deurbellen en beveiligingscamera's.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integratie met ANPR/ALPR kentekenplaatcamera's via bestandssysteem (NAS/FTP) naar MQTT met optionele beeldanalyse en UK DVLA-integratie.
