import asyncio
import logging
from .tenda import TendaBeliPlug, TendaBeliServer

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity_registry import async_get
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, HUB

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None) -> None:

    async def remove_entity_if_exist(unique_id):
        try:
            entity_registry = async_get(hass)
            entity_id = entity_registry.async_get_entity_id("switch", DOMAIN, unique_id)
            if not entity_id == None:
                entity_registry.async_remove(entity_id)
                _LOGGER.debug(f"Succesfully removed {entity_id}")
        except Exception as err:
                _LOGGER.debug(f"Unexpected error during entity removal, {err=}, {type(err)=}")
                raise
    
    async def process_callback(sn: str, msg: str):
        if msg == "setup":
            try:
                plug = TendaBeliSwitch(hass.data[DOMAIN][HUB], sn)
                await remove_entity_if_exist(f"tbp_switch_{sn}")
                async_add_entities([plug], True)
                _LOGGER.debug(f"Succesfully added switch entity for {sn}")
                
            except Exception as err:
                _LOGGER.debug(f"Unexpected error during setup, {err=}, {type(err)=}")
                raise
        elif msg == "discard":
            await remove_entity_if_exist(f"tbp_switch_{sn}")
    
    try:
        hub: TendaBeliServer = hass.data[DOMAIN][HUB]
        hub.register_setup_callback(process_callback)
    except Exception as err:
        _LOGGER.debug(f"Unexpected {err=}, {type(err)=}")
        raise

class TendaBeliSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hub, sn):
        self._state = False
        self._available = False
        self._sn: str | None = sn
        self._device_class = "outlet"
        self._hub: TendaBeliServer = hub
        self._plug: TendaBeliPlug = self._hub.get_TBP(self._sn)

    async def async_added_to_hass(self):
        self._hub.register_operational_callback(self.process_callback, self._sn)

    async def async_will_remove_from_hass(self):
        self._hub.register_operational_callback(self.process_callback, self._sn)

    async def process_callback(self):
        await self.async_update()
        self.async_write_ha_state()
    
    @property
    def name(self):
        return  f"tbp_switch_{self._sn[-4:]}"

    @property
    def should_poll(self):
        return False
    
    @property
    def unique_id(self) -> str | None:
        return f"tbp_switch_{self._sn}"

    @property
    def device_class(self):
        return self._device_class


    @property
    def is_on(self) -> bool:
        return self._state

    @property
    def available(self) -> bool:
        return self._available 

    async def async_update(self):
        #self._plug = self._hub.get_TBP(self._sn)
        self._available = self._plug.alive
        self._state =  self._plug.is_on

    async def async_turn_on(self, **kwargs)-> None:
        self._plug.send_toggle_request()

    async def async_turn_off(self, **kwargs)-> None:
       self._plug.send_toggle_request()

    async def async_toggle(self, **kwargs):
        self._plug.send_toggle_request()
    
