# Installation

## Install

Updates2MQTT prefers to be run inside a Docker container, though can run standalone, for example scripted via cron or systemd.

The only mandatory configuration is the MQTT broker host, user name and password, which can be set by environment variables, or the config file. The node name will be taken from the operating system if there’s no config file. See [Configuration](https://updates2mqtt.rhizomatics.org.uk/configuration/index.md) for details.

To check that it’s working, have a look at [Verifying it Works on Home Assistant](https://updates2mqtt.rhizomatics.org.uk/home_assistant/#verifying-it-works).

### Docker

See `examples` directory for a working `docker-compose.yaml`.

If you want to update and restart containers, then the file system paths to the location of the directory where the docker compose file lives must be available in the Updates2MQTT container.

docker compose snippet

```yaml
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

The example `docker-compose.yaml` mounts `/my/container/home` for this purpose, so if your containers are in `/my/container/home/app1`, `/my/container/home/app2` etc, then Updates2MQTT will be able to find them in order to restart them. Map as many root paths as needed.

#### Parallel Updates

Several updates can run at once, for example when *Update All* is used in Home Assistant. Up to `max_concurrent_updates` (default 3) run in parallel, set in the `docker` section of the config file or with the `U2M_MAX_CONCURRENT_UPDATES` env var. Further updates show as in progress while they wait for a free slot. Restarts and builds for containers in the same compose project, or Portainer stack, are run one at a time.

#### Updating Updates2MQTT Itself

When Updates2MQTT updates its own container, it waits for any other updates in progress to finish, and ignores new update requests meanwhile. It then starts a short-lived helper container, from its own image and with the same volumes, to run `docker compose up`, so that the recreation isn’t cut short when the old container is stopped. The helper is named after the Updates2MQTT container, with a `_self_update_` suffix, and is removed by the new Updates2MQTT container when it starts, after logging the result. If the helper can’t be started, Updates2MQTT falls back to running compose from inside its own container, as in earlier versions.

Containers managed as a [Portainer](https://updates2mqtt.rhizomatics.org.uk/configuration/portainer/index.md) stack are redeployed by Portainer instead.

#### Ensuring Always Running

Use cron to make sure the container is always up, this example will run once an hour, adapt the schedule and the location of `docker-compose.yaml` for your needs.

```bash
sudo crontab -e
```

```bash
0 * * * * /usr/bin/docker compose -f /containers/updates2mqtt/docker-compose.yaml up -d --no-recreate
```

### Without Docker

Updates2MQTT is published as a [PyPI package](https://pypi.org/project/updates2mqtt/) on every release, so it can be used in any way you like - cron, systemd, your own Dockerfile, or whatever.

#### Run without installing using uv

```bash
uv run --with updates2mqtt updates2mqtt
```

#### Install and run with pip

```bash
pip install updates2mqtt
python3 -m updates2mqtt
```

### Github Token

A GitHub access token is optional, however when supplied additional API calls can be made for GHCR images, and the quotas for all APIs may be higher.

When creating the access token, ensure it has the `packages:read` permission, or use the ‘Classic’ rather than fine-grained token.

One case where access tokens help is if there either no version label in the image, or the label isn’t a version ( for example, Homarr has `main` as the version for all images.) In these case, the authenticated only [packages API calls](https://docs.github.com/en/rest/packages/packages) will be made to match a version from the image digest.

### Portainer

See the [Portainer Configuration](https://updates2mqtt.rhizomatics.org.uk/configuration/portainer/index.md) section.
