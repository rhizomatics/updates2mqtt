# Understanding Container Metadata


## Key Entities

Documented at the [OCI Image Format Specification](https://github.com/opencontainers/image-spec/blob/main/spec.md)

```mermaid
---
config:
    class:
      hideEmptyMembersBox: true
---
classDiagram
    class ImageIndex {
        +ManifestDescriptor[] manifestDescriptors
        +Annotations annotations
    }
    link ImageIndex "https://github.com/opencontainers/image-spec/blob/main/image-index.md" "OCI Specification"
    note for ImageIndex "Catalogs manifests\n for each architecture\n and operating systems"
    class ImageManifest {
        +Descriptor config
        +Descriptor[] layers
        +Annotations annotations
    }
    link ImageManifest "https://github.com/opencontainers/image-spec/blob/main/manifest.md" "OCI Specification"
    note for ImageManifest "Lists layers and\n their digests,\n and points to the config doc"
    class ImageConfig {
        +string created
        +string author
        +string architecture
        +string os
        +Config config
        +RootFS rootfs
        +History[] history
    }
    link ImageConfig "https://github.com/opencontainers/image-spec/blob/main/config.md" "OCI Specification"
    note for ImageConfig "Everything specified\n by the Dockerfile,\n and history to\n record building of each step"

    ImageIndex "1" --> "*" ImageManifest : refers
    ImageManifest "1" --> "1" ImageConfig : refers
    ImageManifest "1" --> "*" Layers : refers


```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```
```