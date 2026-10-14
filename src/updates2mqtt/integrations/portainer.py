from typing import Any

import httpx
import structlog

from updates2mqtt.config import PortainerConfig

PORTAINER_STACK_TYPE_COMPOSE = 2
# Portainer and its agents can't be safely redeployed by Portainer itself
PORTAINER_IMAGES: tuple[str, ...] = ("portainer/portainer-ce", "portainer/portainer-ee", "portainer/agent")


def is_portainer_image(image_ref: str | None) -> bool:
    return image_ref is not None and any(img in image_ref for img in PORTAINER_IMAGES)


class PortainerClient:
    """Redeploy Portainer stacks via the Portainer API

    Stack images are expected to already be pulled locally, so redeploy is made without `pullImage`,
    and only containers whose image has changed are recreated, rather than every service in the stack
    """

    def __init__(self, cfg: PortainerConfig) -> None:
        self.cfg: PortainerConfig = cfg
        self.log: Any = structlog.get_logger().bind(integration="portainer")

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.url and self.cfg.api_key)

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url=str(self.cfg.url).rstrip("/"),
            headers={"X-API-Key": str(self.cfg.api_key)},
            verify=self.cfg.verify_ssl,
            timeout=self.cfg.timeout,
        )

    def redeploy(self, stack_id: str) -> bool:
        logger: Any = self.log.bind(stack_id=stack_id, action="redeploy")
        try:
            with self.client() as client:
                response: httpx.Response = client.get(f"/api/stacks/{stack_id}")
                response.raise_for_status()
                stack: dict[str, Any] = response.json()
                if stack.get("Type") != PORTAINER_STACK_TYPE_COMPOSE:
                    logger.warning("Only compose stacks can be redeployed, stack type is %s", stack.get("Type"))
                    return False
                params: dict[str, Any] = {"endpointId": stack.get("EndpointId")}
                env: list[dict[str, str]] = stack.get("Env") or []
                git_config: dict[str, Any] | None = stack.get("GitConfig")

                if git_config:
                    # stored git credentials are reused when authentication flagged and password left empty
                    logger.info("Redeploying git stack %s from %s", stack.get("Name"), git_config.get("ReferenceName"))
                    response = client.put(
                        f"/api/stacks/{stack_id}/git/redeploy",
                        params=params,
                        json={
                            "env": env,
                            "prune": False,
                            "pullImage": False,
                            "repositoryReferenceName": git_config.get("ReferenceName"),
                            "repositoryAuthentication": git_config.get("Authentication") is not None,
                        },
                    )
                else:
                    response = client.get(f"/api/stacks/{stack_id}/file")
                    response.raise_for_status()
                    # file content and env must be sent back, otherwise Portainer replaces them with empty values
                    logger.info("Redeploying stack %s", stack.get("Name"))
                    response = client.put(
                        f"/api/stacks/{stack_id}",
                        params=params,
                        json={
                            "stackFileContent": response.json().get("StackFileContent"),
                            "env": env,
                            "prune": False,
                            "pullImage": False,
                        },
                    )
                response.raise_for_status()
                logger.info("Redeploy via Portainer successful")
                return True
        except httpx.HTTPStatusError as e:
            logger.warning("Portainer API error %s: %s", e.response.status_code, e.response.text)
        except httpx.HTTPError as e:
            logger.warning("Unable to reach Portainer at %s: %s", self.cfg.url, e)
        except ValueError as e:
            logger.warning("Unexpected Portainer response: %s", e)
        return False
