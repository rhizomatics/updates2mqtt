import docker
import httpx
from pathlib import Path
from updates2mqtt.config import Config, PackageUpdateInfo, load_package_info

custom={}

def save_if_set(key: str, val: str | None) -> None:
    if val is not None:
        custom[key] = val

def valurl(url)->bool:
    try:
       response=httpx.get(url)
       return response.status_code
    except:
        pass
    return False

client=docker.from_env()
common_pkgs=load_package_info(Path("common_packages.yaml"))

def find_pkg(imgref):
    for pkg in common_pkgs.values():
         if pkg.docker.image_name == imgref:
             return pkg
    return None

for c in client.containers.list():

    image_ref=c.attrs.get("Config", {}).get("Image") or c.image.tags[0]
    image_name = image_ref.split(":")[0]
    pkg=find_pkg(image_ref) or find_pkg(image_name)
    print(pkg)
    image_version: str = c.labels.get("org.opencontainers.image.version")
    image_revision: str = c.labels.get("org.opencontainers.image.revision")
    source = c.labels.get("org.opencontainers.image.source")
    if source and image_revision and "github.com" in source:
       diff_url = f"{source}/commit/{image_revision}"
       save_if_set("diff_url", diff_url)
       release_url = f"{source}/releases/tag/{image_version}"
       save_if_set("release_url", release_url)
       if valurl(release_url):
           print("GOOD %s" % release_url)
       else:
           print("BROKEN %s" % release_url)
       if valurl(diff_url):
           print("GOOD %s" % diff_url)
       else:
           print("BROKEN %s" % diff_url)
    elif pkg:
        release_url=pkg.release_notes_url.format({"image_version"
    else:
       print("No metadata for %s" % c.name)

         
