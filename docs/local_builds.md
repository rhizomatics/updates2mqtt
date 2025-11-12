# Local Builds

## Custom docker builds

If the image is locally built from a checked out git repo, package update can be driven by the availability of git repo changes to pull rather than a new image on a Docker registry.

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

Declare the git path using the env var in ``UPD2MQTT_GIT_REPO_PATH`` in the docker container ( directly or via an ``.env`` file). The git repo at this path will be used as the source of timestamps, and an update command will carry out a 
``git pull`` and ``docker-compose build`` rather than pulling an image.

Note that the updates2mqtt docker container needs access to this path declared in its volumes, and that has to be read/write if automated install required.