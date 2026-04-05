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


## Resumen

Permite que Home Assistant te notifique sobre nuevas actualizaciones de imágenes Docker para tus contenedores.

![Ejemplo de página de actualización de Home Assistant](../images/ha_update_detail.png "Home Assistant Updates")![Ejemplo de notas de versión de Home Assistant](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

Lee las notas de la versión y, opcionalmente, haz clic en *Actualizar* para activar un *pull* de Docker (o, opcionalmente, un *build*) y una *actualización*.

![Ejemplo de diálogo de actualización de Home Assistant](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Descripción

Updates2MQTT verifica periódicamente si hay nuevas versiones de los componentes disponibles y publica la información de nuevas versiones en MQTT. Se admite el descubrimiento automático de HomeAssistant, de modo que todas las actualizaciones se pueden ver en el mismo lugar que los propios componentes y complementos de Home Assistant.

Actualmente solo se admiten contenedores Docker, ya sea mediante una verificación de registro de imágenes (usando las API de Docker v1 o la API OCI v2), o un repositorio git para el código fuente (consulta [Compilaciones Locales](local_builds.md)), con manejo específico para Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay y LinuxServer Registry, con comportamiento adaptativo para la mayoría de los demás. El diseño es modular, por lo que se pueden agregar otras fuentes de actualización, al menos para notificaciones. La siguiente prevista es **apt** para sistemas basados en Debian.

Los componentes también pueden actualizarse, ya sea automáticamente o activados a través de MQTT, por ejemplo, haciendo clic en el botón *Instalar* en el diálogo de actualización de HomeAssistant. Se pueden especificar iconos y notas de versión para una mejor experiencia en HA. Consulta [Integración con Home Assistant](home_assistant.md) para más detalles.

Para comenzar, lee las páginas de [Instalación](installation.md) y [Configuración](configuration/index.md).

Para una prueba rápida, intenta esto:

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

o sin Docker, usando [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

También incluye una herramienta básica de línea de comandos que realizará el análisis para un único contenedor en ejecución, o recuperará manifiestos, blobs JSON y listas de etiquetas desde registros remotos (comprobado que funciona con GitHub, GitLab, Codeberg, Quay, LSCR y Microsoft MCR).

## Soporte de Versiones

Actualmente solo se admiten contenedores Docker, aunque se planean otros, probablemente con prioridad para `apt`.

| Ecosistema | Soporte       | Comentarios                                                                                                        |
|------------|---------------|--------------------------------------------------------------------------------------------------------------------|
| Docker     | Scan, Fetch   | Fetch es solo ``docker pull``. Soporte de reinicio solo para contenedores basados en imagen de ``docker-compose``. |

## Latido (Heartbeat)

Un payload JSON de latido se publica opcionalmente de forma periódica en un topic MQTT configurable, cuyo valor predeterminado es `healthcheck/{node_name}/updates2mqtt`. Contiene la versión actual de Updates2MQTT, el nombre del nodo, una marca de tiempo y algunas estadísticas básicas.

## Verificación de Salud (Healthcheck)

Se incluye un script `healthcheck.sh` en la imagen Docker y puede usarse como healthcheck de Docker si las variables de entorno del contenedor `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` y `MQTT_PASS` están configuradas. Usa el paquete Linux `mosquitto-clients`, que proporciona el comando `mosquitto_sub` para suscribirse a topics.

!!! tip

    Verifica que el healthcheck funciona usando `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (puedes omitir `| jq` si no tienes jsonquery instalado, pero es mucho más fácil de leer con él)

Otro enfoque es usar un servicio de reinicio directamente en Docker Compose para forzar un reinicio, en este caso una vez al día:

```yaml title="Ejemplo de Servicio Compose"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Contenedores Objetivo

Mientras que `updates2mqtt` descubrirá y monitorizará todos los contenedores que se ejecutan bajo el daemon de Docker, hay algunas opciones para ajustar su funcionamiento en esos contenedores.

Esto se hace agregando variables de entorno o etiquetas Docker a los contenedores, típicamente dentro de un archivo `.env`, o como opciones de `environment` dentro de `docker-compose.yaml`.

### Actualizaciones Automáticas

Si los contenedores Docker deben actualizarse inmediatamente, sin ninguna confirmación o activador, por ejemplo desde el diálogo de actualización de HomeAssistant, establece la variable de entorno `UPD2MQTT_UPDATE` en el contenedor objetivo en `Auto` (el valor predeterminado es `Passive`). Si deseas que se actualice sin publicar en MQTT y sin ser visible para Home Assistant, usa `Silent`.

```yaml title="Fragmento de Ejemplo Compose"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Las actualizaciones automáticas también pueden aplicarse a compilaciones locales, donde se ha definido un `git_repo_path` - si hay commits remotos disponibles para obtener, se ejecutarán `git pull`, `docker compose build` y `docker compose up`.


## Proyectos Relacionados

Otras aplicaciones útiles para self-hosting con la ayuda de MQTT:

- [psmqtt](https://github.com/eschava/psmqtt) - Reportar salud del sistema y métricas a través de MQTT

Encuentra más en [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Para un gestor de actualizaciones más potente centrado en Docker, prueba [What's Up Docker](https://getwud.github.io/wud/)

## Desarrollo

Este componente se basa en varios paquetes de código abierto:

- [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK de Python para acceso a las APIs de Docker
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) cliente MQTT
- [OmegaConf](https://omegaconf.readthedocs.io) para configuración y validación
- [structlog](https://www.structlog.org/en/stable/) para registro estructurado y [rich](https://rich.readthedocs.io/en/stable/) para mejor reporte de excepciones
- [hishel](https://hishel.com/) para caché de metadatos
- [httpx](https://www.python-httpx.org) para recuperar metadatos
- Las herramientas de Astral [uv](https://docs.astral.sh/uv/) y [ruff](https://docs.astral.sh/ruff/) para desarrollo y compilación
- [pytest](https://docs.pytest.org/en/stable/) y complementos de soporte para pruebas automatizadas
- [usingversion](https://pypi.org/project/usingversion/) para registrar información de la versión actual

## Rhizomatics Open Source para Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Armar y desarmar automáticamente paneles de control de alarma de Home Assistant usando botones físicos, presencia, calendarios, sol y más
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Captura de eventos OpenTelemetry (OTLP) y Syslog para Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Notificación unificada para mensajería multicanal fácil, incluida una poderosa integración de timbres y cámaras de seguridad.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Integración con cámaras ANPR/ALPR de matrículas a través del sistema de archivos (NAS/FTP) a MQTT con análisis de imágenes opcional e integración con la DVLA del Reino Unido.
