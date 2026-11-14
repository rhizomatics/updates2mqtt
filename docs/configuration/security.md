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

## Docker API Access

Updates2MQTT talks to Docker through `/var/run/docker.sock`, which allows anything the Docker
daemon can do, and so is effectively `root` on the host. Look after it accordingly:

- Only mount the compose directories Updates2MQTT needs to update, not whole filesystems
- If you only want update notifications, set `allow_pull`, `allow_restart` and `allow_build` to
  `false` in the `docker` section of the config
- A Docker socket proxy, such as
  [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), can block API areas
  Updates2MQTT doesn't use, such as `exec`, swarm, secrets and plugins. Point Updates2MQTT at it
  with the `DOCKER_HOST` env var, e.g. `DOCKER_HOST=tcp://docker-socket-proxy:2375`.
  Notifications only need read access to containers and images. Applying updates also needs `POST`,
  and access to containers, images, networks and volumes for `docker compose`, which is still
  powerful, so a proxy reduces exposure rather than removing it. This setup isn't yet part of the
  Updates2MQTT test suite, so check your updates work after switching to it.

## Supply Chain Protection

See [Supply Chain Protection](supply_chain.md) for how Updates2MQTT installs exactly the image it
checked, tracks release history, and reports update cooldowns.

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