# Portainer Configuration

## Installation

Install an Updates2MQTT container on each Portainer host, this can be using a `docker-compose.yaml` file, or using the Portainer UI to define the image name and env vars ( no config file required ).

## Implementation

**Update detection** works fully for Portainer stacks, since it only needs the Docker socket. Each stack container shows up as a Docker Compose service, even if it was defined entirely in the Portainer UI.

**Updating from Home Assistant** needs Portainer API access. Updates2MQTT pulls the new image through the Docker API, but recreating the container normally means running `docker compose` in the stack’s directory. Portainer keeps stack files in its own data volume, at `/data/compose/<stack id>`, rather than on the host file system, so Updates2MQTT can’t see them, and for hosts managed by a Portainer Agent, the files are on a different machine entirely. Instead, Updates2MQTT can ask Portainer to redeploy the stack.

1. In Portainer, go to *My account* → *Access tokens* and create a token

1. Give each Updates2MQTT container the Portainer URL and token, either as env vars

   ```yaml
   environment:
     - PORTAINER_URL=https://portainer.example.com:9443
     - PORTAINER_API_KEY=ptr_xxxxxxxxxxxx
   ```

   or in the config file

   ```yaml
   docker:
     portainer:
       url: https://portainer.example.com:9443
       api_key: ptr_xxxxxxxxxxxx
       verify_ssl: true # set false for Portainer's default self-signed certificate
       ca_certs: /certs/root_ca.pem # optional, CA file to verify Portainer's certificate
       timeout: 300     # seconds to wait for the redeploy to complete
   ```

If Portainer uses a certificate signed by your own CA, mount the root CA file into the container and set `PORTAINER_CA_CERTS` (or `ca_certs`) to its path. Only that CA file is used for verification, not the public CA bundle. `PORTAINER_VERIFY_SSL=false` (or `verify_ssl: false`) skips verification altogether, e.g. for Portainer’s default self-signed certificate.

When *Update* is pressed, the new image is pulled locally, and then Portainer redeploys the stack with its existing stack file and environment variables. The redeploy doesn’t pull images itself, so only containers whose image was just pulled get recreated, not every service in the stack. Stacks on Agent-managed hosts work the same way, since Portainer routes the redeploy to the right host.

## Limitations

- Only compose stacks can be redeployed, not Swarm or Kubernetes stacks
- Git-based stacks are redeployed from the stack’s configured branch, so any new commits come in too
- Portainer itself and its agents can’t be updated this way, use the command line for those
- The token’s user needs access to the environment the stack runs in

Without Portainer API access, Updates2MQTT will:

- Report `can_restart` as `false`, and `compose_path_found` as `false` in the MQTT attributes
- Add a `portainer_stack_id` attribute, so you know which stack to redeploy
- Log a warning at startup naming the stack

The image will still be pulled when *Update* is pressed in Home Assistant, so a following *Re-deploy* in Portainer is quick, but the running container isn’t changed until then. Containers managed by plain `docker compose` on the same host are not affected, and update as normal.
