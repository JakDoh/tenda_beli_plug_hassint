"""
Sensor platform for Tenda Beli Smart Plug Integration.

This module provides sensor entities for monitoring power consumption, energy usage,
device uptime, and hub statistics for Tenda SP9/SP3 smart plugs.

"""
import logging
from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    HUB,
    MANUFACTURER,
    MODEL_HUB,
    MODEL_PLUG,
    SETUP_DONE_KEYS,
    ENTITY_NAME_PATTERNS,
    HUB_ENTITY_PATTERNS
)
from .tenda import TendaBeliPlug, TendaBeliServer, HubState, HubStatistics

_LOGGER = logging.getLogger(__name__)


def format_duration_in_seconds(seconds: Optional[int]) -> str:
    """
    Format a duration in seconds into a human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string
    """
    if seconds is None or not isinstance(seconds, (int, float)) or seconds < 0:
        return "unknown"

    seconds = int(seconds)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    
    return f"{secs}s"


async def async_setup_entry( 
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up sensor platform from a config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry for this integration
        async_add_entities: Callback to add new entities
    """
    hub: TendaBeliServer = hass.data[DOMAIN][HUB]
    setup_done_key = SETUP_DONE_KEYS["sensor"]
    
    # Initialize setup tracking for this platform
    if setup_done_key not in hass.data[DOMAIN]:
        hass.data[DOMAIN][setup_done_key] = set()

    async def process_callback(serial_number: str, message: str) -> None:
        """
        Process callback for sensor setup and discard operations.
        
        Args:
            serial_number: Plug serial number  
            message: Operation type ('setup' or 'discard')
        """
        if message == "setup" and serial_number not in hass.data[DOMAIN][setup_done_key]:
            _LOGGER.debug("Sensor setup triggered for serial number: %s", serial_number)
            hass.data[DOMAIN][setup_done_key].add(serial_number)
            
            # Create all sensor entities for this plug
            plug_sensors = [
                TendaBeliPower(hub, serial_number),
                TendaBeliEnergy(hub, serial_number), 
                TendaBeliUpTime(hub, serial_number),
                TendaBeliOnTime(hub, serial_number),
                TendaBeliPlugStatus(hub, serial_number),
                TendaBeliLastSeen(hub, serial_number)
            ]
            async_add_entities(plug_sensors)

    # Create hub sensors if not already created
    if not hass.data[DOMAIN].get("hub_sensors_created"):
        _LOGGER.info("Creating Tenda Beli Hub sensor entities")
        hass.data[DOMAIN]["hub_sensors_created"] = True
        
        hub_sensors = [
            TendaBeliHubState(hub),
            TendaBeliHubUptime(hub),
            TendaBeliHubConnections(hub),
            TendaBeliHubPackets(hub),
            TendaBeliHubErrors(hub)
        ]
        async_add_entities(hub_sensors)
    
    await hub.register_setup_callback(process_callback)


class TendaBeliSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: TendaBeliServer, sn: Optional[str] = None) -> None:
        self._hub = hub
        self._sn = sn
        self._plug: Optional[TendaBeliPlug] = self._hub.get_plug_by_sn(sn) if sn else None
        self._attr_available = self._plug.alive if self._plug else False

        if sn:
            self._attr_device_info = DeviceInfo(
                #config_entry_id=self._hub.config_entry_id,
                identifiers={(DOMAIN, sn)},
                name=f"Tenda Plug {sn[-4:]}",
                manufacturer=MANUFACTURER,
                model=self._plug.model if self._plug and self._plug.model else MODEL_PLUG,
                sw_version=self._plug.firmware if self._plug and self._plug.firmware else "unknown",
                connections={(CONNECTION_NETWORK_MAC, self._plug._mac_address)} if self._plug and self._plug._mac_address else set(),
                serial_number=sn
            )
        else: # Pro Hub senzory
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, "hub")},
                name="Tenda Beli Plug Hub",
                manufacturer="JakDoh",
                model="Smart Plug Hub"
            )

    async def async_added_to_hass(self) -> None:
        """Handle being added to hass and perform initial update."""
        if self._sn:
            # For plug entities, register the callback and do an initial pull.
            self._hub.register_operational_callback(self.process_callback, self._sn)
            # This ensures the entity gets the state if the plug is already connected.
            await self.process_callback()
        else:
            # For Hub entities, register the callback for future updates.
            self._hub.register_hub_callback(self.process_hub_callback)
            
            # Immediately trigger the first update with the hub's current state.
            # This avoids waiting for the first periodic update cycle.
            _LOGGER.debug(f"Hub sensor {self.name} added, performing initial state pull.")
            await self.process_hub_callback(self._hub.state, self._hub.statistics)

    async def async_will_remove_from_hass(self) -> None:
        if self._sn:
            self._hub.remove_operational_callback(self.process_callback, self._sn)
        else:
            self._hub.remove_hub_callback(self.process_hub_callback)

    async def process_callback(self) -> None:
        self._plug = self._hub.get_plug_by_sn(self._sn)
        if self._plug:
            self._attr_available = self._plug.alive
            await self.async_update()
            self.async_write_ha_state()
        elif self._attr_available:
            self._attr_available = False
            self.async_write_ha_state()

    async def process_hub_callback(self, state: HubState, statistics: HubStatistics) -> None:
        self._attr_available = True
        await self.async_update()
        self.async_write_ha_state()
    
    @abstractmethod
    async def async_update(self) -> None: pass

class TendaBeliPower(TendaBeliSensor):
    _attr_name = "Power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT 
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:flash"
    
    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_unique_id = f"tbp_power_{sn}"

    async def async_update(self) -> None:
        if self._plug:
            power, _ = self._plug.power
            self._attr_native_value = float(power) if power != "unknown" else None

class TendaBeliEnergy(TendaBeliSensor):
    _attr_name = "Energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR 
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_unique_id = f"tbp_energy_{sn}"

    async def async_update(self) -> None:
        """Update the sensor's state."""
        if self._plug:
            energy, _ = self._plug.energy # timestamp už nepotřebujeme
            try:
                self._attr_native_value = float(energy) if energy != "unknown" else None
                # Atribut _attr_last_reset již nenastavujeme, protože state_class je 'total_increasing'
            except (ValueError, TypeError):
                self._attr_native_value = None

class TendaBeliUpTime(TendaBeliSensor):
    _attr_name = "Uptime"
    _attr_icon = "mdi:clock-outline"
    
    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        """Initialize the uptime sensor."""
        super().__init__(hub, sn)
        self._attr_unique_id = f"tbp_uptime_{sn}"
        self._raw_seconds: Optional[int] = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {"seconds": self._raw_seconds}

    async def async_update(self) -> None:
        """Update the sensor's state with a formatted string."""
        if self._plug:
            uptime_str, _ = self._plug.uptime
            if uptime_str.isdigit():
                self._raw_seconds = int(uptime_str)
                self._attr_native_value = format_duration_in_seconds(self._raw_seconds)
            else:
                self._raw_seconds = None
                self._attr_native_value = "unknown"

class TendaBeliOnTime(TendaBeliSensor):
    _attr_name = "On Time"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        """Initialize the on-time sensor."""
        super().__init__(hub, sn)
        self._attr_unique_id = f"tbp_ontime_{sn}"
        self._raw_seconds: Optional[int] = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {"seconds": self._raw_seconds}

    async def async_update(self) -> None:
        """Update the sensor's state with a formatted string."""
        if self._plug:
            ontime_str, _ = self._plug.ontime
            if ontime_str.isdigit():
                self._raw_seconds = int(ontime_str)
                self._attr_native_value = format_duration_in_seconds(self._raw_seconds)
            else:
                self._raw_seconds = None
                self._attr_native_value = "unknown"

class TendaBeliPlugStatus(TendaBeliSensor):
    _attr_name = "Status"
    _attr_icon = "mdi:connection"

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_unique_id = f"tbp_status_{sn}"

    async def async_update(self) -> None:
        if self._plug:
            self._attr_native_value = self._plug.status.value
        else:
            self._attr_native_value = "disconnected"

class TendaBeliLastSeen(TendaBeliSensor):
    _attr_name = "Last Seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, hub: TendaBeliServer, sn: str) -> None:
        super().__init__(hub, sn)
        self._attr_unique_id = f"tbp_last_seen_{sn}"

    async def async_update(self) -> None:
        if self._plug and self._plug._last_seen:
            try:
                self._attr_native_value = datetime.fromtimestamp(self._plug._last_seen, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                self._attr_native_value = None
        else:
            self._attr_native_value = None

# --- Hub Sensors ---
class TendaBeliHubState(TendaBeliSensor):
    _attr_name = "Hub State"
    _attr_unique_id = "tbh_state"
    _attr_icon = "mdi:server-network"
    
    async def async_update(self) -> None:
        self._attr_native_value = self._hub.state.value

class TendaBeliHubUptime(TendaBeliSensor):
    _attr_name = "Hub Uptime"
    _attr_unique_id = "tbh_uptime"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hub: TendaBeliServer, sn: Optional[str] = None) -> None:
        """Initialize the Hub Uptime sensor."""
        super().__init__(hub, sn)
        self._raw_seconds: Optional[int] = 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return {"seconds": self._raw_seconds}
    
    async def async_update(self) -> None:
        """Update the sensor's state with a formatted string."""
        stats = self._hub.stats
        self._raw_seconds = int(stats.uptime) if stats.uptime else 0
        self._attr_native_value = format_duration_in_seconds(self._raw_seconds)

class TendaBeliHubConnections(TendaBeliSensor):
    _attr_name = "Hub Connections"
    _attr_unique_id = "tbh_connections"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:access-point-network"

    async def async_update(self) -> None:
        self._attr_native_value = self._hub.stats.current_connections

class TendaBeliHubPackets(TendaBeliSensor):
    _attr_name = "Hub Packets Received"
    _attr_unique_id = "tbh_packets"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:network"

    async def async_update(self) -> None:
        self._attr_native_value = self._hub.stats.packets_received

class TendaBeliHubErrors(TendaBeliSensor):
    _attr_name = "Hub Errors"
    _attr_unique_id = "tbh_errors"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:alert-circle-outline"

    async def async_update(self) -> None:
        self._attr_native_value = self._hub.stats.errors