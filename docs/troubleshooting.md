---
tags:
  - docker
  - docker-compose
  - homeassistant
  - mqtt
  - paho
---
# Troubleshooting

## General

Things that need to work:

- Docker API access to list and inspect containers
- MQTT Publication of results
- Home Assistant discovering the Update entities on MQTT
- Home Assistant generating update notices in UI when there's a new version
- Command Topic message sent by Home Assistant when Update button clicked
- Docker Compose available from shell to make updates and restart
- Git command available in shell to check for local repo updates and pull

## Updates2MQTT Logs

If running under docker, and following the container naming guidance, then see the
logs using:

`docker logs updates2mqtt`

or change to the directory where the `docker-compose.yaml` is installed and do `docker compose logs`

### Changing Log Level

Update the `config.yaml` and change the log level to DEBUG, which will show much
more diagnostic information.

```yaml
log:
  level: DEBUG
```

When you have everything working, its best to change the log level back, so
your container isn't generating big logs.

### Going Inside Container

From the `docker-compose.yaml` directory, execute 

`docker compose exec -it updates2mqtt bash`

(if you have an old Docker install, you may need to use `docker-compose` instead of `docker compose`)

This will give you shell access inside the container, which is a good way of checking
for path issues, permissio issues etc. For example, if you have compose directories in the
`/containers` directory, you could `cd /containers` and validate that Updates2MQTT can see the
other compose directories, `ls` the contents, and run `docker compose` or `git` actions there.

## MQTT

If the host, port, user and password for MQTT are incorrect then usually this
will show in the logs, or use a MQTT client to verify that Updates2MQTT is
successfully posting to topics ( and that HomeAssistant itself is publishing
to the same broker OK).

Updates2MQTT uses the [Eclipse Paho Python Client](https://github.com/eclipse-paho/paho.mqtt.python) for all MQTT interaction, using v2 of the callback API, and supports the older
MQTT implementations as well as the newer v5 protocol. The [Issues](https://github.com/eclipse-paho/paho.mqtt.python/issues?q=is%3Aissue) list might give you some clues for your situation. 


### MQTT Clients

Use a desktop MQTT app - [MQTTX](https://mqttx.app) will let you subscribe to `#` and see everything on a broker, while [MQTT Explorer](https://mqtt-explorer.com) automatically shows a tree structure of topics, and can run either as a desktop app, or as [web app running on Docker](https://github.com/Smeagolworms4/MQTT-Explorer).

These tools will let you inspect messages, and also publish your own, so can create
your own update message and see if it gets picked up by the Home Assistant app.

Alternatively, use the debug option and logging of Mosquitto broker, or the built-in admin/debug UI of EMQX broker. Or the handy command line `mosquitto_sub` and `mosquitto_pub`, which are also used by the Updates2MQTT health check.

## Home Assistant

### Checklist 

(All of these can be checked and changed via the Home Assistant UI.)

- HA is configured with an MQTT integration
- MQTT broker host and port is the same on HA as Updates2MQTT
    - Updates2MQTT has been tested with Mosquitto and EMQX
- Automatic *Discovery* is on
- The discovery prefix matches Updates2MQTT ( they both default to `homeassistant`)

See the examples at [Home Assistant Configuration](home_assistant.md#configuration)

In addition to the base MQTT configuration, Updates2MQTT relies on [MQTT Discovery](https://www.home-assistant.io/integrations/update.mqtt/) and [MQTT Update](https://www.home-assistant.io/integrations/update.mqtt/) integrations. All of these have a single set of [MQTT Issues](https://github.com/home-assistant/core/issues?q=is%3Aissue+label%3A%22integration%3A+mqtt%22). 

When configured, each monitored container will have an `update` entity visible in the [Home Assistant Developer Tools](https://www.home-assistant.io/docs/tools/dev-tools/) and [Entities View](https://www.home-assistant.io/docs/configuration/entities_domains/).

#### Home Assistant Mosquitto HassOS App

If using the default *Mosquitto* broker, and *Customization* switched on, check the ACL
configuration has `readwrite` access give to the Updates2MQTT user for its topics. The [HomeAssistant add-in config](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md) puts this in the `/share/mosquitto` directory. 

Oddly, the Paho MQTT client used by Updates2MQTT is known to [report success even when broker rejects message because of ACL restrictions](https://github.com/eclipse-paho/paho.mqtt.python/issues/895).

#### Alternative MQTT Discovery

There's also an alternative to MQTT Discovery in HA, using plain yaml, the [MQTT Update Integration](https://www.home-assistant.io/integrations/update.mqtt/#configuration). The [BBQKees Boiler Gateway](https://bbqkees-electronics.nl/wiki/home-automations/home-assistant-configuration.html) has some detailed steps and examples for MQTT Discovery too.

#### No Update Button

If there's an update showing, but no *Update* button present, then there's a few reasons, which
can be checked directly from the config and log:

- Config has the `allow_pull`,`allow_restart` and `allow_build` all overridden to `False`
- A new version reference can't be found 
- The compose working directory can't be found
  - This is sourced from the `com.docker.compose.project.working_dir` label, which can be seen in `docker inspect`
  - This only stops restart, not pull, so if `allow_pull` is on, the Update button will still show
- The git repo path can't be found for a local build

The current state of this can be seen in MQTT, the config message will have two extra
values as below:

```yaml
  "command_topic": "updates2mqtt/dockernuc/docker",
  "payload_install": "docker|homarr|install"
```

#### Home Assistant Logs

Use the [System Log](https://www.home-assistant.io/integrations/system_log/) to check
for MQTT errors, or for positive confirmation that Update entities have been discovered. The
*raw* log will show more, and allow you to scroll back for hours.

The [Logger Integration](https://www.home-assistant.io/integrations/logger/#viewing-logs)
lets you tweak the levels of specific integrations. This is less useful for Updates2MQTT,
since all the work is happening outside of Home Assistant, however it can be useful
for general MQTT issues, and the examples in the Home Assistant documentation shows how
to tune the MQTT integration.

## Docker

More detailed information on the Docker API and compatibility with Docker engine versions can be found at Docker's own [Docker Engine API](https://docs.docker.com/reference/api/engine/) reference.

`updates2mqtt` is designed to run on the same host as the containers, so only needs local Docker daemon access. All it needs for that is the volume mapping as below:

```yaml title="Example Docker Compose Snippet"
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

Where `docker-compose` projects are being automatically updated and restarted, one problem can be that earlier versions used a `docker-compose` command and newer ones use `docker compose`. There is a `v1` and `v2` option in the [configuration](configuration.md) to support this, defaulting to `v2`.
  
If the `updates2mqtt` container is not running as root, then ensure that the user is a member of the local `docker` group. (If it is running as root, then consider moving
to a defined user, see [Running as Non-Root](configuration.md#running-as-non-root)).

### Docker Help

Best place to start is the `docker-py` [Issues](https://github.com/docker/docker-py/issues?q=is%3Aissue) on GitHub, since this is the primary component inside Updates2MQTT.

A simple way of testing if there's a `docker-py` issue is to load the client
directly from python. This example uses `uv` to avoid changing local Python
environment, use `pip` or other preferred tool to install if you want instead.

```yaml
uv run --with docker python3
>>> import docker
>>> docker.__version__
>>> client = docker.from_env()
>>> client.info()['Containers']
```

This should output the version of the `docker` package, and the total count of local containers if the connection is good. Updates2MQTT uses at least v7.1.0 of `docker` for Python API.