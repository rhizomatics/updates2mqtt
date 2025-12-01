# Troubleshooting

## Log Level

Update the `config.yaml` and change the log level to DEBUG

```yaml
log:
  level: DEBUG
```

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

In addition to the base MQTT configuration, Updates2MQTT relies on [MQTT Discovery](https://www.home-assistant.io/integrations/update.mqtt/) and [MQTT Update](https://www.home-assistant.io/integrations/update.mqtt/) integrations. All of these have a single set of [MQTT Issues](https://github.com/home-assistant/core/issues?q=is%3Aissue+label%3A%22integration%3A+mqtt%22). When configured, each monitored container will have an `update` entity visible in the [Home Assistant Developer Tools](https://www.home-assistant.io/docs/tools/dev-tools/).

#### Home Assistant Mosquitto HassOS App

If using the default *Mosquitto* broker, and *Customization* switched on, check the ACL
configuration has `readwrite` access give to the Updates2MQTT user for its topics. The [HomeAssistant add-in config](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md) puts this in the `/share/mosquitto` directory. 

Oddly, the Paho MQTT client used by Updates2MQTT is known to [report success even when broker rejects message because of ACL restrictions](https://github.com/eclipse-paho/paho.mqtt.python/issues/895).

#### Alternative MQTT Discovery

There's also an alternative to MQTT Discovery in HA, using plain yaml, the [MQTT Update Integration](https://www.home-assistant.io/integrations/update.mqtt/#configuration). The [BBQKees Boiler Gateway](https://bbqkees-electronics.nl/wiki/home-automations/home-assistant-configuration.html) has some detailed steps and examples for MQTT Discovery too.

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