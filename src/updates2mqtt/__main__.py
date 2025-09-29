"""Detect component version change availability and broadcast on MQTT topic, suitable for HomeAssistant autodetect"""


def run() -> None:
    import asyncio

    from .app import App

    app = App()
    asyncio.run(app.run())


if __name__ == "__main__":
    run()
