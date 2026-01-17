import docker
import httpx

custom={}

def save_if_set(key: str, val: str | None) -> None:
    if val is not None:
        custom[key] = val

client=docker.from_env()
for c in client.containers.list():
    
    image_version: str = c.labels.get("org.opencontainers.image.version")
    image_revision: str = c.labels.get("org.opencontainers.image.revision")
    source = c.labels.get("org.opencontainers.image.source")
    if source and image_revision and "github.com" in source:
       diff_url = f"{source}/commit/{image_revision}"
       save_if_set("diff_url", diff_url)
       release_url = f"{source}/releases/tag/{image_version}"
       save_if_set("release_url", release_url)
       response=httpx.get(release_url)
       if response.status_code==200:
           print("GOOD %s" % release_url)
       else:
           print("BROKEN %s" % release_url)
       response=httpx.get(diff_url)
       if response.status_code==200:
           print("GOOD %s" % diff_url)
       else:
           print("BROKEN %s" % diff_url)
    else:
       print("No metadata for %s" % c.name)

         
