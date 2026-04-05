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


## Résumé

Laissez Home Assistant vous informer des nouvelles mises à jour des images Docker pour vos conteneurs.

![Exemple de page de mise à jour Home Assistant](../images/ha_update_detail.png "Home Assistant Updates")![Exemple de notes de version Home Assistant](../images/ha_release_notes.png "Home Assistant Release Notes"){width=300}

Lisez les notes de version et cliquez éventuellement sur *Mettre à jour* pour déclencher un *pull* Docker (ou optionnellement un *build*) et une *mise à jour*.

![Exemple de dialogue de mise à jour Home Assistant](../images/ha_update_dialog.png "Home Assistant Updates"){width=480}


## Description

Updates2MQTT vérifie périodiquement la disponibilité de nouvelles versions des composants et publie les informations de nouvelles versions sur MQTT. La découverte automatique de HomeAssistant est prise en charge, de sorte que toutes les mises à jour peuvent être vues au même endroit que les propres composants et add-ins de Home Assistant.

Seuls les conteneurs Docker sont actuellement pris en charge, soit via une vérification du registre d'images (en utilisant les API Docker v1 ou l'API OCI v2), soit un dépôt git pour la source (voir [Compilations Locales](local_builds.md)), avec une gestion spécifique pour Docker, Github Container Registry, Gitlab, Codeberg, Microsoft Container Registry, Quay et LinuxServer Registry, avec un comportement adaptatif pour la plupart des autres. La conception est modulaire, de sorte que d'autres sources de mise à jour peuvent être ajoutées, au moins pour les notifications. La prochaine prévue est **apt** pour les systèmes basés sur Debian.

Les composants peuvent également être mis à jour, soit automatiquement soit déclenchés via MQTT, par exemple en cliquant sur le bouton *Installer* dans le dialogue de mise à jour de HomeAssistant. Des icônes et des notes de version peuvent être spécifiées pour une meilleure expérience HA. Voir [Intégration Home Assistant](home_assistant.md) pour plus de détails.

Pour commencer, lisez les pages [Installation](installation.md) et [Configuration](configuration/index.md).

Pour un essai rapide, essayez ceci :

```bash
docker run -v /var/run/docker.sock:/var/run/docker.sock -e MQTT_USER=user1 -e MQTT_PASS=user1 -e MQTT_HOST=192.168.1.5 ghcr.io/rhizomatics/updates2mqtt:latest
```

ou sans Docker, en utilisant [uv](https://docs.astral.sh/uv/)

```bash
export MQTT_HOST=192.168.1.1;export MQTT_USER=user1;export MQTT_PASS=user1;uv run --with updates2mqtt python -m updates2mqtt
```

Il est également livré avec un outil en ligne de commande basique qui effectuera l'analyse pour un seul conteneur en cours d'exécution, ou récupérera des manifestes, des blobs JSON et des listes de tags depuis des registres distants (fonctionnement vérifié avec GitHub, GitLab, Codeberg, Quay, LSCR et Microsoft MCR).

## Support des Versions

Seuls les conteneurs Docker sont pris en charge pour l'instant, bien que d'autres soient prévus, probablement avec une priorité pour `apt`.

| Écosystème | Support       | Commentaires                                                                                                           |
|------------|---------------|------------------------------------------------------------------------------------------------------------------------|
| Docker     | Scan, Fetch   | Fetch est uniquement ``docker pull``. Support de redémarrage uniquement pour les conteneurs basés sur image ``docker-compose``. |

## Battement de Cœur (Heartbeat)

Un payload JSON de battement de cœur est optionnellement publié périodiquement sur un topic MQTT configurable, par défaut `healthcheck/{node_name}/updates2mqtt`. Il contient la version actuelle d'Updates2MQTT, le nom du nœud, un horodatage et quelques statistiques de base.

## Vérification de Santé (Healthcheck)

Un script `healthcheck.sh` est inclus dans l'image Docker et peut être utilisé comme healthcheck Docker si les variables d'environnement du conteneur `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` et `MQTT_PASS` sont définies. Il utilise le paquet Linux `mosquitto-clients` qui fournit la commande `mosquitto_sub` pour s'abonner aux topics.

!!! tip

    Vérifiez que le healthcheck fonctionne en utilisant `docker inspect --format "{{json .State.Health }}" updates2mqtt | jq` (vous pouvez omettre `| jq` si vous n'avez pas jsonquery installé, mais c'est beaucoup plus facile à lire avec)

Une autre approche consiste à utiliser un service de redémarrage directement dans Docker Compose pour forcer un redémarrage, dans ce cas une fois par jour :

```yaml title="Exemple de Service Compose"
restarter:
    image: docker:cli
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart updates2mqtt; done"]
    restart: unless-stopped
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

## Conteneurs Cibles

Bien que `updates2mqtt` découvre et surveille tous les conteneurs s'exécutant sous le daemon Docker, il existe des options pour ajuster son fonctionnement sur ces conteneurs.

Cela se fait en ajoutant des variables d'environnement ou des labels Docker aux conteneurs, typiquement dans un fichier `.env` ou en tant qu'options `environment` dans `docker-compose.yaml`.

### Mises à Jour Automatiques

Si les conteneurs Docker doivent être immédiatement mis à jour, sans confirmation ni déclencheur, par exemple depuis le dialogue de mise à jour de HomeAssistant, définissez la variable d'environnement `UPD2MQTT_UPDATE` dans le conteneur cible sur `Auto` (la valeur par défaut est `Passive`). Si vous souhaitez une mise à jour sans publication sur MQTT et sans visibilité pour Home Assistant, utilisez `Silent`.

```yaml title="Extrait Compose Exemple"
restarter:
    image: docker:cli
    command: ["/bin/sh", "-c", "while true; do sleep 86400; docker restart mailserver; done"]
    environment:
      - UPD2MQTT_UPDATE=AUTO
```

Les mises à jour automatiques peuvent également s'appliquer aux compilations locales, où un `git_repo_path` a été défini - si des commits distants sont disponibles à récupérer, alors `git pull`, `docker compose build` et `docker compose up` seront exécutés.


## Projets Connexes

D'autres applications utiles pour l'auto-hébergement avec l'aide de MQTT :

- [psmqtt](https://github.com/eschava/psmqtt) - Rapporter l'état de santé et les métriques du système via MQTT

Trouvez-en plus sur [awesome-mqtt](https://github.com/rhizomatics/awesome-mqtt)

Pour un gestionnaire de mises à jour plus puissant axé sur Docker, essayez [What's Up Docker](https://getwud.github.io/wud/)

## Développement

Ce composant repose sur plusieurs packages open source :

- [docker-py](https://docker-py.readthedocs.io/en/stable/) SDK Python pour l'accès aux APIs Docker
- [Eclipse Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) client MQTT
- [OmegaConf](https://omegaconf.readthedocs.io) pour la configuration et la validation
- [structlog](https://www.structlog.org/en/stable/) pour la journalisation structurée et [rich](https://rich.readthedocs.io/en/stable/) pour un meilleur rapport d'exceptions
- [hishel](https://hishel.com/) pour la mise en cache des métadonnées
- [httpx](https://www.python-httpx.org) pour récupérer les métadonnées
- Les outils Astral [uv](https://docs.astral.sh/uv/) et [ruff](https://docs.astral.sh/ruff/) pour le développement et la compilation
- [pytest](https://docs.pytest.org/en/stable/) et les add-ins de support pour les tests automatisés
- [usingversion](https://pypi.org/project/usingversion/) pour journaliser les informations de version actuelle

## Rhizomatics Open Source pour Home Assistant

### HACS
- [AutoArm](https://autoarm.rhizomatics.org.uk) - Armer et désarmer automatiquement les panneaux de contrôle d'alarme Home Assistant en utilisant des boutons physiques, la présence, les calendriers, le soleil et plus encore
- [Remote Logger](https://remote-logger.rhizomatics.org.uk) - Capture d'événements OpenTelemetry (OTLP) et Syslog pour Home Assistant
- [Supernotify](https://supernotify.rhizomatics.org.uk) - Notification unifiée pour une messagerie multi-canal facile, incluant une intégration puissante de sonnettes et de caméras de sécurité.


### Python / Docker

- [Anpr2MQTT](https://anpr2mqtt.rhizomatics.org.uk) - Intégration avec les caméras ANPR/ALPR de plaques d'immatriculation via le système de fichiers (NAS/FTP) vers MQTT avec analyse d'images optionnelle et intégration DVLA britannique.
