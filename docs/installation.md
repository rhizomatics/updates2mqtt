# Installation

## Install

updates2mqtt prefers to be run inside a Docker container, though can run standalone, for example scripted via cron or systemd.

### Docker

See `examples` directory for a working `docker-compose.yaml`.

If you want to update and restart containers, then the file system paths to the location of the directory where the docker compose file lives must be available in the updates2mqtt container. 

The example `docker-compose.yaml` mounts `/home/containers` for this purpose, so if your containers are in
`/home/containers/app1`, `/home/containers/app2` etc, then updates2mqtt will be able to find them. Map as many root paths as needed.

### Without Docker

#### Run without installing using uv

```
uv run --with updates2mqtt updates2mqtt
```

#### Install and run with pip

```
pip install updates2mqtt
python3 -m updates2mqtt
```
