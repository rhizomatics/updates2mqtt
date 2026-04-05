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


## Riepilogo

Lascia che Home Assistant ti informi dei nuovi aggiornamenti alle immagini Docker per i tuoi container.

![Esempio di pagina di aggiornamento Home Assistant](../images/ha_update_detail.png "Home Assistant Updates")![Esempio di note di rilascio Home Assistant](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

Leggi le note di rilascio e, facoltativamente, fai clic su *Aggiorna* per avviare un Docker *pull* (o facoltativamente *build*) e un *aggiornamento*.

![Esempio di dialogo di aggiornamento Home Assistant](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Descrizione

Updates2MQTT verifica periodicamente la disponibilità di nuove versioni dei componenti e pubblica le informazioni sulle nuove versioni tramite MQTT. Il rilevamento automatico di HomeAssistant è supportato, in modo che tutti gli aggiornamenti possano essere visualizzati nello stesso posto dei componenti e dei componenti aggiuntivi di Home Assistant.

Attualmente sono supportati solo i container Docker, tramite una verifica del registro delle immagini (usando le API Docker v1 o l'API OCI v2) o un repository git per il sorgente (vedi [Build Locali](local_builds.md)), con gestione specifica per Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay e LinuxServer Registry, con comportamento adattivo per la maggior parte degli altri. Il design è modulare, quindi è possibile aggiungere altre sorgenti di aggiornamento, almeno per le notifiche. La prossima prevista è **apt** per i sistemi basati su Debian.

I componenti possono anche essere aggiornati, automaticamente o attivati tramite MQTT, ad esempio premendo il pulsante *Installa* nel dialogo di aggiornamento di HomeAssistant. Icone e note di rilascio possono essere specificate per una migliore esperienza HA. Consulta [Integrazione con Home Assistant](home_assistant.md) per i dettagli.

Per iniziare, leggi le pagine [Installazione](installation.md) e [Configurazione](configuration/index.md).

Per una prova rapida, esegui:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

o senza Docker, usando [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

Include anche uno strumento base da riga di comando che eseguirà l'analisi per un singolo container in esecuzione, o recupererà manifest, blob JSON e liste di tag da registri remoti (verificato funzionante con GitHub, GitLab, Codeberg, Quay, LSCR e Microsoft MCR).

## Supporto alle Versioni

Attualmente sono supportati solo i container Docker, anche se altri sono pianificati, probabilmente con priorità per `apt`.

| Ecosistema | Supporto      | Note                                                                                                               |
|------------|---------------|--------------------------------------------------------------------------------------------------------------------|
| Docker     | Scan, Fetch   | Fetch è solo ``docker pull``. Supporto al riavvio solo per container basati su immagine ``docker-compose``.       |

## Heartbeat

Un payload JSON di heartbeat viene facoltativamente pubblicato periodicamente su un topic MQTT configurabile, con valore predefinito `healthcheck/{node_name}/updates2mqtt`. Contiene la versione corrente di Updates2MQTT, il nome del nodo, un timestamp e alcune statistiche di base.

## Healthcheck

Nell'immagine Docker è incluso uno script `healthcheck.sh`, utilizzabile come healthcheck Docker se le variabili d'ambiente del container `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` e `MQTT_PASS` sono impostate. Usa il pacchetto Linux `mosquitto-clients` che fornisce il comando `mosquitto_sub` per iscriversi ai topic.

!!! tip

    Verifica che l'healthcheck funzioni usando `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (puoi omettere `| jq` se non hai jsonquery installato, ma è molto più facile da leggere con esso)

Un altro approccio è utilizzare un servizio di riavvio direttamente in Docker Compose per forzare un riavvio, in questo caso una volta al giorno:

```yaml title="Esempio di Servizio Compose"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Container Target

Mentre `updates2mqtt` scoprirà e monitorerà tutti i container in esecuzione sotto il daemon Docker, esistono alcune opzioni per ottimizzarne il funzionamento su quei container.

Ciò avviene aggiungendo variabili d'ambiente o label Docker ai container, tipicamente all'interno di un file `.env`, o come opzioni `environment` all'interno di `docker-compose.yaml`.

### Aggiornamenti Automatici

Se i container Docker devono essere aggiornati immediatamente, senza alcuna conferma o attivatore, ad esempio dal dialogo di aggiornamento di HomeAssistant, imposta la variabile d'ambiente `UPD2MQTT_UPDATE` nel container di destinazione su `Auto` (il valore predefinito è `Passive`). Se vuoi che si aggiorni senza pubblicare su MQTT ed essere visibile a Home Assistant, usa `Silent`.

```yaml title="Esempio di Frammento Compose"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Gli aggiornamenti automatici possono applicarsi anche alle build locali, dove è stato definito un `git_repo_path` - se sono disponibili commit remoti da scaricare, verranno eseguiti `git pull`, `docker compose build` e `docker compose up`.


## Progetti Correlati

Altre app utili per il self-hosting con l'aiuto di MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Segnala salute del sistema e metriche tramite MQTT

Trova altri su [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Per un gestore di aggiornamenti più potente incentrato su Docker, prova [What's Up Docker](https://getwud.github.io/wud/)

## Sviluppo

Questo componente si basa su diversi pacchetti open source:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK Python per l'accesso alle API Docker
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) client MQTT
- [OmegaConf](https://omegaconf.readthedocs.io) per configurazione e validazione
- [structlog](https://www.structlog.org/en/stable/) per la registrazione strutturata e [rich](https://rich.readthedocs.io/en/stable/) per una migliore segnalazione delle eccezioni
- [hishel](https://hishel.com/) per la memorizzazione nella cache dei metadati
- [httpx](https://www.python-httpx.org) per il recupero dei metadati
- Gli strumenti Astral [uv](https://docs.astral.sh/uv/) e [ruff](https://docs.astral.sh/ruff/) per lo sviluppo e la compilazione
- [pytest](https://docs.pytest.org/en/stable/) e add-in di supporto per i test automatizzati
- [usingversion](https://pypi.org/project/usingversion/) per registrare le informazioni sulla versione corrente

## Rhizomatics Open Source per Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Inserimento e disinserimento automatico dei pannelli di controllo allarme di Home Assistant utilizzando pulsanti fisici, presenza, calendari, sole e altro ancora
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Acquisizione di eventi OpenTelemetry (OTLP) e Syslog per Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Notifica unificata per una messaggistica multicanale semplice, con potente integrazione di campanelli e telecamere di sicurezza.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integrazione con telecamere ANPR/ALPR per targhe tramite file system (NAS/FTP) a MQTT con analisi delle immagini opzionale e integrazione DVLA del Regno Unito.
