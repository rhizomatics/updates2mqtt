# Improving Security

## Moving Secrets Out of Config

Example use of environment variables, e.g. for secrets:

```yaml title="config.yaml snippet"
mqtt:
    password: ${oc.env:MQTT_PASS}
```

## Running as non-root

It is good practice not to run Docker containers as root, and `updates2mqtt` will
work with any user so long as it has Docker permissions, usually as a result
of being a member of the `docker` group.

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

The two brokers most commonly used with Home Assistant, **Mosquitto** and **EMQX**, both have
access control mechanisms, so you can restrict the user account for Updates2MQTT to only be able
to read and write its own topics.
