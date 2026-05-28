"""
Switch platform for Tenda Beli Smart Plug Integration.

This module provides Home Assistant switch entities for controlling Tenda SP9/SP3 smart plugs,
including power state management and device attribute reporting.

"""
import asyncio
import logging
from typing import Any, Dict, Optional

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    HUB,
    MANUFACTURER,
    MODEL_PLUG,
    SETUP_DONE_KEYS,
    ERROR_MESSAGES
)
from .tenda import TendaBeliPlug, TendaBeliServer

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry( 
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up switch platform from a config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry for this integration
        async_add_entities: Callback to add new entities
    """
    hub: TendaBeliServer = hass.data[DOMAIN][HUB]
    setup_done_key = SETUP_DONE_KEYS["switch"]

    # Initialize setup tracking
    if setup_done_key not in hass.data[DOMAIN]:
        hass.data[DOMAIN][setup_done_key] = set()

    async def process_callback(serial_number: str, message: str) -> None:
        """
        Process callback for switch setup and discard operations.
        
        Args:
            serial_number: Plug serial number
            message: Operation type ('setup' or 'discard')
        """
        if message == "setup" and serial_number not in hass.data[DOMAIN][setup_done_key]:
            _LOGGER.debug("Switch setup triggered for serial number: %s", serial_number)
            hass.data[DOMAIN][setup_done_key].add(serial_number)
            
            plug_switch = TendaBeliSwitch(hub, serial_number)
            async_add_entities([plug_switch])

    await hub.register_setup_callback(process_callback)

class TendaBeliSwitch(SwitchEntity):
    """
    Switch entity representing a Tenda Beli smart plug.
    
    This entity provides power control functionality and reports device
    status, power consumption, and other attributes.
    """
    
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: TendaBeliServer, serial_number: str) -> None:
        """
        Initialize the switch entity.
        
        Args:
            hub: Reference to the hub server
            serial_number: Plug serial number
        """
        self._hub = hub
        self._serial_number = serial_number
        self._plug: Optional[TendaBeliPlug] = self._hub.get_plug_by_serial_number(serial_number)

        self._state = self._plug.is_on if self._plug else False
        self._available = self._plug.alive if self._plug else False
        
        self._attr_name = "Switch"
        self._attr_unique_id = f"tbp_switch_{serial_number}"
        self._attr_device_class = SwitchDeviceClass.OUTLET
        
        # Device information for Home Assistant device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            name=f"Tenda Plug {serial_number[-4:]}",
            manufacturer=MANUFACTURER,
            model=self._plug.model if self._plug and self._plug.model else MODEL_PLUG,
            sw_version=self._plug.firmware if self._plug and self._plug.firmware else "unknown",
            connections=(
                {(CONNECTION_NETWORK_MAC, self._plug.mac_address)} 
                if self._plug and self._plug.mac_address 
                else set()
            ),
            serial_number=serial_number
        )

    async def async_added_to_hass(self) -> None:
        """Register operational callback when added to Home Assistant."""
        self._hub.register_operational_callback(
            self.process_callback, 
            self._serial_number
        )
        await self.process_callback()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister operational callback before removal."""
        self._hub.remove_operational_callback(
            self.process_callback, 
            self._serial_number
        )

    async def process_callback(self) -> None:
        """Handle updates from the hub and refresh entity state."""
        await self.async_update()
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        return self._state

    @property
    def available(self) -> bool:
        """Return True if the switch is available."""
        return self._available 

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes for the switch."""
        attributes = {}
        self._plug = self._hub.get_plug_by_serial_number(self._serial_number)
        
        if self._plug:
            power_value, _ = self._plug.power
            energy_value, _ = self._plug.energy
            
            attributes.update({
                "current_power": power_value if power_value != "unknown" else None,
                "total_energy": energy_value if energy_value != "unknown" else None,
                "ip_address": self._plug.ip_address,
                "mac_address": self._plug.mac_address,
                "status": self._plug.status.value
            })
        
        return attributes

    async def async_update(self) -> None:
        """Update switch state from plug data."""
        self._plug = self._hub.get_plug_by_serial_number(self._serial_number)
        
        if self._plug:
            self._available = self._plug.alive
            old_state = self._state
            self._state = self._plug.is_on
            
            if old_state != self._state:
                _LOGGER.debug(
                    "Switch %s state changed: %s -> %s", 
                    self._serial_number, 
                    old_state, 
                    self._state
                )
        else:
            self._available = False
            _LOGGER.warning(
                "Plug %s not found during update", 
                self._serial_number
            )

    async def _send_toggle_command(self) -> bool:
        """
        Send toggle command with comprehensive error handling.
        
        Returns:
            True if command sent successfully, False otherwise
        """
        self._plug = self._hub.get_plug_by_serial_number(self._serial_number)
        
        if not self._plug:
            _LOGGER.error(
                "Cannot toggle %s: plug not found", 
                self._serial_number
            )
            return False
        
        if not self.available:
            _LOGGER.error(
                "Cannot toggle %s: plug not available", 
                self._serial_number
            )
            return False
        
        try:
            self._plug.send_toggle_request()
            _LOGGER.debug("Toggle command sent to %s", self._serial_number)
            
            # Brief delay then request power update
            await asyncio.sleep(0.5)
            self._plug.send_power_request()
            return True
            
        except Exception as err:
            _LOGGER.error(
                "Failed to send toggle command to %s: %s", 
                self._serial_number, 
                err
            )
            return False

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the switch on."""
        if not self._state:
            success = await self._send_toggle_command()
            if not success:
                _LOGGER.warning("Failed to turn on %s", self._serial_number)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the switch off."""
        if self._state:
            success = await self._send_toggle_command()
            if not success:
                _LOGGER.warning("Failed to turn off %s", self._serial_number)

    async def async_toggle(self, **kwargs) -> None:
        """Toggle the switch state."""
        success = await self._send_toggle_command()
        if not success:
            _LOGGER.warning("Failed to toggle %s", self._serial_number)

    @property
    def icon(self) -> Optional[str]:
        """Return the appropriate icon for the switch."""
        if not self.available:
            return "mdi:power-socket-off-outline"
        elif self.is_on:
            return "mdi:power-socket"
        else:
            return "mdi:power-socket-off"