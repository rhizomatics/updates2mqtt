import asyncio

from updates2mqtt.app import App

app = App()
asyncio.run(app.run())
