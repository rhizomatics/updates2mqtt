---
description: Supply chain protection for container updates - threat model, digest pinning, update cooldowns, signature and provenance checks, image scanning, and the phases to deliver them
---
# RFC 0002 Cyber Security Improvements

| | |
|---|---|
| **Status** | Phases 0 and 1 implemented in 1.18.0, later phases draft |
| **Created** | 2026-11-14 |
| **Supersedes** | the *Cooldown* RFC draft |

## Motivation

The pace of cyber attacks has increased hugely in 2026 with the help of AI agents, and supply chain attacks are more common and harder to deal with.

Package managers are adding cooldowns to shrink the window in which a supply chain attack can spread. Examples include Renovate's `minimumReleaseAge`, Dependabot's `cooldown`, uv's `exclude-newer` (used by this project, set to 7 days) and pnpm's `minimumReleaseAge`.

For an updater this is a double-edged sword:

- Reacting quickly to new software is itself an attack vector.
- But quickly applying a remediated release is the best defence once a vulnerability is known.

Updates2MQTT needs both: hold back new releases by default, and let a fix through when there's evidence it is one.

Updates2MQTT is also a target in its own right. It holds the Docker socket, which is equivalent to root on the host, and accepts commands over MQTT. Hardening the updater matters as much as being careful about what it installs.

## Scope

- **In scope:** OCI images updated by pulling, both plain Compose projects and Portainer stacks, and the Updates2MQTT image itself.
- **Later:** other package types, primarily `.deb` packages, under the `apt` roadmap item. The same policy model should carry over.
- **Out of scope for now:** locally built images (`git pull` and rebuild). The build inputs are the user's own repository, and that's a different trust model. Revisit once the image work is done.

## Threat model

| Threat | Example | Main controls |
|---|---|---|
| Compromised upstream release | A maintainer account or CI pipeline publishes a malicious version | Cooldown, signature checks, scanning |
| Tag re-pointed to a new digest | A versioned tag such as `2.0.18` is re-pushed with different content | Digest pinning, tag-mutation detection |
| Registry or CDN compromise | A different image is served for a tag | Digest pinning, signature checks |
| Typosquatting | A look-alike image name in a compose file | Signature identity checks. Mostly outside Updates2MQTT's control, so covered by documentation |
| Install of a different image than the one checked | The tag moves between the checks and the pull | Digest pinning |
| Unauthorised update commands | Anyone with publish rights on the MQTT broker triggers pulls and restarts | Broker ACLs and TLS, documentation |
| Compromise of Updates2MQTT itself | A malicious dependency, GitHub Action or Updates2MQTT release | Own supply chain hygiene, cooldown on self-update |
| Bad update with no way back | A legitimate but broken or malicious release has been installed | Rollback image, audit log |

## Design

### Install exactly the image that was approved

This is the foundation that every other control relies on.

- **Today:** an update pulls the container's image *tag* (`DockerProvider.fetch()`). The install command from Home Assistant is a fixed `docker|<name>|install` payload with no version or digest. If the tag moves between the checks and the install, the pull fetches whatever is newest, which is exactly what a cooldown or scan exists to prevent.
- **Change:** pull the approved digest (`repo@sha256:...`) with the container's platform, then tag the image locally with the original tag, so `docker compose up` and Portainer redeploys keep working unchanged.
    - Portainer stacks already redeploy with `pullImage: False` after Updates2MQTT has pulled, so `fetch()` is the only place that changes.
    - Pull by the image index digest where there is one, so multi-platform images still pick the right platform.
- **Tag-mutation detection:**
    - Record which digest each *versioned* tag had when first seen.
    - If a versioned tag later points to a different digest, publish a `tag_moved` attribute and log it, and treat the new digest as brand new for cooldown purposes.
    - This is informational, not a block. Some publishers, including Docker Official Images, routinely rebuild version tags for base image fixes.
    - Floating tags such as `latest`, `stable` or `nightly` are expected to move and are not flagged.

### Release time

A cooldown is only as good as its clock.

- **The image's own timestamp can't be trusted.** The `org.opencontainers.image.created` label and the image config's `created` time are set by whoever built the image. Reproducible builds often set them to 1970, which would pass any cooldown.
- **Sources, most trusted first:**
    1. **First seen:** when Updates2MQTT first saw the digest. This is the default basis for the cooldown.
    2. **Registry push time,** where the registry exposes one, such as Docker Hub's `last_pushed` or the GitHub Packages API for GHCR.
    3. **Release publication time** from the source repository, such as GitHub `published_at`, which `github_enrich` already fetches.
    4. **Image `created` time.** Used only for display.
- **Rule:** other sources may make a cooldown *longer*, never shorter.
    - For example, a digest first seen today but published a month ago still starts its cooldown today.
    - Exceptions, which are evidence-based (see below), are the only way to shorten it.
- **Persistence.**
    - First-seen times must survive restarts and Updates2MQTT's own updates.
    - Today nothing does: the HTTP cache lives inside the container unless a volume is mapped.
    - Store a small state file under `/app/conf`, which is always mounted, keyed by digest.
    - Don't use retained MQTT messages for this: anyone who can publish to the broker could backdate them.
    - If the state file is lost, the effect is safe: every digest gets a fresh cooldown.

### Cooldown

- **Policy:** a duration in hours or days since release, measured from the release time above, before an update is offered as eligible.
- **Settings:**
    - a global default
    - per-container overrides with the `updates2mqtt.cooldown` label or `UPD2MQTT_COOLDOWN` env var
    - `0` turns it off for a container
- **Defaults:**
    - Enforce cooldown for containers on the `Auto` update policy.
    - For `Passive` containers, still show the newest version, but mark it as in cooldown, so a person can decide.
    - Proposed starting default: 3 days, to be checked against data from the observe-only phase.
- **Updates2MQTT's own self-update** follows the same policy.
- **Breaking change.** Document it clearly:
    - Auto-updated containers will no longer update as soon as a release appears, unless the defaults are overridden.
    - Users may want stricter settings than the defaults.
- **Exceptions** shorten or skip a cooldown when there is evidence a release is a fix:
    - It's signed by the expected identity (see trust levels).
    - It has fewer known CVEs than the installed image, and adds no new critical or high ones (see scanning).
    - Each exception is recorded in the entity attributes, so it's visible why an update came early.
- **Forcing an update during cooldown** is at the user's discretion, typically for a critical fix.
    - Home Assistant's MQTT update entity sends a fixed install payload and, as far as we know, has no "install specific version" support. *To verify.*
    - Options:
        - a separate MQTT `button` entity, "Install now, ignoring cooldown"
        - an install command payload that carries the digest, for scripts and automations
    - Home Assistant's own *Skip version* already covers the opposite case.
- **What Home Assistant shows:**
    - `latest_version` is the newest *eligible* version, so the update entity only offers what the policy allows. For `Passive` containers it is the newest version, marked as in cooldown.
    - Proposed attributes:
        - `cooldown_policy`
        - `cooldown_until`
        - `release_time` and `release_time_source`
        - `held_versions`, listing each held version with its digest and eligible-from time
        - `cooldown_exception`
    - Watch for Home Assistant changes that would support this better, or propose them.

### Trust levels

Instead of tuning a cooldown per container, each image gets a trust level, and the cooldown is set once per level.

- **Assigned from evidence:**
    - **High:** the image's signature or provenance attestation verifies against the expected identity, such as a known GitHub repository and workflow, or a publisher such as Docker Official Images.
    - **Standard:** no signature, but a stable publisher and history.
    - **Low:** the signer changed or a signature disappeared, a versioned tag was re-pushed, or the image is new to this host.
- **Overridable** per container with an `updates2mqtt.trust_level` label.
- **Where the evidence comes from:**
    - Look for packages that publish their own cooldowns or trusted quality metadata.
    - Use the base image's information where the image itself has little, for example for signatures or SBOMs on the base layer.

### Signature and provenance verification

This is the strongest signal available, and it wasn't in the first draft.

- Many images now carry cosign signatures, or GitHub or SLSA provenance attestations, as OCI artifacts. They can be found through the OCI referrers API. The [OCI client](rfc0001-oci_client.md) already has `list_referrers`.
- Verify the signature, and compare the signer identity with the identity recorded when the image was first installed. A changed or missing signer lowers trust.
- Results go into the entity attributes and feed the trust level.
- Verification needs Sigstore's trust root and transparency log checks.
    - Prefer a maintained Python library, such as `sigstore-python`, over custom cryptography.
    - Check its dependency weight against the Docker image size first.

### Image scanning

- **Sources, in order of preference:**
    1. **Attestations attached to the image:** SBOMs and VEX documents published with it. These are free to read and tied to the digest.
    2. **Public scan results for the digest,** where available, such as Docker Scout for some images or Chainguard's images. Few registries publish these, so this is a bonus, not something to rely on.
    3. **A scanning service the user configures,** such as a Trivy server or Grype.
        - A vulnerability database is a few hundred MB and needs regular refreshes, so it runs as a separate service, not inside Updates2MQTT.
        - Document a Compose example.
- **Results go into the image attributes:**
    - counts by severity for the installed and new images
    - new critical or high CVEs
    - the scan source and when it ran
- **Uses:**
    - **Clearing:** after cooldown, a scan with no new critical or high CVEs clears the image for update. A failed scan holds it and says why.
    - **Exception:** before cooldown ends, a new image with fewer CVEs than the installed one, and no new critical or high ones, can skip the rest of the cooldown.

### Rollback and audit

- **Keep the previous image** until the new one has been running for at least the cooldown period, so a bad update can be undone quickly.
    - This changes how `remove_old_image` works: removal is deferred rather than immediate.
- **Rollback command:** a `docker|<name>|rollback` MQTT command that re-tags and redeploys the previous digest.
- **Audit log:** an append-only log of every update:
    - container, old and new digest, and time
    - the command or policy that triggered it, and any cooldown exception
    - kept in `/app/conf`, which helps incident response

### Hardening Updates2MQTT itself

- **Already in place:**
    - uv `exclude-newer = "7 days"`
    - Dependabot cooldowns
    - build provenance attestations on the Docker image
    - Grype scans of the published image
    - SHA-pinned third-party actions in the image scan workflow
- **To do:**
    - Pin all GitHub Actions by commit SHA, including first-party ones such as `actions/checkout@v7` and `astral-sh/setup-uv@v7`.
    - Review Dependabot auto-merge now that cooldowns are in place. Limit it to patch updates, or require CI and a cooldown.
    - Sign the Docker image (cosign keyless), in addition to the provenance attestation, so users and Updates2MQTT itself can verify it.
    - Publish an SBOM attestation with the image.
- **Security guidance for users:**
    - MQTT broker ACLs, so only Home Assistant can publish to Updates2MQTT's command topics. Also TLS.
    - Running behind a Docker socket proxy that allows only the API calls Updates2MQTT needs.
    - Mounting only the compose directories that are needed, read-only where possible.

## Rollout phases

Each phase can ship and be useful on its own, and each builds the foundation the next one needs.

| Phase | Delivers | Behaviour change | Why this order |
|---|---|---|---|
| **0. Foundations** | Digest-pinned installs. Persistent first-seen times. Tag-mutation warnings. SHA-pinned Actions. MQTT ACL and socket proxy docs | None visible, except the new warning attribute | Without digest pinning, every later control can be bypassed by the tag moving. Valuable even if nothing else ships |
| **1. Cooldown, observe only** | Cooldown settings and release-time sources. Attributes showing which updates *would* be held and why | None: attributes only | Shows users the effect before enforcement, and gives real data for choosing the default duration |
| **2. Cooldown enforced** | Enforcement for `Auto`. Marking for `Passive`. Force-install route. Deferred old-image removal and rollback. Audit log. Cooldown on self-update | **Breaking:** auto-updates wait for the cooldown | The main protection. Rollback ships with it so being strict carries less risk |
| **3. Signatures and trust levels** | Signature and provenance verification through OCI referrers. Trust levels with per-level cooldowns. Signing and SBOM for Updates2MQTT's own image | Signed images may update sooner, and changed signers are held | Gives evidence-based exceptions, which make strict cooldowns livable |
| **4. Scanning** | Attestation SBOM/VEX reading, optional Trivy or Grype service, scan attributes, scan-based clearing and exceptions | Scans can hold or clear updates | Most moving parts and external dependencies, so built last on a settled policy model |

- **1.18.0 delivered phases 0 and 1:**
    - digest-pinned installs
    - the persistent release history in `conf/release_history.json`, keeping the latest 50 digests and versioned tags per image
    - `tag_moved` and `cooldown` attributes
    - the `docker.cooldown` setting, defaulting to `3d`, with the `updates2mqtt.cooldown` label and `UPD2MQTT_COOLDOWN` env var
    - SHA-pinned GitHub Actions
    - documentation of MQTT ACLs and Docker API access
- **Not yet done:** registry push time as a release-time source. 1.18.0 uses first sighting, plus GitHub release `published_at` when that's later.
- Phases 0 and 1 need only one or two new settings, which can go into the current configuration system without waiting for [RFC 0003](rfc0003-configuration.md).
- If RFC 0003 lands first, the cooldown and trust settings should be designed in its model from the start.

## Success criteria

- No install of a digest other than the one the policy approved. A test registry fixture re-points a tag between the checks and the install.
- No auto-install of a digest younger than its cooldown, unless a recorded exception applies.
- A lost state file never shortens a cooldown.
- Every held, excepted, forced or rolled-back update is visible in Home Assistant attributes and the audit log.

## Open questions

- Default cooldown duration, and whether `Passive` containers should have a separate one. Decide with data from phase 1.
- Should a held update be hidden from Home Assistant entirely, or shown as in cooldown? This RFC proposes hiding it for `Auto` and showing it for `Passive`.
- Which signer identities can be inferred automatically, for example from a GitHub source repository label, and which have to be configured?
- Dependency cost of Sigstore verification in the Docker image.
- Whether the rollback command should be exposed as a Home Assistant button entity, or only as an MQTT command.
