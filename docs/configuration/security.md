# Improving Security

## Moving Secrets Out of Config

Example use of environment variables, e.g. for secrets:

```yaml title="config.yaml snippet"
mqtt:
    password: ${oc.env:MQTT_PASS}
```

## Running as non-root

It is good practice not to run Docker containers as root, and `updates2mqtt` will work with any user so long as it has Docker permissions, usually as a result of being a member of the `docker` group.

To create a suitable use, use the shell command below - it will create a user
that can only be used for this purpose, and can't otherwise login. It assumes there is already a group called `docker` with access to the Docker Daemon, if you dont
have one, follow the [Docker Post Install Steps](https://docs.docker.com/engine/install/linux-postinstall/) which explain how and why to do it.

```bash
sudo adduser --system --ingroup docker --no-create-home -shell /sbin/nologin updates2mqtt
```

Note the `uid` that is reported here. If you don't know the `gid` for the `docker` group, use `grep docker /etc/group`. In this example, our `uid` is `130` and the `gid` of `docker` group is `119`.

In the `docker-compose.yaml`, set the user and group using [user](https://docs.docker.com/reference/compose-file/services/#user) attribute:

```yaml title="docker compose snippet"
services:
  updates2mqtt:
    container_name: updates2mqtt
    image: ghcr.io/rhizomatics/updates2mqtt:latest
    user: 130:119
```

If you're using Updates2MQTT to update local git repos, then the user created above will also need `rw` access to those, which you can do by making it a member of the
same group as owns the repos and making sure they have group `rw` access configured.

For more information, see the [Understanding the Docker USER Instruction](https://www.docker.com/blog/understanding-the-docker-user-instruction/) article from Docker.

## MQTT Access Control

Its best to have a dedicated MQTT user for Updates2MQTT, for security and debug. For most
secure installations, only use secure ports with validated certificates, although this will
require more complicated setup and ongoing support, including using host names rather than
IP addresses, and with [LetsEncrypt](https://letsencrypt.org) to update certificates.

The two brokers most commonly used with Home Assistant, **Mosquitto** and **EMQX**, both have access control mechanisms, so you can restrict the user account for Updates2MQTT to only be able to read and write its own topics.

### Restricting update commands

Anyone who can publish to Updates2MQTT's command topic can make it pull images and restart
containers, so it's worth limiting that to Home Assistant. The command topic is
`<topic_root>/<node>/<source>`, e.g. `updates2mqtt/dockernuc/docker`, and Updates2MQTT publishes
state, attributes and availability under the same `updates2mqtt/` prefix.

For Mosquitto, an [ACL file](https://mosquitto.org/man/mosquitto-conf-5.html) along these lines gives each
user only what it needs, assuming users called `updates2mqtt` and `homeassistant`, and the
default `updates2mqtt` topic root and `homeassistant` discovery prefix:

```text title="mosquitto acl_file"
# Updates2MQTT publishes state, attributes, availability, discovery config and its healthcheck
user updates2mqtt
topic readwrite updates2mqtt/#
topic readwrite homeassistant/update/#
topic readwrite healthcheck/#

# Home Assistant reads everything Updates2MQTT publishes, and is the only other user that can send commands
user homeassistant
topic readwrite homeassistant/#
topic read updates2mqtt/#
topic write updates2mqtt/+/+
```

Other users get no access to these topics unless given it, as Mosquitto denies anything an ACL
doesn't allow once an `acl_file` is configured. Add the lines your other users need, without
`write` on `updates2mqtt/`. `updates2mqtt/+/+` matches the command topics, and also the availability
topic, but not the state and attribute topics, which are a level deeper. If you've changed `topic_root` or the discovery `prefix`, adjust
the topics to match.

### Retained commands

From v1.19.0, a command published with the MQTT `retain` flag is ignored, with a warning in the log.
The broker would deliver it again every time Updates2MQTT reconnected or restarted, repeating the
install each time. Home Assistant doesn't retain its update commands, so this only affects scripts
and automations that publish their own.

### Saying which release to install

A command can end with the digest it expects to install, as `docker|<container>|install|sha256:...`,
using the `image_digest` from the `latest_detail` section of the container's attributes. The command is
ignored if the latest scan found a different digest, so a script or automation only ever installs the
release it looked at. The plain `docker|<container>|install` form, which Home Assistant sends,
works as before.

### Unencrypted connections

Updates2MQTT logs a warning at startup when the broker is on another host and `tls_mode` is `off`,
since the MQTT password and update commands then cross the network unencrypted. See [MQTT TLS](#mqtt-tls).

## Container Settings

Labels and environment variables on a container change how Updates2MQTT treats it, and a container
inherits both from its image. From v1.19.0, an image can only supply the picture, release notes and
display name for itself. Everything else, including the update policy, cooldown and local build path,
has to be set on the container, see
[Where Settings Have to be Set](customizing_containers.md#where-settings-have-to-be-set). Images you
trust, such as your own, can be named in `trust_image_settings` to accept all of their settings.
Wildcards aren't accepted there.

In the same way, the Docker Compose labels that say where a container's compose project lives are
ignored if they came from the image, not from Compose, so an image can't have `docker compose`
run in a directory of its choosing.

For local builds, `git_repo_roots` restricts which directories git is run in, see
[Limiting where git is run](../local_builds.md#limiting-where-git-is-run).

## Config File Permissions

`config.yaml` often holds the MQTT password, and possibly a GitHub token or Portainer API key.
A config file generated by Updates2MQTT is created readable only by its owner, from v1.19.0. For an
existing one that holds secrets and can be read by every user on the host, a warning is logged at
startup. Fix it with `chmod 600 conf/config.yaml`, or move the secrets to environment variables as
shown at the top of this page.

## Docker API Access

Updates2MQTT talks to Docker through `/var/run/docker.sock`, which allows anything the Docker
daemon can do, and so is effectively `root` on the host. Look after it accordingly:

- Only mount the compose directories Updates2MQTT needs to update, not whole filesystems
- If you only want update notifications, set `allow_pull`, `allow_restart` and `allow_build` to
  `false` in the `docker` section of the config
- Add `no-new-privileges` to the Updates2MQTT service, as the [example compose file](examples/docker_compose.md) does,
  so nothing in the container can gain privileges through setuid binaries
- A Docker socket proxy, such as
  [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), can block API areas
  Updates2MQTT doesn't use, such as `exec`, swarm, secrets and plugins. Point Updates2MQTT at it
  with the `DOCKER_HOST` env var, e.g. `DOCKER_HOST=tcp://docker-socket-proxy:2375`.
  Notifications only need read access to containers and images. Applying updates also needs `POST`,
  and access to containers, images, networks and volumes for `docker compose`, which is still
  powerful, so a proxy reduces exposure rather than removing it. This setup isn't yet part of the
  Updates2MQTT test suite, so check your updates work after switching to it.

## What Updates2MQTT Can't Do for You

Some protections can't be switched on by default, because they depend on how the host is set up, or
would break existing installs. They're worth doing by hand where they fit.

### The Docker socket is root

Nothing in Updates2MQTT can change this. Anything that takes over the container can take over the
host, through the socket. So:

- Keep the MQTT broker's access controls tight, as [above](#mqtt-access-control), since MQTT is the way in
  from the network
- Use a [socket proxy](#docker-api-access) if you want to narrow what the socket allows
- Turn off `allow_pull`, `allow_restart` and `allow_build` on hosts where notification is enough

### Run as a non-root user

The image runs as `root` unless told otherwise, because the user and group that can reach the Docker
socket differ from host to host, so there's no default that would work everywhere. Set `user` as
described in [Running as non-root](#running-as-non-root). The user still controls Docker, so this
limits accidents and file ownership more than it limits an attacker.

### Read-only filesystem and dropped capabilities

These can work, but need testing on your setup, so aren't in the example compose file:

- `read_only: true` needs writable places left for the app: `/app/conf`, the heartbeat file's
  directory (`/tmp` unless `U2M_HEARTBEAT_FILE` moves it), `/app/.cache`, and the home directory if
  `docker login` credentials or git are used. `tmpfs` mounts cover the ones that needn't persist
- `cap_drop: [ALL]` stops `root` in the container from writing files owned by other users. If the
  `conf` directory or local build repos belong to your own user on the host, config generation,
  the release history and `git pull` will then fail. It works best combined with running as the
  user that owns those files

### Other containers with the Docker socket

Every container given the socket is as powerful as Updates2MQTT, and needs the same care. That
includes a `restarter` sidecar like the one in the example compose file. Pin its image to a version
you've checked, e.g. `docker:29-cli`, in place of the floating `docker:cli`, and think about
whether you want it on `UPD2MQTT_UPDATE=AUTO`, since that installs new versions of a
root-equivalent container unattended, and cooldowns aren't enforced yet.

### Bind mounts shared with other containers

Updates2MQTT needs to see the compose directories, and containers often keep their data in the same
directories. A compromised container can therefore write files where Updates2MQTT can read them.
Updates2MQTT no longer takes paths to act on from images, but you can reduce the overlap further:

- Mount compose directories into Updates2MQTT read-only where local builds aren't used. Compose only
  needs to read them
- Keep container data in a separate tree from the compose files, where that's practical
- Set `git_repo_roots` if you use local builds

### Images you run are trusted by you

Updates2MQTT installs exactly the image it checked, but can't tell you whether that image is safe.
Cooldowns are reported but not yet enforced, and signatures aren't yet verified, see
[Supply Chain Protection](supply_chain.md). Until then, prefer images from publishers you know, pin
versions where you can, and leave `Auto` updates for images you'd trust with the host.

### Checking the Updates2MQTT image

The image is published with build provenance and an SBOM. To check that the image you pulled was
built by this project's release workflow, with the [GitHub CLI](https://cli.github.com):

```bash
gh attestation verify oci://ghcr.io/rhizomatics/updates2mqtt:release --owner rhizomatics
```

From v1.19.0 the image is also signed with [cosign](https://docs.sigstore.dev/cosign/system_config/installation/),
without any long-lived keys: the signature is tied to the identity of the release workflow, and recorded
in Sigstore's public transparency log. To verify it, with a recent cosign:

```bash
cosign verify ghcr.io/rhizomatics/updates2mqtt:release \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/rhizomatics/updates2mqtt/\.github/workflows/docker-publish\.yml@refs/(tags/v.+|heads/main)$'
```

The identity has two forms because a release is signed from its tag, and a rebuilt revision from `main`.
Images published before v1.19.0 aren't signed, and only have the provenance attestation.

Version tags, such as `1.19.0`, are published once and never changed. When a release is rebuilt to
pick up fixes in the base image or system packages, it's published as a new revision, `1.19.0-r1`,
`1.19.0-r2` and so on, and the floating `1.19` and `release` tags move to the newest. Pin a full
version, or a digest, if you want to decide when that happens. System packages in a rebuild come
straight from Debian's security updates, with no waiting period, since there's no practical way to
hold those back.

## Supply Chain Protection

See [Supply Chain Protection](supply_chain.md) for how Updates2MQTT installs exactly the image it
checked, tracks release history, and reports update cooldowns.

By default, the digest a registry reports for an image tag is trusted. Switch on
[strict mode](supply_chain.md#strict-registry-checks) to check it against the manifest the registry serves,
and to refuse registry data that can't be verified:

```yaml title="config.yaml snippet"
docker:
  registry:
    strict: true
```

Until strict mode is on, a warning is logged at startup. It applies to the default `OCI_V2` and
`OCI_V2_MINIMAL` registry clients, not to `DOCKER_CLIENT`.

## MQTT TLS

`tls_mode` defaults to `off`, and can be switched to `on` or to `insecure` for testing with mismatched hostnames.

Encrypt MQTT broker communication with TLS to wrap socket communication and optionally verify client and.or server identity.

This can be used in basic non-auth mode, (using default public certificate authorities, or local ones located at  `ca_certs` in the `mqtt` config section), or using client certificates too with `client_cert` and `client_key`. `cert_reqs` can be used with any of the python SSL values, e.g. `CERT_REQUIRED`.

```yaml
mqtt:
  host: localhost
  port: 1883
  tls_mode: ON
  ca_certs: ssl/ca_cert.crt
  client_cert: ssl/client_cert.pem
  client_key: ssl/client_key.pem
  cert_reqs: CERT_OPTIONAL
```

See the [Paho MQTT `tls_set`](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html#paho.mqtt.client.Client.tls_set) API documentation for more on the underlying config, which is based on Python's [ssl](https://docs.python.org/3/library/ssl.html) module.