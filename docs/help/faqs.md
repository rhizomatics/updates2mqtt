---
tags:
  - faq
  - support
  - help
title: Frequently Asked Questions
description: Answers to common Updates2MQTT support queries
---
# Frequently Asked Questions

## Scanning

**Q**: How do I get Updates2MQTT to update Home Assistant every hour?

**A**: Set `scan_interval` in the Updates2MQTT config file to `3600`. This is the number of seconds Updates2MQTT sleeps between scans, and defaults to `10800` (3 hours).

```yaml title="conf/config.yaml"
scan_interval: 3600 # check for new versions every hour
```

Restart the container afterwards, for example `docker compose restart updates2mqtt`, to pick up the change. If you are running without a config file, see [Using a Config File](../configuration/using_a_config_file.md) for how to create one.

There's nothing to change in Home Assistant. It doesn't poll Updates2MQTT; the MQTT Update entities change as soon as Updates2MQTT publishes the results of each scan. The interval is measured from the end of one scan to the start of the next, so scans won't land exactly on the hour. A restart also triggers a fresh scan straight away.

Before going much lower than an hour, take a look at [Remote API Usage](../configuration/remote_api_usage.md#api-throttling), since registries like Docker Hub limit how many requests can be made per hour, especially when you have lots of containers.
