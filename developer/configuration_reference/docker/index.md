# Docker

The `docker` block, and the blocks nested inside it.

## DockerConfig

Docker container scanning and updating, the `docker` block

### enabled

```python
enabled: bool = True
```

Scan Docker containers

### allow_pull

```python
allow_pull: bool = True
```

Allow updates by pulling the new image

### allow_restart

```python
allow_restart: bool = True
```

Allow updates to recreate the container with `docker compose up`

### allow_build

```python
allow_build: bool = True
```

Allow updates of local builds with `docker compose build`

### git_repo_roots

```python
git_repo_roots: list[str] = field(default_factory=list)
```

Directories that local build git repos have to be inside, e.g. `["/home/containers"]`. Any path set on a container is accepted while this is empty

### trust_image_settings

```python
trust_image_settings: list[str] = field(
    default_factory=list
)
```

Images trusted to supply any setting through their own labels or env, e.g. ones you build yourself. Plain image refs only, as written in the compose file, with or without a tag, e.g. `["ghcr.io/me/myapp"]`. Wildcards and patterns are refused

### remove_old_image

```python
remove_old_image: bool = (
    "${oc.env:U2M_REMOVE_OLD_IMAGE,false}"
)
```

Remove the previous image once a container has been recreated with the new one, from `U2M_REMOVE_OLD_IMAGE`

### compose_version

```python
compose_version: str = 'v2'
```

`v2` for `docker compose`, `v1` for `docker-compose`

### max_concurrent_updates

```python
max_concurrent_updates: int = (
    "${oc.env:U2M_MAX_CONCURRENT_UPDATES,3}"
)
```

Updates run in parallel up to this limit, further ones queue for a free slot, from `U2M_MAX_CONCURRENT_UPDATES`

### default_entity_picture_url

```python
default_entity_picture_url: str = "https://www.docker.com/wp-content/uploads/2022/03/Moby-logo.png"
```

Picture for update entities with no package logo

### device_icon

```python
device_icon: str = 'mdi:docker'
```

Icon to show when browsing entities in Home Assistant

### discover_metadata

```python
discover_metadata: dict[str, MetadataSourceConfig] = field(
    default_factory=lambda: {
        "linuxserver.io": MetadataSourceConfig(
            enabled=True
        ),
        "hotio.dev": MetadataSourceConfig(enabled=True),
    }
)
```

Online catalogues of image metadata, keyed by name

### registry

```python
registry: RegistryConfig = field(
    default_factory=lambda: RegistryConfig()
)
```

Registry client and caching

### default_api_backoff

```python
default_api_backoff: int = 60 * 15
```

Seconds to back off a registry API after it throttles

### image_ref_select

```python
image_ref_select: Selector = field(
    default_factory=lambda: Selector()
)
```

Image refs to publish

### version_select

```python
version_select: Selector = field(
    default_factory=lambda: Selector()
)
```

Latest versions to publish

### version_policy

```python
version_policy: VersionPolicy = VersionPolicy.AUTO
```

Default version policy for all containers

### registry_select

```python
registry_select: Selector = field(
    default_factory=lambda: Selector()
)
```

Registries, by index name, to look up latest versions in

### container_select

```python
container_select: Selector = field(
    default_factory=lambda: Selector()
)
```

Container names to ignore completely, e.g. exclude `["^lab_", "^beta_"]`, as regular expressions

### portainer

```python
portainer: PortainerConfig = field(
    default_factory=lambda: PortainerConfig()
)
```

Portainer API access, for stacks managed by Portainer

### cooldown

```python
cooldown: str = '3d'
```

How long a release has to be known before it’s eligible to update, e.g. `72h`, `3d`, `1w`, or `0` for none. Observe only for now, reported in the update attributes, see RFC 0002

## Registry

## RegistryConfig

Container registry lookups, the `docker.registry` block

### api

```python
api: RegistryAPI = RegistryAPI.OCI_V2
```

Registry client used to find the latest image

### mutable_cache_ttl

```python
mutable_cache_ttl: int | None = 60 * 60
```

Seconds to cache responses that can change, such as tag lookups

### immutable_cache_ttl

```python
immutable_cache_ttl: int | None = 7776000
```

Seconds to cache responses addressed by digest, which can’t change

### token_cache_ttl

```python
token_cache_ttl: int | None = None
```

Seconds to cache registry auth tokens, or `None` to follow the registry’s own expiry

## RegistryAPI

How the latest version of an image is looked up, matched case insensitively

### OCI_V2

```python
OCI_V2 = 'OCI_V2'
```

Built-in OCI Distribution v2 client, with manifests, configs and annotations, see RFC 0001

### OCI_V2_MINIMAL

```python
OCI_V2_MINIMAL = 'OCI_V2_MINIMAL'
```

Built-in OCI v2 client, using the manifest only, without fetching the image config for labels

### DOCKER_CLIENT

```python
DOCKER_CLIENT = 'DOCKER_CLIENT'
```

The Docker engine’s own distribution API

### DISABLED

```python
DISABLED = 'DISABLED'
```

No registry lookups

## Selection

## Selector

Regular expression filter, where a value is selected if it matches an `include` and no `exclude`

### include

```python
include: list[str] | None = None
```

Patterns to select, or all if empty

### exclude

```python
exclude: list[str] | None = None
```

Patterns to reject, applied after `include`

## VersionPolicy

How the installed and latest versions are described

### AUTO

```python
AUTO = 'AUTO'
```

Pick the best available for the image

### VERSION

```python
VERSION = 'VERSION'
```

Version label or tag only

### DIGEST

```python
DIGEST = 'DIGEST'
```

Image digest only

### VERSION_DIGEST

```python
VERSION_DIGEST = 'VERSION_DIGEST'
```

Version with an abbreviated digest

### TIMESTAMP

```python
TIMESTAMP = 'TIMESTAMP'
```

Image creation time

## Metadata Catalogues

## MetadataSourceConfig

A catalogue of image metadata, such as linuxserver.io, in `docker.discover_metadata`

### enabled

```python
enabled: bool = True
```

Look up logos, release notes and source links in this catalogue

### cache_ttl

```python
cache_ttl: int = 60 * 60 * 24 * 7
```

Seconds to cache the catalogue

## Portainer

See [Portainer](https://updates2mqtt.rhizomatics.org.uk/configuration/portainer/index.md).

## PortainerConfig

Portainer API access, used to redeploy stacks whose compose files live in Portainer’s data volume

### url

```python
url: str | None = '${oc.env:PORTAINER_URL,null}'
```

Portainer base URL, from `PORTAINER_URL`

### api_key

```python
api_key: str | None = '${oc.env:PORTAINER_API_KEY,null}'
```

Portainer API access token, from `PORTAINER_API_KEY`

### verify_ssl

```python
verify_ssl: bool = '${oc.env:PORTAINER_VERIFY_SSL,true}'
```

Verify Portainer’s TLS certificate, from `PORTAINER_VERIFY_SSL`

### ca_certs

```python
ca_certs: str | None = '${oc.env:PORTAINER_CA_CERTS,null}'
```

CA certificate bundle to verify Portainer, e.g. a private root CA, from `PORTAINER_CA_CERTS`

### timeout

```python
timeout: int = 300
```

Seconds allowed for API calls, and for a stack deployment to finish
