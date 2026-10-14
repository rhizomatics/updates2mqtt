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

### On Portainer

Install an Updates2MQTT container on each Portainer host, this can be using a `docker-compose.yaml` file, or using the Portainer UI to define the image name and env vars ( no config file required ).

**Update detection** works fully for Portainer stacks, since it only needs the Docker socket. Each stack container shows up as a Docker Compose service, even if it was defined entirely in the Portainer UI.

**Updating from Home Assistant** is more limited. Updates2MQTT pulls the new image through the Docker API, but recreating the container needs `docker compose` to be run in the stack’s directory. Portainer keeps stack files in its own data volume, at `/data/compose/<stack id>`, rather than on the host file system, so this directory usually can’t be seen by Updates2MQTT, and for hosts managed via a Portainer Agent, the files are on a different machine entirely.

In this case Updates2MQTT will:

- Report `can_restart` as `false`, and `compose_path_found` as `false` in the MQTT attributes
- Add a `portainer_stack_id` attribute, so you know which stack to redeploy
- Log a warning at startup naming the stack

The image will still be pulled when *Update* is pressed in Home Assistant, so a following *Re-deploy* in Portainer is quick, but the running container isn’t changed until then. Containers managed by plain `docker compose` on the same host are not affected and update as normal.

### Github Token

A GitHub access token is optional, however when supplied additional API calls can be made for GHCR images, and the quotas for all APIs may be higher.

When creating the access token, ensure it has the `packages:read` permission, or use the ‘Classic’ rather than fine-grained token.

One case where access tokens help is if there either no version label in the image, or the label isn’t a version ( for example, Homarr has `main` as the version for all images.) In these case, the authenticated only [packages API calls](https://docs.github.com/en/rest/packages/packages) will be made to match a version from the image digest.
