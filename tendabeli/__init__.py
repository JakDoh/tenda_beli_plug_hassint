from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.components.network import async_get_source_ip
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.core import Context
from homeassistant.const import EVENT_HOMEASSISTANT_STOP

from .const import DOMAIN, HUB
from .tenda import TendaBeliServer

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ['switch', 'sensor']

async def async_setup(hass: HomeAssistant, config) -> bool:

    if config.get(DOMAIN) is not None:
        hass.data[DOMAIN] = {}
        hub = TendaBeli(hass)
        await hub.start()
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, hub.stop)

        for platform in PLATFORMS:
            _LOGGER.debug(f"Starting {platform} platform")
            hass.async_create_task(async_load_platform(hass, platform, DOMAIN, None, config))

    return True


class TendaBeli:
    def __init__(self, hass):
        self.hass = hass
        self.hub = hass.data[DOMAIN][HUB] = TendaBeliServer()
        self.context = Context()

    async def start(self):
        haip :str = await async_get_source_ip(self.hass)
        await self.hub.listen(haip)

    def stop(self, event):
        self.hub.stop()

    