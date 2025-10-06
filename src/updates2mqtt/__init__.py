"""Detect component version change availability and broadcast on MQTT topic, suitable for HomeAssistant autodetect"""

from usingversion import getattr_with_version

__getattr__ = getattr_with_version("updates2mqtt", __file__, __name__)
