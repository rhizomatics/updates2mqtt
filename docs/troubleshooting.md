# Troubleshooting

## Log Level

Update the `config.yaml` and change the log level to DEBUG

```yaml
log:
  level: DEBUG
```


## MQTT

Use a desktop MQTT app - [MQTTX](https://mqttx.app) will let you subscribe to `#` and see everything on a broker, while [MQTT Explorer](https://mqtt-explorer.com) automatically shows a tree structure of topics, and can run either as a desktop app, or as [web app running on Docker](https://github.com/Smeagolworms4/MQTT-Explorer).

These tools will let you inspect messages, and also publish your own, so can create
your own update message and see if it gets picked up by the Home Assistant app.

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