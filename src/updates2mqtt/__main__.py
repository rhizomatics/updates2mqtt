"""Detect component version change availability and broadcast on MQTT topic, suitable for HomeAssistant autodetect"""

if __name__ == "__main__":
    import asyncio

    from .app import App

    app = App()
    asyncio.run(app.run())
