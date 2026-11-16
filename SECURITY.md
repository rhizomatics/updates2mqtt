# Security Policy

Updates2MQTT has access to the Docker daemon, which is equivalent to `root` on the host, and acts on
commands received over MQTT, so security reports are taken seriously.

## Supported Versions

Security fixes are made to the latest release only. Please update to it before reporting, as the
problem may already be fixed.

## Reporting a Vulnerability

Please don't open a public issue for a vulnerability.

Report it privately using GitHub's
[private vulnerability reporting](https://github.com/rhizomatics/updates2mqtt/security/advisories/new),
from the *Security* tab of the repository. Include:

- the Updates2MQTT version, and how it's installed (Docker image or PyPI)
- what an attacker needs to start with, for example MQTT publish rights, or control of an image
- steps to reproduce, or a proof of concept
- what the attacker gains

You should get an acknowledgement within a week. Once a fix is released, the advisory is published,
with credit to the reporter unless you'd rather not be named.

## Scope

Of most interest:

- anything that lets a container image, a registry, or an MQTT client run commands, or install
  something other than what was checked
- leaks of credentials, such as MQTT passwords, registry tokens, or GitHub and Portainer API keys
- weaknesses in the build and release pipeline for the PyPI package and Docker image

Anyone able to publish to the command topic can ask for updates to be installed, by design. Restrict
that with broker access controls, as described in
[Improving Security](https://updates2mqtt.rhizomatics.org.uk/configuration/security/).

## Hardening Your Install

See [Improving Security](https://updates2mqtt.rhizomatics.org.uk/configuration/security/) and
[Supply Chain Protection](https://updates2mqtt.rhizomatics.org.uk/configuration/supply_chain/).
