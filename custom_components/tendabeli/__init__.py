"""
Tenda Beli Smart Plug Integration for Home Assistant.

This integration provides basic support for Tenda SP9/SP3 smart plugs,
including device discovery, power and energy monitoring, and hub management.

"""
import logging
from typing import Any, Dict

from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant

from .const import DOMAIN, HUB, PLATFORMS, SETUP_DONE_KEYS
from .tenda import TendaBeliServer

_LOGGER = logging.getLogger(__name__)

RUNTIME_DATA_KEYS = (*SETUP_DONE_KEYS.values(), "hub_sensors_created", "hub_buttons_created")


def _reset_runtime_data(hass: HomeAssistant) -> None:
    """Clear integration runtime flags so reload creates entities again."""
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        return

    domain_data.pop(HUB, None)
    for key in RUNTIME_DATA_KEYS:
        domain_data.pop(key, None)

    if not domain_data:
        hass.data.pop(DOMAIN, None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up Tenda Beli integration from a config entry.
    
    This function initializes the hub server, starts network services,
    and sets up all supported platforms.
    
    Args:
        hass: Home Assistant instance
        entry: Integration config entry
        
    Returns:
        True if setup was successful, False otherwise
    """
    _LOGGER.info(
        "Setting up Tenda Beli integration from config entry: %s", 
        entry.entry_id
    )
    
    # Initialize domain data structure
    hass.data.setdefault(DOMAIN, {})
    
    # Create and configure hub server
    hub = TendaBeliServer()
    hub.config_entry_id = entry.entry_id
    hass.data[DOMAIN][HUB] = hub

    # Set up graceful shutdown handler
    async def handle_homeassistant_stop(event: Event) -> None:
        """Handle Home Assistant stop event."""
        _LOGGER.info("Home Assistant stopping, shutting down Tenda Beli hub")
        try:
            await hub.stop()
            _LOGGER.info("Tenda Beli hub shutdown completed")
        except Exception as err:
            _LOGGER.error("Error during hub shutdown: %s", err, exc_info=True)

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, handle_homeassistant_stop)
    )

    # Get Home Assistant IP address for server binding
    try:
        source_ip = await async_get_source_ip(hass)
        if not source_ip:
            _LOGGER.error("Unable to determine Home Assistant IP address")
            return False
            
        _LOGGER.info("Starting Tenda Beli hub on IP address: %s", source_ip)
        
        # Start the hub server
        if not await hub.start(source_ip):
            _LOGGER.error("Failed to start Tenda Beli hub during setup")
            return False
            
    except Exception as err:
        _LOGGER.error("Error determining IP address or starting hub: %s", err, exc_info=True)
        return False

    # Set up all supported platforms
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.info("Successfully set up all platforms: %s", ", ".join(PLATFORMS))
        return True
        
    except Exception as err:
        _LOGGER.error("Failed to set up platforms: %s", err, exc_info=True)
        # Clean up hub if platform setup fails
        try:
            await hub.stop()
        except Exception:
            pass
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload Tenda Beli integration config entry.
    
    This function gracefully shuts down the hub server and unloads
    all platforms while preserving any necessary data.
    
    Args:
        hass: Home Assistant instance
        entry: Integration config entry
        
    Returns:
        True if unloading was successful, False otherwise
    """
    _LOGGER.info("Unloading Tenda Beli integration: %s", entry.entry_id)
    
    # Unload all platforms
    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            _LOGGER.warning("Some platforms failed to unload properly")
            
    except Exception as err:
        _LOGGER.error("Error unloading platforms: %s", err, exc_info=True)
        unload_ok = False
    
    # Stop and clean up hub
    if unload_ok and HUB in hass.data.get(DOMAIN, {}):
        hub: TendaBeliServer = hass.data[DOMAIN][HUB]
        try:
            _LOGGER.info("Stopping Tenda Beli hub")
            await hub.stop()
            
            _reset_runtime_data(hass)
            _LOGGER.info("Hub stopped and runtime data cleared")
            
        except Exception as err:
            _LOGGER.error("Error stopping hub during unload: %s", err, exc_info=True)
            unload_ok = False
    
    if unload_ok:
        _LOGGER.info("Tenda Beli integration unloaded successfully")
    else:
        _LOGGER.error("Tenda Beli integration unload completed with errors")
            
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Reload the Tenda Beli integration config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Integration config entry
    """
    _LOGGER.info("Reloading Tenda Beli integration: %s", entry.entry_id)
    
    if not await async_unload_entry(hass, entry):
        _LOGGER.error("Failed to unload integration during reload")
        return
        
    if not await async_setup_entry(hass, entry):
        _LOGGER.error("Failed to reload integration")
        return
        
    _LOGGER.info("Tenda Beli integration reloaded successfully")


def get_integration_info() -> Dict[str, Any]:
    """
    Get information about the integration.
    
    Returns:
        Dictionary containing integration metadata
    """
    return {
        "domain": DOMAIN,
        "name": "Tenda Beli Smart Plug Integration",
        "version": "0.2.5",
        "platforms": PLATFORMS,
        "manufacturer": "Tenda",
        "description": "Tenda Beli Smart plugs integration with power monitoring and energy tracking"
    }