# Installation

## Install

Updates2MQTT prefers to be run inside a Docker container, though can run standalone, for example scripted via cron or systemd.

The only mandatory configuration is the MQTT broker host, user name and password, which can be set by environment variables, or the config file. The node name will be taken from the operating system if there's no config file. See [Configuration](configuration/index.md) for details.

To check that it's working, have a look at [Verifying it Works on Home Assistant](home_assistant.md#verifying-it-works).

### Docker

See `examples` directory for a working `docker-compose.yaml`.

If you want to update and restart containers, then the file system paths to the location of the directory where the docker compose file lives must be available in the Updates2MQTT container. 

```yaml title="docker compose snippet"
volumes:
      # Must have config directory mapped
      - ./conf:/app/conf
      # Must have the Docker daemon socket mapped
      - /var/run/docker.sock:/var/run/docker.sock
      # This list of paths is only needed when containers are to be updated
      # The paths here are completely dependent on where your docker-compose files live
      # and the internal/external paths must be exactly the same
      - /my/container/home:/my/container/home
      - /more/containers:/more/containers
```

The example `docker-compose.yaml` mounts `/my/container/home` for this purpose, so if your containers are in
`/my/container/home/app1`, `/my/container/home/app2` etc, then Updates2MQTT will be able to find them in
order to restart them. Map as many root paths as needed.

#### Ensuring Always Running

Use cron to make sure the container is always up, this example will run once an hour, adapt the schedule
and the location of `docker-compose.yaml` for your needs.

```bash
sudo crontab -e
```

```bash
0 * * * * /usr/bin/docker compose -f /containers/updates2mqtt/docker-compose.yaml up -d --no-recreate
```

### Without Docker

Updates2MQTT is published as a [PyPI package](https://pypi.org/project/updates2mqtt/) on every release,
so it can be used in any way you like - cron, systemd, your own Dockerfile, or whatever.

#### Run without installing using uv

```bash
uv run --with updates2mqtt updates2mqtt
```

#### Install and run with pip

```bash
pip install updates2mqtt
python3 -m updates2mqtt
```

