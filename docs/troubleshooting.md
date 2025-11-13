# Troubleshooting

## MQTT

Use a desktop MQTT app - [MQTTX](https://mqttx.app) will let you subscribe to `#` and see everything on a broker, and [MQTT Explorer](https://mqtt-explorer.com) automatically shows a tree structure of topics, and can run either as a desktop app, or as [web app running on Docker](https://github.com/Smeagolworms4/MQTT-Explorer). These will let you inspect messages, and also publish your own.

## Docker

More detailed information on the Docker API and compatibility with Docker engine versions can be found at Docker's own [Docker Engine API](https://docs.docker.com/reference/api/engine/) reference.

`updates2mqtt` is designed to run on the same host as the containers, so only needs local Docker daemon access. All it needs for that is the volume mapping as below:

```yaml title="Example Docker Compose Snippet"
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

Where `docker-compose` projects are being automatically updated and restarted, one problem can be that earlier versions used a `docker-compose` command and newer ones use `docker compose`. There is a `v1` and `v2` option in the [configuration](configuration.md) to support this, defaulting to `v2`.
  