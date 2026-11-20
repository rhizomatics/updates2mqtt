# Packages

The `packages` block, keyed by package name, and the built-in `common_packages.yaml`, which share the same entry format. See [Common Packages](https://updates2mqtt.rhizomatics.org.uk/configuration/common_packages/index.md).

## PackageUpdateInfo

Metadata for a package, an entry in `packages`, or in the built-in common packages

### docker

```python
docker: DockerPackageUpdateInfo | None = field(
    default_factory=DockerPackageUpdateInfo
)
```

Images that belong to this package

### logo_url

```python
logo_url: str | None = None
```

Picture shown on the Home Assistant update entity

### release_notes_url

```python
release_notes_url: str | None = None
```

Link to the release notes

### source_repo_url

```python
source_repo_url: str | None = None
```

Source code repository, used to find release notes on GitHub

## DockerPackageUpdateInfo

Docker specifics of a package

### image_name

```python
image_name: Any = MISSING
```

Untagged image ref, either a single string or a list of strings, mandatory

### version_policy

```python
version_policy: VersionPolicy = VersionPolicy.AUTO
```

Version policy for images of this package

## CommonPackages

Built-in package metadata, the format of `common_packages.yaml`

### common_packages

```python
common_packages: dict[str, PackageUpdateInfo] = field(
    default_factory=dict
)
```

Package metadata, keyed by package name
