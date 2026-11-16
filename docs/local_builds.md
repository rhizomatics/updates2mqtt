# Local Builds

## Custom docker builds

If the image is locally built from a checked out git repo, package update can be driven by the availability of git repo changes to pull rather than a new image on a Docker registry. This will both show where a change is available in Home Assistant ( or other MQTT client ), and allow an update to be triggered remotely. 

(People sometimes do this as a quick way of forking and changing a repo that doesn't quite work for them, or if the app is a development work in progress).

```yaml title="Example docker-compose.yaml snippet"
services:
  mymailserver:
    build: ./build/mymailserver
    environment:
      - UPD2MQTT_GIT_REPO_PATH=build/mymailserver
    volumes:
      - /home/containers/mymailserver/build:/home/containers/mymailserver/build
```

Declare the git path using the env var in ``UPD2MQTT_GIT_REPO_PATH`` in the docker container ( directly or via an ``.env`` file), or an equivalent label (see [Docker Labels](configuration/customizing_containers.md#docker-labels)). The git repo at this path will be used as the source of timestamps, and an update command will carry out a `git pull` and `docker-compose build` rather than pulling an image.

Note that the Updates2MQTT docker container needs access to this path declared in its volumes, and that has to be read/write if automated install required.

From v1.19.0, the path has to be set on the container itself, as above. A path that comes from the image's own labels or environment is ignored, see [Where Settings Have to be Set](configuration/customizing_containers.md#where-settings-have-to-be-set).

### Limiting where git is run

Git reads the configuration of whichever repo it's run in, and that configuration can make git run other programs. To restrict local builds to directories you trust, list them as `git_repo_roots` in the `docker` section of the config. A repo outside all of them is ignored, with a warning in the log:

```yaml title="config.yaml snippet"
docker:
  git_repo_roots:
    - /home/containers
```

With no `git_repo_roots`, any path set on a container is accepted. Setting `allow_build` to `false` stops Updates2MQTT running git at all.

Updates2MQTT no longer adds repos to the global git `safe.directory` list. Each git command marks its own repo as safe for that command only, so there's nothing to set up, even where the repo belongs to a different user.

Since there's no image digest, the current git revision will be used as the version, like `git:c2b12584a27f`, and when there are remote repo commits to pull, the new version will show
how many commits ahead it is, for example `git:c2b12584a27f+5`