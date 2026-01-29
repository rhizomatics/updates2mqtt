# Remote API Usage

Updates2MQTT uses several remote APIs to check for new versions, or pull in useful metadata,
in addition to local API calls to the Docker daemon.

* **Docker Registry V1 API**
    * These calls are all made via the [docker-py](https://docker-py.readthedocs.io/en/stable/) Python SDK from the Docker vendor, and now only if the alternative `registry_access` is selected
* **OCI Container Distribution V2 API**
    * This API is supported all mainstream container registries, and provides indexes ( which can be accessed by digest, or by a tag like `latest` or `nightly`, and are the mechanism by which new versions are discovered), plus manifests and config documents which provide more detail including annotations and labels
* **GitHub REST API**
    * Used to pull in release summaries where container images provide source links and revisions
* **LinuxServer API**
    * Used to get release notes and icons for lots of popular containers


## API Throttling

### Container Registry APIs

Docker API has [usage limits](https://docs.docker.com/docker-hub/usage/) which may be triggered if there are many containers ( and other registries will have similar).

`updates2mqtt` will back off if a `429` Too Many Requests response is received, and pause for that specific registry for the requested number of seconds. There's a default in `docker` config of `default_api_backoff` applied if the backoff can't be automatically determined.

The main technique to avoid throttling is caching of responses, and fortunately many of the calls are cache friendly, such as the manifest retrieval. By default, responses will be cached as suggested by the registry API service ([explanation](https://hishel.com/1.1/specification/#how-it-works)), however this can be overridden with these options:

| Config Key | Default | Comments |
| ---------- | ------- | -------- |
| `mutable_cache_ttl` | None | This is primarily the fetch of `latest` or similar tags to get new versions |
| `immutable_cache_ttl` | 7776000 (90 days) | This is for anything fetched by a digest, such as image manifests. The only limitation for these should be storage space |
| `token_cache_ttl` | None | Caching for authorization tokens, `docker.io` is good for 300 seconds, not all registries publish the life in the response |

The cache, using [Hishel](https://hishel.com), is automatically cleaned up of old entries once the TTL (Time to Live) has expired.

The other approach can be to reduce the scan interval, or ignore some of the containers.

### GitHub API

GitHub REST API has its own throttling, which may impact fetching release summaries. A higher limit can be achieved using a
*personal access token*. Create one in *Developer Settings* in GitHub, make sure it has access to "Public Repositories",
and configure it in Updates2MQTT as below:

```yaml title="updates2mqtt config snippet"
github:
  access_token: my_access_token
```
