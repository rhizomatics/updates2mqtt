# RFC 0002 Cyber Security Improvements

## Motivation

The pace of cyber attacks has increased hugely in 2026 with the assistance of AI agents, and supply chain attacks are more common and trickier to deal with.

All package managers are moving to support a cooldown, to minimize the window in which a supply chain attack can be distributed.

For updating packages this is made more complicated because reacting quickly to updated software can itself be an attack vector, however being able to quickly apply remediated packages is the best defence. Double-edged sword.

## Design

All of these changes will apply immediately to OCI images, although in future will apply more widely to other packages, primarily `.deb` linux packages.

### Cooldown

- Document this as a breaking change, notifying people they won't get updates immediately any longer unless they override defaults, and may want to make them stricter
- Cooldown policy will be expressed in hours/days and exception handling
  - Hours/days since release before update will be applied
  - Exception policy for releases that fix more CVEs than solve
- Attributes, in a HA compatible manner, will be updated to hold the cooldown policy, and also indicate all versions that are hidden behind the policy
- Watch for Home Assistant changes, or propose new ones, that better support cooldown handling
- Where possible, allow user discretion to force an update during cooldown, usually because there is a critical fix required
- Explore where packages have their own cooldowns, or there are trusted metadata for package quality
- Explore use of `trust levels` where rather than managing cooldown at package level, each package has a default and overridable trust level, and cooldown policy set once per level
- Explore where base image info can be used, for example where there is insufficient data on the docker image itself

### Image Scanning
- Ideally, reuse public trusted scan results for a container hash
- Alternatively, allow a service to be configured
- Scan results go into image attributes
- Scan can be used to clear an image for update, after cooldown passed
- Scan can be used to compute an exception to cleardown
  - New image has fewer CVEs than current image and not introduced new critical or high ones