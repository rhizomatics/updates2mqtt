"""Detect component version change availability and broadcast on MQTT topic, suitable for HomeAssistant autodetect"""

if __name__ == "__main__":
    from updates2mqtt.app import run

    run()
