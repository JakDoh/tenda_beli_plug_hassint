import logging
from typing import Optional, Any

from .tenda import TendaBeliPlug, TendaBeliServer, HubState

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC

from .const import (
    DOMAIN,
    HUB,
    MANUFACTURER,
    MODEL_PLUG,
    SETUP_DONE_KEYS,
    ERROR_MESSAGES
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry( 
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback) -> None:
    """Set up button platform from a config entry."""
    hub: TendaBeliServer = hass.data[DOMAIN][HUB]

    if SETUP_DONE_KEYS["button"] not in hass.data[DOMAIN]:
        hass.data[DOMAIN][SETUP_DONE_KEYS["button"]] = set()

    async def process_callback(sn: str, msg: str) -> None:
        if msg == "setup" and sn not in hass.data[DOMAIN][SETUP_DONE_KEYS["button"]]:
            _LOGGER.debug(f"Button setup triggered for SN: {sn}")
            hass.data[DOMAIN][SETUP_DONE_KEYS["button"]].add(sn)
            entities = [
                TendaBeliPowerRefresh(hub, sn),
                TendaBeliEnergyRefresh(hub, sn),
                TendaBeliDisconnect(hub, sn)
            ]
            async_add_entities(entities)

    if not hass.data[DOMAIN].get("hub_buttons_created"):
        _LOGGER.info("Creating Tenda Beli Hub button entities.")
        hass.data[DOMAIN]["hub_buttons_created"] = True
        hub_buttons = [
            TendaBeliHubStart(hub), TendaBeliHubStop(hub),
            TendaBeliHubRestart(hub), TendaBeliHubStatus(hub)
        ]
        async_add_entities(hub_buttons)

    await hub.register_setup_callback(process_callback)

class TendaBeliButton(ButtonEntity):
    """Base button entity for Tenda Beli integration."""
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: TendaBeliServer, sn: Optional[str] = None) -> None:
        """Initialize the base button."""
        self._hub: TendaBeliServer = hub
        self._sn: Optional[str] = sn
        self._plug: Optional[TendaBeliPlug] = self._hub.get_plug_by_serial_number(sn) if sn else None
        
        self._attr_available = self._plug.alive if self._plug else False
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        if sn:
            self._attr_device_info = DeviceInfo(
                #config_entry_id=self._hub.config_entry_id,
                identifiers={(DOMAIN, sn)},
                name=f"Tenda Plug {sn[-4:]}",
                manufacturer=MANUFACTURER,
                model=self._plug.model if self._plug and self._plug.model else MODEL_PLUG,
                sw_version=self._plug.firmware if self._plug and self._plug.firmware else None,
                connections={(CONNECTION_NETWORK_MAC, self._plug._mac_address)} if self._plug and self._plug._mac_address else set(),
                serial_number=sn
            )
        else: # Pro Hub tlačítka
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "hub")},
                name="Tenda Beli Plug Hub",
                manufacturer="JakDoh",
                model="Smart Plug Hub"
            )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._attr_available

    async def async_added_to_hass(self) -> None:
        """Register callbacks when added to hass."""
        if self._sn:
            self._hub.register_operational_callback(self.process_callback, self._sn)
            await self.process_callback()
        else:
            self._hub.register_hub_callback(self.process_hub_callback)

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks when removed from hass."""
        if self._sn:
            self._hub.remove_operational_callback(self.process_callback, self._sn)
        else:
            self._hub.remove_hub_callback(self.process_hub_callback)

    async def process_callback(self) -> None:
        """Handle updates from the hub for a specific plug."""
        self._plug = self._hub.get_plug_by_serial_number(self._sn)
        self._attr_available = self._plug.alive if self._plug else False
        self.async_write_ha_state()

    async def process_hub_callback(self, state: HubState, stats: Any) -> None:
        self.async_write_ha_state()

# ... zbytek souboru button.py zůstává stejný ...
class TendaBeliPowerRefresh(TendaBeliButton):
    """Button to refresh power measurement."""
    _attr_icon = "mdi:flash-outline"
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_name = "Power Refresh"
        self._attr_unique_id = f"tbp_powref_{sn}"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Handle button press - request power refresh."""
        self._plug = self._hub.get_plug_by_serial_number(self._sn)
        if self._plug:
            _LOGGER.debug(f"Power refresh triggered for {self._sn}")
            self._plug.send_power_request()
        else:
            _LOGGER.warning(f"Cannot refresh power: plug {self._sn} not found")

class TendaBeliEnergyRefresh(TendaBeliButton):
    """Button to refresh energy consumption."""
    _attr_icon = "mdi:lightning-bolt-outline"
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_name = "Energy Refresh"
        self._attr_unique_id = f"tbp_enref_{sn}"
        self._attr_entity_category = EntityCategory.CONFIG
        
    async def async_press(self) -> None:
        """Handle button press - request energy refresh."""
        self._plug = self._hub.get_plug_by_serial_number(self._sn)
        if self._plug:
            _LOGGER.debug(f"Energy refresh triggered for {self._sn}")
            self._plug.send_energy_request()
        else:
            _LOGGER.warning(f"Cannot refresh energy: plug {self._sn} not found")

class TendaBeliDisconnect(TendaBeliButton):
    """Button to force disconnect a plug for reconnection."""
    _attr_icon = "mdi:power-plug-off-outline"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_name = "Disconnect"
        self._attr_unique_id = f"tbp_disconnect_{sn}"
        self._attr_entity_category = EntityCategory.CONFIG
        
    async def async_press(self) -> None:
        """Handle button press - disconnect the plug."""
        _LOGGER.info(f"Disconnecting plug {self._sn}")
        await self._hub.remove_plug(self._sn)

# Hub Management Buttons
class TendaBeliHubStart(TendaBeliButton):
    """Button to start the hub."""
    _attr_icon = "mdi:play"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, hub: TendaBeliServer) -> None:
        super().__init__(hub)
        self._attr_name = "Start Hub"
        self._attr_unique_id = "tbh_start"
        self._attr_entity_category = EntityCategory.CONFIG
        
    @property
    def available(self) -> bool:
        """Hub start button is available when hub is stopped."""
        return self._hub.state in [HubState.STOPPED, HubState.ERROR]
        
    async def async_press(self) -> None:
        """Handle button press - start the hub."""
        _LOGGER.info("Hub start requested via button")
        if self._hub._ha_ip:
            if self._hub.state == HubState.STOPPED:
                await self._hub.start(self._hub._ha_ip)
            else:
                await self._hub.restart()
        else:
            _LOGGER.error("Cannot start hub: no IP address configured")

class TendaBeliHubStop(TendaBeliButton):
    """Button to stop the hub."""
    _attr_icon = "mdi:stop"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, hub: TendaBeliServer) -> None:
        super().__init__(hub)
        self._attr_name = "Stop Hub"
        self._attr_unique_id = "tbh_stop"
        self._attr_entity_category = EntityCategory.CONFIG
        
    @property
    def available(self) -> bool:
        """Hub stop button is available when hub is running."""
        return self._hub.state in [HubState.RUNNING, HubState.STARTING]
        
    async def async_press(self) -> None:
        """Handle button press - stop the hub."""
        _LOGGER.info("Hub stop requested via button")
        await self._hub.stop()

class TendaBeliHubRestart(TendaBeliButton):
    """Button to restart the hub."""
    _attr_icon = "mdi:restart"
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, hub: TendaBeliServer) -> None:
        super().__init__(hub)
        self._attr_name = "Restart Hub"
        self._attr_unique_id = "tbh_restart"
        self._attr_entity_category = EntityCategory.CONFIG
        
    @property
    def available(self) -> bool:
        """Hub restart button is available when hub is not stopped."""
        return self._hub.state != HubState.STOPPED
        
    async def async_press(self) -> None:
        """Handle button press - restart the hub."""
        _LOGGER.info("Hub restart requested via button")
        await self._hub.restart()

class TendaBeliHubStatus(TendaBeliButton):
    """Button to refresh hub status and trigger diagnostics."""
    _attr_icon = "mdi:information-outline"
    _attr_device_class = ButtonDeviceClass.UPDATE

    def __init__(self, hub: TendaBeliServer) -> None:
        super().__init__(hub)
        self._attr_name = "Hub Status"
        self._attr_unique_id = "tbh_status"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_available = True
        
    async def async_press(self) -> None:
        _LOGGER.info("Hub status refresh requested via button.")
        await self._hub.force_hub_update()
        hub_info = self._hub.get_hub_info()
        _LOGGER.info("--- Tenda Beli Hub Status ---")
        _LOGGER.info(f"  State: {hub_info['state']}")
        stats = hub_info['statistics']
        _LOGGER.info(f"  Uptime: {stats.get('uptime', 0):.1f} seconds")
        _LOGGER.info(f"  Connections: {stats.get('current_connections', 0)} current / {stats.get('total_connections', 0)} total")
        _LOGGER.info(f"  Packets Received: {stats.get('packets_received', 0)}")
        _LOGGER.info(f"  Errors: {stats.get('errors', 0)}")
        if stats.get('last_error'):
            _LOGGER.warning(f"  Last Error: {stats.get('last_error')}")
        
        plugs = hub_info.get('plugs', [])
        if plugs:
            _LOGGER.info("  Connected Plugs:")
            for plug_info in plugs:
                _LOGGER.info(f"    - SN: {plug_info['sn']}, Status: {plug_info['status']}, Alive: {plug_info['alive']}")
        else:
            _LOGGER.info("  No plugs currently connected.")
        _LOGGER.info("-----------------------------")