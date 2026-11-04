"""Media types for OCI and Docker image manifests"""

OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_EMPTY = "application/vnd.oci.empty.v1+json"

DOCKER_MANIFEST_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
DOCKER_CONFIG = "application/vnd.docker.container.image.v1+json"

INDEX_MEDIA_TYPES: tuple[str, ...] = (OCI_INDEX, DOCKER_MANIFEST_LIST)
IMAGE_MANIFEST_MEDIA_TYPES: tuple[str, ...] = (OCI_MANIFEST, DOCKER_MANIFEST)
# index first, since a tag may point to either, and an index is preferred where published
ALL_MANIFEST_MEDIA_TYPES: tuple[str, ...] = INDEX_MEDIA_TYPES + IMAGE_MANIFEST_MEDIA_TYPES
