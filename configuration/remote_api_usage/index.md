# Remote API Usage

Updates2MQTT uses several remote APIs to check for new versions, or pull in useful metadata, in addition to local API calls to the Docker daemon.

- **Docker Registry V1 API**
  - These calls are all made via the [docker-py](https://docker-py.readthedocs.io/en/stable/) Python SDK from the Docker vendor, and now only if the alternative `registry_access` is selected
- **OCI Container Distribution V2 API**
  - This API is supported all mainstream container registries, and provides indexes ( which can be accessed by digest, or by a tag like `latest` or `nightly`, and are the mechanism by which new versions are discovered), plus manifests and config documents which provide more detail including annotations and labels
- **GitHub REST API**
  - Used to pull in release summaries where container images provide source links and revisions
- **LinuxServer API**
  - Used to get release notes and icons for lots of popular containers

## Private Registries

Registry checks use the same credentials as `docker login`, read from the Docker config file, `~/.docker/config.json`, or `config.json` in the directory named by the `DOCKER_CONFIG` env var. Credentials are only sent to registries that ask for them, and logging in to Docker Hub also gets a higher [rate limit](https://docs.docker.com/docker-hub/usage/) than anonymous access.

When running in Docker, mount the config file read-only into the Updates2MQTT container:

docker compose snippet

```yaml
volumes:
  - ~/.docker/config.json:/root/.docker/config.json:ro
```

Credentials saved directly in the file, under `auths`, work as is. Where `docker login` saved them to a credential helper instead, such as the desktop keychain or `pass`, listed under `credsStore` or `credHelpers`, that helper must also be installed in the Updates2MQTT container, otherwise those registries are checked anonymously. The same file is used by `docker pull` when updating.

A token for a single container can also be given with the `updates2mqtt.registry_token` label or `UPD2MQTT_REGISTRY_TOKEN` env var, see [Customizing Containers](https://updates2mqtt.rhizomatics.org.uk/configuration/customizing_containers/index.md).

## API Throttling

### Container Registry APIs

Docker API has [usage limits](https://docs.docker.com/docker-hub/usage/) which may be triggered if there are many containers ( and other registries will have similar).

`updates2mqtt` will back off if a `429` Too Many Requests response is received, and pause for that specific registry for the requested number of seconds. There’s a default in `docker` config of `default_api_backoff` applied if the backoff can’t be automatically determined.

The main technique to avoid throttling is caching of responses, and fortunately many of the calls are cache friendly, such as the manifest retrieval. By default, responses will be cached as suggested by the registry API service ([explanation](https://hishel.com/1.1/specification/#how-it-works)), however this can be overridden with these options:

| Config Key            | Default           | Comments                                                                                                                   |
| --------------------- | ----------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `mutable_cache_ttl`   | None              | This is primarily the fetch of `latest` or similar tags to get new versions                                                |
| `immutable_cache_ttl` | 7776000 (90 days) | This is for anything fetched by a digest, such as image manifests. The only limitation for these should be storage space   |
| `token_cache_ttl`     | None              | Caching for authorization tokens, `docker.io` is good for 300 seconds, not all registries publish the life in the response |

The cache, using [Hishel](https://hishel.com), is automatically cleaned up of old entries once the TTL (Time to Live) has expired.

The other approach can be to reduce the scan interval, or ignore some of the containers.

### GitHub API

GitHub REST API has its own throttling, which may impact fetching release summaries. A higher limit can be achieved using a *personal access token*. Create one in *Developer Settings* in GitHub, make sure it has access to “Public Repositories”, and configure it in Updates2MQTT as below:

updates2mqtt config snippet

```yaml
github:
  access_token: my_access_token
```
