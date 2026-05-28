"""
Tenda Beli Smart Plug Integration - Core Module.

This module provides the core functionality for communicating with Tenda SP9/SP3 smart plugs,
including device discovery, connection management, and data processing.

"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set, Tuple
from dataclasses import dataclass

from .const import (
    PLATFORMS,
    DEFAULT_TIMEOUT,
    DEFAULT_PORT,
    HUB_RESTART_DELAY,
    PACKET_TYPES,
)

_LOGGER = logging.getLogger(__name__)




class PlugStatus(Enum):
    """Enumeration for plug connection status states."""
    NEW = "new"
    INITIALIZING = "initializing" 
    SN_RETRIEVED = "sn_retrieved"
    REGISTERED = "registered"
    IN_OPERATION = "in_operation"
    DISCONNECTING = "disconnecting"


class HubState(Enum):
    """Enumeration for hub operational states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"

@dataclass
class HubStatistics:
    """Container for hub operational statistics and metrics."""
    start_time: Optional[float] = None
    total_connections: int = 0
    current_connections: int = 0
    packets_received: int = 0
    packets_sent: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    uptime: float = 0.0
    
    def update_uptime(self) -> None:
        """Calculate and update the current uptime."""
        if self.start_time:
            self.uptime = time.time() - self.start_time


def get_mac_address_from_arp(ip_address: str) -> Optional[str]:
    """
    Retrieve MAC address for given IP using ARP table.
    
    Args:
        ip_address: Target IP address
        
    Returns:
        MAC address string if found, None otherwise
    """
    try:
        with os.popen(f"arp -n {ip_address}") as process:
            arp_output = process.read()
        
        mac_pattern = r'([a-fA-F0-9]{2}[:-]){5}[a-fA-F0-9]{2}'
        mac_match = re.search(mac_pattern, arp_output)
        
        return mac_match.group(0) if mac_match else None
        
    except Exception as err:
        _LOGGER.warning("Failed to retrieve MAC address for %s: %s", ip_address, err)
        return None

class TendaBeliPlug:
    """
    Represents a Tenda SP9/SP3 smart plug with state management.
    
    This class handles communication with individual plugs, maintains their state,
    and provides methods for sending commands and updating data.
    """
    
    def __init__(
        self, 
        ip_address: str, 
        writer: asyncio.StreamWriter, 
        hub: 'TendaBeliServer',
        timeout: int = DEFAULT_TIMEOUT
    ) -> None:
        """
        Initialize a new plug instance.
        
        Args:
            ip_address: IP address of the plug
            writer: AsyncIO stream writer for communication
            hub: Reference to the parent hub server
            timeout: Connection timeout in seconds
        """
        # Core references
        self._hub = hub
        self._writer = writer
        self._timeout = timeout
        
        # Network information
        self._ip_address = ip_address
        self._mac_address = get_mac_address_from_arp(ip_address)
        
        # Connection state
        self._status = PlugStatus.NEW
        self._available = False
        self._registration_time = time.time()
        self._last_seen = self._registration_time
        
        # Device identification
        self._serial_number: Optional[str] = None
        self._nickname: Optional[str] = None
        self._model: Optional[str] = None
        self._firmware: Optional[str] = None
        self._hardware: Optional[str] = None
        
        # Device state
        self._is_powered_on = False
        self._power_consumption = "unknown"
        self._power_last_update: Optional[float] = None
        self._energy_consumption = "unknown"
        self._energy_last_update: Optional[datetime] = None
        self._device_uptime = "unknown"
        self._uptime_last_update: Optional[float] = None
        self._on_time = "unknown"
        self._on_time_last_update: Optional[datetime] = None
        
        # Communication statistics
        self._packets_sent = 0
        self._packets_received = 0
        self._last_command_time: Optional[float] = None

    def _send_command(self, command: bytes) -> None:
        """
        Send command to the plug with error handling and statistics tracking.
        
        Args:
            command: Raw command bytes to send
        """
        try:
            if not self._writer or self._writer.is_closing():
                _LOGGER.warning(
                    "Cannot send command to %s: connection closed", 
                    self._serial_number or self._ip_address
                )
                return
                
            self._writer.write(command)
            self._packets_sent += 1
            self._last_command_time = time.time()
            
            _LOGGER.debug(
                "Sent command to %s: %s", 
                self._serial_number or self._ip_address, 
                command.hex()
            )
            
        except Exception as err:
            _LOGGER.error(
                "Failed to send command to %s: %s", 
                self._serial_number or self._ip_address, 
                err
            )
    
    def send_toggle_request(self) -> None:
        """Send power toggle command to the plug."""
        toggle_command = bytes.fromhex(
            "24000300015d000c000000005f0c00007b22616374696f6e223a317d"
        )
        self._send_command(toggle_command)
    
    def send_power_request(self) -> None:
        """Request current power consumption measurement."""
        power_command = bytes.fromhex("2400030000d500000205000000000000")
        self._send_command(power_command)
    
    def send_energy_request(self) -> None:
        """Request energy consumption history."""
        energy_command = bytes.fromhex("2400030000d500000208000000000000")
        self._send_command(energy_command)
    
    async def notify_state_change(self) -> None:
        """Notify the hub of state changes for Home Assistant updates."""
        if self._hub and self._serial_number:
            await self._hub.notify_plug_update(self._serial_number)

    # Properties for status and connection state
    @property
    def status(self) -> PlugStatus:
        """Get the current connection status."""
        return self._status

    @status.setter
    def status(self, value: PlugStatus) -> None:
        """Set the connection status with validation."""
        if isinstance(value, PlugStatus):
            self._status = value
        else:
            _LOGGER.warning(
                "Invalid status type for %s: %s", 
                self._serial_number or self._ip_address, 
                type(value)
            )

    @property
    def alive(self) -> bool:
        """Check if the plug is considered alive based on last contact."""
        return (time.time() - self._last_seen) <= self._timeout

    @alive.setter
    def alive(self, timestamp: float) -> None:
        """Update the last seen timestamp."""
        self._last_seen = timestamp

    @property
    def ip_address(self) -> str:
        """Get the plug's IP address."""
        return self._ip_address
    
    @property
    def mac_address(self) -> Optional[str]:
        """Get the plug's MAC address."""
        return self._mac_address

    # Properties for device identification
    @property  
    def sn(self) -> Optional[str]:
        """Get the plug's serial number."""
        return self._serial_number

    @sn.setter
    def sn(self, value: str) -> None:
        """Set the serial number and trigger setup if new."""
        if not value or len(value) == 0:
            return
            
        if self._serial_number != value:
            _LOGGER.info(
                "Plug %s identified with serial number: %s", 
                self.ip_address, 
                value
            )
            self._serial_number = value
            self._status = PlugStatus.SN_RETRIEVED
            asyncio.create_task(self.notify_state_change())
       
    @property
    def nick(self) -> Optional[str]:
        """Get the plug's nickname."""
        return self._nickname

    @nick.setter
    def nick(self, value: str) -> None:
        """Set the plug's nickname."""
        self._nickname = value
    
    @property
    def model(self) -> Optional[str]:
        """Get the plug's device model."""
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        """Set the plug's device model."""
        self._model = value
    
    @property
    def firmware(self) -> Optional[str]:
        """Get the plug's firmware version."""
        return self._firmware

    @firmware.setter
    def firmware(self, value: str) -> None:
        """Set the plug's firmware version."""
        self._firmware = value
    
    @property
    def hardware(self) -> Optional[str]:
        """Get the plug's hardware version."""
        return self._hardware

    @hardware.setter
    def hardware(self, value: str) -> None:
        """Set the plug's hardware version."""
        self._hardware = value
        
    # Properties for device state
    @property
    def is_on(self) -> bool:
        """Get the power state of the plug."""
        return self._is_powered_on

    @is_on.setter
    def is_on(self, value: bool) -> None:
        """Set the power state and trigger updates if changed."""
        if isinstance(value, bool) and value != self._is_powered_on:
            self._is_powered_on = value
            asyncio.create_task(self.notify_state_change())

    @property
    def power(self) -> Tuple[str, Optional[float]]:
        """Get current power consumption and last update timestamp."""
        return self._power_consumption, self._power_last_update

    @power.setter
    def power(self, value: str) -> None:
        """Set power consumption with validation."""
        try:
            float(value)  # Validate numeric value
            if self._power_consumption != value:
                self._power_consumption = value
                self._power_last_update = time.time()
                asyncio.create_task(self.notify_state_change())
        except ValueError:
            _LOGGER.warning(
                "Invalid power value for %s: %s", 
                self._serial_number or self._ip_address, 
                value
            )
            
    @property
    def energy(self) -> Tuple[str, Optional[datetime]]:
        """Get energy consumption and last update timestamp."""
        return self._energy_consumption, self._energy_last_update

    def set_energy(self, value: str, timestamp: datetime) -> None:
        """Set energy consumption with specific timestamp."""
        try:
            float(value)  # Validate numeric value
            if self._energy_consumption != value:
                self._energy_consumption = value
                self._energy_last_update = timestamp
                asyncio.create_task(self.notify_state_change())
        except ValueError:
            _LOGGER.warning(
                "Invalid energy value for %s: %s", 
                self._serial_number or self._ip_address, 
                value
            )
            
    @energy.setter 
    def energy(self, value: str) -> None:
        """Set energy consumption with current timestamp."""
        self.set_energy(value, datetime.now())
    
    @property
    def uptime(self) -> Tuple[str, Optional[float]]:
        """Get device uptime and last update timestamp."""
        return self._device_uptime, self._uptime_last_update

    @uptime.setter
    def uptime(self, value: str) -> None:
        """Set device uptime."""
        if self._device_uptime != value:
            self._device_uptime = value
            self._uptime_last_update = time.time()
            asyncio.create_task(self.notify_state_change())

    @property
    def ontime(self) -> Tuple[str, Optional[datetime]]:
        """Get on-time duration and last update timestamp."""
        return self._on_time, self._on_time_last_update
    
    @ontime.setter
    def ontime(self, value: str) -> None:
        """Set on-time duration."""
        if self._on_time != value:
            self._on_time = value
            self._on_time_last_update = datetime.now()
            asyncio.create_task(self.notify_state_change())

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the plug.
        
        Returns:
            Dictionary containing all plug statistics and state information
        """
        return {
            "serial_number": self._serial_number,
            "ip_address": self._ip_address,
            "mac_address": self._mac_address,
            "status": self._status.value,
            "is_alive": self.alive,
            "is_powered_on": self._is_powered_on,
            "power_consumption": self._power_consumption,
            "energy_consumption": self._energy_consumption,
            "device_uptime": self._device_uptime,
            "on_time": self._on_time,
            "packets_sent": self._packets_sent,
            "packets_received": self._packets_received,
            "last_command_time": self._last_command_time,
            "registration_time": self._registration_time,
            "last_seen": self._last_seen
        }

class TendaBeliServer:
    """
    Main server class for managing Tenda smart plug connections and communication.
    
    This class handles:
    - Network server operations for plug discovery and provisioning
    - Plug connection management and health monitoring
    - Callback management for Home Assistant integration
    - Statistics and operational state tracking
    """
    
    def __init__(self) -> None:
        """Initialize the server with default state and empty collections."""
        # Core server state
        self._state = HubState.STOPPED
        self._statistics = HubStatistics()
        
        # Network configuration
        self._ha_ip: Optional[str] = None
        self._provisioning_server_ip = ""
        
        # Server management
        self._servers: list = []
        self._server_tasks: list = []
        
        # Connected devices
        self._connected_plugs: Dict[str, TendaBeliPlug] = {}
        
        # Temporary storage for rendezvous device information
        self._rendezvous_device_info: Dict[str, Dict[str, str]] = {}
        
        # Callback management
        self._setup_callbacks: Set[Callable] = set()
        self._hub_callbacks: Set[Callable] = set()
        self._operational_callbacks: Dict[str, Set[Callable]] = {}
        
        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._hub_update_task: Optional[asyncio.Task] = None
        
        # Platform readiness
        self.platforms_ready = False
        
        # Start background services
        self._start_health_monitoring()
        self._start_periodic_updates()
        
        # Config entry reference for device registry
        self.config_entry_id: Optional[str] = None

    # Callback and notification management
    async def notify_plug_update(self, serial_number: str) -> None:
        """
        Notify all registered operational callbacks for a specific plug.
        
        Args:
            serial_number: Serial number of the plug that was updated
        """
        if serial_number not in self._operational_callbacks:
            return
            
        callbacks = self._operational_callbacks[serial_number].copy()
        _LOGGER.debug(
            "Notifying %d callbacks for plug %s", 
            len(callbacks), 
            serial_number
        )
        
        for callback in callbacks:
            try:
                await callback()
            except Exception as err:
                _LOGGER.error(
                    "Error in operational callback for %s: %s", 
                    serial_number, 
                    err
                )

    async def _notify_hub_state_change(self) -> None:
        """Notify all hub callbacks of state or statistics changes."""
        if not self._hub_callbacks:
            return
            
        callbacks = self._hub_callbacks.copy()
        for callback in callbacks:
            try:
                await callback(self._state, self._statistics)
            except Exception as err:
                _LOGGER.error("Error in hub state callback: %s", err)

    def register_hub_callback(self, callback: Callable) -> None:
        """Register a callback for hub state changes."""
        self._hub_callbacks.add(callback)

    def remove_hub_callback(self, callback: Callable) -> None:
        """Remove a hub state change callback."""
        self._hub_callbacks.discard(callback)

    def register_operational_callback(self, callback: Callable, serial_number: str) -> None:
        """
        Register an operational callback for a specific plug.
        
        Args:
            callback: Function to call when plug state changes
            serial_number: Serial number of the plug to monitor
        """
        self._operational_callbacks.setdefault(serial_number, set()).add(callback)
        _LOGGER.debug(
            "Registered operational callback for %s (total: %d)", 
            serial_number, 
            len(self._operational_callbacks[serial_number])
        )
    
    def remove_operational_callback(self, callback: Callable, serial_number: str) -> None:
        """
        Remove an operational callback for a specific plug.
        
        Args:
            callback: Function to remove
            serial_number: Serial number of the monitored plug
        """
        if serial_number in self._operational_callbacks:
            self._operational_callbacks[serial_number].discard(callback)
            if not self._operational_callbacks[serial_number]:
                del self._operational_callbacks[serial_number]
        _LOGGER.debug("Removed operational callback for %s", serial_number)

    async def register_setup_callback(self, callback: Callable) -> None:
        """
        Register a platform setup callback.
        
        When all platforms are registered, triggers setup for already connected plugs.
        
        Args:
            callback: Platform setup function
        """
        self._setup_callbacks.add(callback)
        callback_count = len(self._setup_callbacks)
        platform_count = len(PLATFORMS)
        
        _LOGGER.debug(
            "Setup callback registered (%d/%d platforms ready)", 
            callback_count, 
            platform_count
        )
        
        if not self.platforms_ready and callback_count == platform_count:
            self.platforms_ready = True
            _LOGGER.info("All %d platforms ready, processing pending plugs", platform_count)
            
            for plug in self._connected_plugs.values():
                if plug.status == PlugStatus.SN_RETRIEVED and plug.sn:
                    _LOGGER.info("Triggering setup for connected plug %s", plug.sn)
                    for setup_callback in self._setup_callbacks:
                        await setup_callback(plug.sn, "setup")
                    plug.status = PlugStatus.REGISTERED

    def remove_setup_callback(self, callback: Callable) -> None:
        """Remove a platform setup callback."""
        self._setup_callbacks.discard(callback)
        _LOGGER.debug("Setup callback removed")

    # Background task management
    def _start_periodic_updates(self) -> None:
        """Start the periodic hub update task if not already running."""
        if self._hub_update_task is None or self._hub_update_task.done():
            self._hub_update_task = asyncio.create_task(self._periodic_hub_updates())

    async def _periodic_hub_updates(self) -> None:
        """Periodically notify hub callbacks of state changes."""
        while True:
            try:
                if self._state == HubState.RUNNING and self._hub_callbacks:
                    await self._notify_hub_state_change()
                await asyncio.sleep(600)  # Update every 10 minutes
            except asyncio.CancelledError:
                _LOGGER.debug("Hub update task cancelled")
                break
            except Exception as err:
                _LOGGER.error("Error in hub update task: %s", err)
                await asyncio.sleep(600)

    async def force_hub_update(self) -> None:
        """Force immediate hub state notification (e.g., from button press)."""
        _LOGGER.debug("Forcing immediate hub state update notification")
        await self._notify_hub_state_change()

    def _start_health_monitoring(self) -> None:
        """Start the health monitoring task if not already running."""
        if self._health_check_task is None or self._health_check_task.done():
            self._health_check_task = asyncio.create_task(self._monitor_plug_health())

    async def _register_plug_if_ready(self, plug: TendaBeliPlug, source: str) -> None:
        """Trigger platform setup for a plug once its serial number is known."""
        if not self.platforms_ready or not plug.sn:
            return

        if plug.status == PlugStatus.REGISTERED:
            return

        _LOGGER.info("Platforms ready, triggering setup for %s (%s)", plug.sn, source)
        for callback in self._setup_callbacks:
            await callback(plug.sn, "setup")

        plug.status = PlugStatus.REGISTERED

    async def _disconnect_plug(self, plug: TendaBeliPlug, source: str) -> bool:
        """Remove a plug only if the currently tracked connection is this instance."""
        current_plug = self._connected_plugs.get(plug.ip_address)
        if current_plug is not plug:
            _LOGGER.debug(
                "Skipping stale plug cleanup for %s from %s",
                plug.sn or plug.ip_address,
                source,
            )
            return False

        self._connected_plugs.pop(plug.ip_address, None)
        plug.alive = 0

        if plug.sn:
            await self.notify_plug_update(plug.sn)

        _LOGGER.debug(
            "Disconnected tracked plug %s from %s",
            plug.sn or plug.ip_address,
            source,
        )
        return True

    async def _monitor_plug_health(self) -> None:
        """Monitor plug health and remove disconnected devices."""
        while True:
            try:
                if self._state not in [HubState.RUNNING, HubState.STARTING]:
                    await asyncio.sleep(DEFAULT_TIMEOUT + 10)
                    continue
                    
                disconnected_plugs = []
                
                for address, plug in list(self._connected_plugs.items()):
                    if not plug.alive:
                        disconnected_plugs.append((address, plug))
                        _LOGGER.info(
                            "Plug %s is no longer alive, removing", 
                            plug.sn or address
                        )
                    else:
                        _LOGGER.debug(
                            "Plug %s is healthy", 
                            plug.sn or address
                        )

                # Clean up disconnected plugs
                for address, plug in disconnected_plugs:
                    try:
                        await self._disconnect_plug(plug, "health_monitor")
                    except Exception as err:
                        _LOGGER.error(
                            "Error during plug cleanup for %s: %s", 
                            address, 
                            err
                        )

                await asyncio.sleep(DEFAULT_TIMEOUT + 10)
                
            except asyncio.CancelledError:
                _LOGGER.debug("Health monitoring task cancelled")
                break
            except Exception as err:
                _LOGGER.error("Unexpected error in health monitoring: %s", err)
                self._statistics.errors += 1
                self._statistics.last_error = str(err)
                await asyncio.sleep(30)

    # Properties for external access
    @property
    def state(self) -> HubState:
        """Get the current hub state."""
        return self._state
    
    @property
    def statistics(self) -> HubStatistics:
        """Get current hub statistics with updated uptime."""
        self._statistics.update_uptime()
        self._statistics.current_connections = len(self._connected_plugs)
        return self._statistics

    @property
    def is_running(self) -> bool:
        """Check if the hub is currently running."""
        return self._state == HubState.RUNNING

    @property
    def connected_plugs(self) -> Dict[str, TendaBeliPlug]:
        """Get a copy of currently connected plugs."""
        return self._connected_plugs.copy()
    
    def get_plug_by_serial_number(self, serial_number: str) -> Optional[TendaBeliPlug]:
        """
        Find a plug by its serial number.
        
        Args:
            serial_number: Serial number to search for
            
        Returns:
            TendaBeliPlug instance if found, None otherwise
        """
        for plug in self._connected_plugs.values():
            if plug.sn == serial_number:
                return plug
        return None

    # Compatibility alias for old code
    def get_plug_by_sn(self, sn: str) -> Optional[TendaBeliPlug]:
        """Legacy method name for backward compatibility."""
        return self.get_plug_by_serial_number(sn)
    
    @property
    def stats(self) -> HubStatistics:
        """Legacy property name for backward compatibility."""
        return self.statistics

    # Server lifecycle management
    async def start(self, home_assistant_ip: str) -> bool:
        """
        Start the Tenda hub server and begin accepting connections.
        
        Args:
            home_assistant_ip: IP address of Home Assistant instance
            
        Returns:
            True if started successfully, False otherwise
        """
        if self._state != HubState.STOPPED:
            _LOGGER.warning(
                "Cannot start hub: current state is %s", 
                self._state.value
            )
            return False
            
        try:
            self._state = HubState.STARTING
            self._ha_ip = home_assistant_ip
            self._start_health_monitoring()
            self._start_periodic_updates()
            await self._notify_hub_state_change()
            
            # Validate and convert IP address for provisioning responses
            ip_parts = home_assistant_ip.split(".")
            if len(ip_parts) != 4:
                raise ValueError(f"Invalid IP address format: {home_assistant_ip}")
            
            try:
                self._provisioning_server_ip = "".join(
                    f"{int(part):02x}" for part in ip_parts
                )
            except ValueError as err:
                raise ValueError(f"Invalid IP address components: {err}")
            
            # Start network servers
            self._server_tasks = [
                asyncio.create_task(
                    self._start_server(1821, self._handle_rendezvous_connection)
                ),
                asyncio.create_task(
                    self._start_server(DEFAULT_PORT, self._handle_provisioning_connection)
                )
            ]
            
            # Initialize statistics
            self._statistics.start_time = time.time()
            self._statistics.errors = 0
            self._statistics.last_error = None
            
            # Mark as running and notify
            self._state = HubState.RUNNING
            await self._notify_hub_state_change()
            
            _LOGGER.info("Tenda Beli hub started successfully on %s", home_assistant_ip)
            return True
            
        except Exception as err:
            _LOGGER.error("Failed to start hub: %s", err, exc_info=True)
            self._state = HubState.ERROR
            self._statistics.errors += 1
            self._statistics.last_error = str(err)
            await self._notify_hub_state_change()
            return False

    async def stop(self) -> bool:
        """
        Stop the Tenda hub server and clean up all connections.
        
        Returns:
            True if stopped successfully, False otherwise
        """
        if self._state == HubState.STOPPED:
            _LOGGER.debug("Stop requested but hub is already stopped")
            return True

        try:
            self._state = HubState.STOPPING
            await self._notify_hub_state_change()

            # Collect plugs that need notification of disconnection
            plugs_to_notify = list(self._connected_plugs.values())

            # Close all plug connections gracefully
            for plug in plugs_to_notify:
                try:
                    if plug._writer and not plug._writer.is_closing():
                        plug._writer.close()
                        await plug._writer.wait_closed()
                except Exception as err:
                    _LOGGER.warning(
                        "Error closing connection for plug %s: %s", 
                        plug.sn or plug.ip_address, 
                        err
                    )
            
            # Cancel all background tasks
            tasks_to_cancel = [
                *self._server_tasks,
                self._health_check_task,
                self._hub_update_task
            ]
            
            for task in tasks_to_cancel:
                if task and not task.done():
                    task.cancel()
            
            # Close all servers
            for server in self._servers:
                server.close()
                await server.wait_closed()

            _LOGGER.info("Hub shutdown complete, notifying entities")
            
            # Mark all plugs as offline and notify entities
            for plug in plugs_to_notify:
                await self._disconnect_plug(plug, "hub_stop")

            # Clear all collections
            self._servers.clear()
            self._server_tasks.clear()
            self._connected_plugs.clear()

            # Update state
            self._state = HubState.STOPPED
            await self._notify_hub_state_change()
            
            _LOGGER.info("Tenda Beli hub stopped successfully")
            return True
            
        except Exception as err:
            _LOGGER.error("Error during hub shutdown: %s", err, exc_info=True)
            self._state = HubState.ERROR
            self._statistics.errors += 1
            self._statistics.last_error = str(err)
            await self._notify_hub_state_change()
            return False

    async def restart(self) -> bool:
        """
        Restart the Tenda hub server.
        
        Returns:
            True if restarted successfully, False otherwise
        """
        _LOGGER.info("Restarting Tenda Beli hub")
        
        if not await self.stop():
            _LOGGER.error("Failed to stop hub during restart")
            return False
            
        # Brief pause to ensure clean shutdown
        await asyncio.sleep(HUB_RESTART_DELAY)
        
        if self._ha_ip:
            return await self.start(self._ha_ip)
        else:
            _LOGGER.error("Cannot restart: no Home Assistant IP stored")
            return False

    # Network server management
    async def _start_server(self, port: int, handler: Callable) -> None:
        """
        Start a network server on the specified port.
        
        Args:
            port: Port number to listen on
            handler: Connection handler function
        """
        try:
            server = await asyncio.start_server(handler, "0.0.0.0", port)
            self._servers.append(server)
            
            addr = server.sockets[0].getsockname()
            _LOGGER.info("Server listening on %s:%d", addr[0], port)
            
            async with server:
                await server.serve_forever()
                
        except asyncio.CancelledError:
            _LOGGER.debug("Server on port %d cancelled", port)
        except Exception as err:
            _LOGGER.error("Server error on port %d: %s", port, err, exc_info=True)
            self._statistics.errors += 1
            self._statistics.last_error = str(err)

    async def _handle_rendezvous_connection(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle rendezvous connections from plugs seeking the provisioning server.
        
        Args:
            reader: Stream reader for incoming data
            writer: Stream writer for responses
        """
        addr, port = writer.get_extra_info('peername')
        
        try:
            # Wait for initial discovery packet
            initial_data = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            _LOGGER.debug(
                "Rendezvous request from %s:%d - data: %s", 
                addr, 
                port,
                initial_data.hex() if initial_data else 'None'
            )
            
            # Extract device information from rendezvous data
            if initial_data:
                decoded_device_info = self.decode_device_info(initial_data.hex())
                if decoded_device_info:
                    self._rendezvous_device_info[addr] = decoded_device_info
                    _LOGGER.info(
                        "Stored device info for %s: %s", 
                        addr, 
                        {k: v for k, v in decoded_device_info.items() if k != 'serial_number'}  # Don't log full SN
                    )
            
            _LOGGER.info("Rendezvous connection from %s:%d", addr, port)
            
            # Send provisioning server details
            response = bytes.fromhex(
                f"2400020000d2000e000000000000000000100004{self._provisioning_server_ip}"
                f"00110002{DEFAULT_PORT:04x}"
            )
            writer.write(response)
            await writer.drain()
            
            _LOGGER.debug(
                "Redirected %s:%d to provisioning server. Waiting for unexpected responses...", 
                addr, 
                port
            )
            
            # Check for unexpected responses (should be none)
            try:
                unexpected_data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                if unexpected_data:
                    _LOGGER.warning(
                        "Unexpected response from %s:%d after redirection: %s", 
                        addr, 
                        port,
                        unexpected_data.hex()
                    )
            except asyncio.TimeoutError:
                _LOGGER.debug("No unexpected response from %s:%d (expected)", addr, port)
            
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Timeout waiting for initial data from %s:%d on rendezvous server", 
                addr, 
                port
            )
        except Exception as err:
            _LOGGER.error(
                "Error in rendezvous connection from %s:%d: %s", 
                addr, 
                port, 
                err
            )
        finally:
            if not writer.is_closing():
                _LOGGER.debug("Closing rendezvous connection from %s:%d", addr, port)
                writer.close()
                await writer.wait_closed()
    
    def decode_device_info(self, hex_string: str):
        data = bytes.fromhex(hex_string)

        parts = []
        current = []
        for b in data:
            if 32 <= b <= 126:
                current.append(chr(b))
            else:
                if current:
                    parts.append("".join(current))
                    current = []
        if current:
            parts.append("".join(current))

        # Find the starting position of actual device data by looking for serial number pattern
        start_offset = 0
        serial_pattern = re.compile(r'^E\d{16}$')
        
        for i, text in enumerate(parts):
            if serial_pattern.match(text):
                start_offset = i
                _LOGGER.debug(f"Found serial number at position {i}: {text}")
                break
        
        if start_offset == 0 and len(parts) > 0 and not serial_pattern.match(parts[0]):
            _LOGGER.warning("Serial number pattern not found, using default positions")
        
        device_info = {}
        
        # Direct assignment based on expected positions, adjusted for offset
        if len(parts) > start_offset:
            device_info['serial_number'] = parts[start_offset]  # Serial number
            _LOGGER.debug(f"{start_offset + 1}: {parts[start_offset]} (serial_number)")
            
        if len(parts) > start_offset + 1:
            device_info['firmware'] = parts[start_offset + 1]  # Firmware
            _LOGGER.debug(f"{start_offset + 2}: {parts[start_offset + 1]} (firmware)")
            
        if len(parts) > start_offset + 2:
            device_info['model'] = parts[start_offset + 2].replace('_', ' ').strip()  # Model
            _LOGGER.debug(f"{start_offset + 3}: {parts[start_offset + 2]} (model -> {device_info['model']})")
            
        if len(parts) > start_offset + 3:
            device_info['hardware'] = parts[start_offset + 3]  # Hardware version
            _LOGGER.debug(f"{start_offset + 4}: {parts[start_offset + 3]} (hardware)")

        _LOGGER.debug("Extracted device info: %s", device_info)
        return device_info

    async def _handle_provisioning_connection(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle provisioning connections from plugs for ongoing communication.
        
        Args:
            reader: Stream reader for incoming data
            writer: Stream writer for responses
        """
        address, port = writer.get_extra_info('peername')
        _LOGGER.info("Provisioning connection from %s:%d", address, port)
        
        # Create new plug instance and register it
        plug = TendaBeliPlug(address, writer, self)
        
        # Apply stored rendezvous device information if available
        if address in self._rendezvous_device_info:
            device_info = self._rendezvous_device_info[address]
            if 'model' in device_info:
                plug.model = device_info['model']
            if 'firmware' in device_info:
                plug.firmware = device_info['firmware']
            if 'hardware' in device_info:
                plug.hardware = device_info['hardware']
            if 'serial_number' in device_info:
                plug.sn = device_info['serial_number']
            
            _LOGGER.debug("Applied device info to plug %s: %s", address, device_info)
            # Clean up stored info after use
            del self._rendezvous_device_info[address]
        
        self._connected_plugs[address] = plug
        self._statistics.total_connections += 1

        await self._register_plug_if_ready(plug, "rendezvous")
        
        try:
            # Perform handshake
            try:
                await asyncio.wait_for(reader.read(1024), timeout=10.0)
                handshake_response = bytes.fromhex(
                    "24000300001a001d0000000000000000000700010000080001000009000100000a00020064000b000400015180"
                )
                writer.write(handshake_response)
                await writer.drain()
                
                await asyncio.wait_for(reader.read(1024), timeout=10.0)
                _LOGGER.debug("Handshake completed for %s:%d", address, port)
                
            except asyncio.TimeoutError:
                _LOGGER.error("Handshake timeout with %s:%d", address, port)
                return
                
            # Main communication loop
            while self._state == HubState.RUNNING:
                try:
                    datapack = await asyncio.wait_for(
                        reader.read(1024), 
                        timeout=DEFAULT_TIMEOUT
                    )
                    
                    if not datapack:
                        _LOGGER.info("Connection closed by plug %s:%d", address, port)
                        break
                    
                    self._statistics.packets_received += 1
                    await self._process_packet_data(datapack, plug, writer)
                        
                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        "Read timeout for plug %s:%d, closing connection", 
                        address, 
                        port
                    )
                    break
                except Exception as err:
                    _LOGGER.error(
                        "Error processing packet from %s:%d: %s", 
                        address, 
                        port,
                        err
                    )
                    self._statistics.errors += 1
                    break
                    
        except Exception as err:
            _LOGGER.error(
                "Error in provisioning connection from %s:%d: %s", 
                address, 
                port,
                err,
                exc_info=True
            )
            self._statistics.errors += 1
            self._statistics.last_error = str(err)
        finally:
            if not writer.is_closing():
                writer.close()
                await writer.wait_closed()

            await self._disconnect_plug(plug, "provisioning_disconnect")
            _LOGGER.debug("Provisioning connection cleanup finished for %s:%d", address, port)

    async def _process_packet_data(self, datapack: bytes, plug: TendaBeliPlug, writer: asyncio.StreamWriter) -> None:
        packets = datapack.split(b'$')
        
        for data in packets:
            if len(data) == 0: continue
                
            try:
                packet_type = data[4] if len(data) > 4 else 0
                _LOGGER.debug(f"Processing packet type {packet_type} for {plug.sn or plug.ip_address}: {data.hex()}")
                
                if packet_type == 101: await self._handle_keepalive_packet(plug, writer)
                elif packet_type == 102: await self._handle_status_packet(data, plug)
                elif packet_type == 94: await self._handle_command_response(data, plug)
                elif packet_type == 103: await self._handle_serial_packet(data, plug)
                elif packet_type == 213: await self._handle_power_packet(data, plug)
                elif packet_type == 137: await self._handle_energy_packet(data, plug, writer)
                else: _LOGGER.debug(f"Unknown packet type {packet_type}: {data.hex()}")
                    
            except Exception as err:
                _LOGGER.error(f"Error processing individual packet: {err}", exc_info=True)
                self._statistics.errors += 1

    
    async def _handle_keepalive_packet(self, plug: TendaBeliPlug, writer: asyncio.StreamWriter) -> None:
        if plug.sn:
            writer.write(bytes.fromhex("24000300006600000000000000000000"))
            await writer.drain()
            plug.alive = time.time()
            plug.send_power_request()
            _LOGGER.debug(f"Keepalive acknowledged for {plug.sn}")
        else:
            _LOGGER.debug("Keepalive received before serial assignment; replying and marking connection alive.")
            plug.alive = time.time()
            writer.write(bytes.fromhex("24000300006600000000000000000000"))
            await writer.drain()

    async def _handle_status_packet(self, data: bytes, plug: TendaBeliPlug) -> None:
        """Handle status packet with serial number."""
        try:
            json_start_idx = data.find(b'{')
            if json_start_idx == -1:
                _LOGGER.warning(f"Could not find JSON in status packet for {plug.sn or plug.ip_address}")
                return

            json_str = data[json_start_idx:].decode('utf-8')
            payload = json.loads(json_str)

            new_sn = payload.get("serialNum")
            status_val = payload.get("status")

            had_sn = bool(plug.sn)
            if new_sn:
                plug.sn = new_sn

            if status_val is not None:
                new_is_on = bool(status_val)
                
                if plug.is_on != new_is_on:
                    _LOGGER.info(f"State change detected for {plug.sn}: {'ON' if new_is_on else 'OFF'}")
                    plug.is_on = new_is_on
                else:
                    _LOGGER.debug(f"Status update for {plug.sn} received, state is unchanged: {'ON' if new_is_on else 'OFF'}")

                plug.send_power_request()

                if not had_sn:
                    await self._register_plug_if_ready(plug, "status_packet")
            
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as err:
            _LOGGER.error(f"Error processing status packet JSON: {err} - Data: {data.hex()}")
        except Exception as err:
            _LOGGER.error(f"Unexpected error in _handle_status_packet: {err}", exc_info=True)

    async def _handle_command_response(self, data: bytes, plug: TendaBeliPlug) -> None:
        if len(data) >= 50: _LOGGER.debug(f"Command response received for {plug.sn}")

    async def _handle_serial_packet(self, data: bytes, plug: TendaBeliPlug) -> None:
        try:
            sn_idx = data.rfind(b'serialNum')
            if sn_idx != -1:
                had_sn = bool(plug.sn)
                new_sn = data[sn_idx+12:sn_idx+29].decode('utf-8')
                plug.sn = new_sn

                if not had_sn:
                    await self._register_plug_if_ready(plug, "serial_packet")
        except Exception as err:
            _LOGGER.error(f"Error processing serial packet: {err} - Data: {data.hex()}")

    async def _handle_power_packet(self, data: bytes, plug: TendaBeliPlug) -> None:
        if len(data) > 50:
            try:
                data_str = data.decode('utf-8', errors='ignore')
                if ':' in data_str:
                    power_str = data_str.split(':')[-1].strip('"}')
                    plug.power = power_str
                    _LOGGER.debug(f"Power update for {plug.sn}: {power_str}W")
            except Exception as err:
                _LOGGER.error(f"Error processing power packet: {err}")

    async def _handle_energy_packet(self, data: bytes, plug: TendaBeliPlug, writer: asyncio.StreamWriter) -> None:
        _LOGGER.debug(f"[{plug.sn or plug.ip_address}] - Received raw energy data packet: {data.hex()}")
        try:
            # Send acknowledgement to the plug
            ack_response = bytes.fromhex("24000300018c000400000000000000006e756c6c")
            writer.write(ack_response)
            await writer.drain()
            _LOGGER.debug(f"[{plug.sn}] - Sent energy packet acknowledgement.")
            
            # Check if the keyword 'energy' is in the packet
            if b'energy' not in data:
                _LOGGER.debug(f"[{plug.sn}] - 'energy' keyword not found in packet. Skipping.")
                return
                
            # Find the start and end of the JSON object
            start_idx, end_idx = data.find(b'{'), data.rfind(b'}')
            if start_idx == -1 or end_idx == -1:
                _LOGGER.warning(f"[{plug.sn}] - Could not find valid JSON object in energy packet. Data: {data.hex()}")
                return
                
            json_str = data[start_idx:end_idx + 1].decode('utf-8')
            _LOGGER.debug(f"[{plug.sn}] - Extracted JSON string: {json_str}")

            # Find the start and end of the energy data list within the JSON
            energy_start, energy_end = json_str.find('['), json_str.find(']')
            if energy_start == -1 or energy_end == -1:
                _LOGGER.warning(f"[{plug.sn}] - Could not find energy data list '[]' in the JSON string.")
                return
                
            # Extract and parse the list of energy entries
            energy_list_str = json_str[energy_start + 1:energy_end]
            if not energy_list_str:
                _LOGGER.debug(f"[{plug.sn}] - Energy data list is empty. Nothing to process.")
                return

            _LOGGER.debug(f"[{plug.sn}] - Raw energy list content: '{energy_list_str}'")
            energy_entries = [e.strip('"') for e in energy_list_str.split('","')]
            _LOGGER.debug(f"[{plug.sn}] - Found {len(energy_entries)} energy entries to process.")
            
            # Process each entry in the list
            for i, entry in enumerate(energy_entries):
                _LOGGER.debug(f"[{plug.sn}] - Processing entry {i+1}/{len(energy_entries)}: '{entry}'")
                energy_data = entry.split(',')
                
                if len(energy_data) >= 5:
                    try:
                        # Extract individual data points
                        ts = int(energy_data[0])
                        up = energy_data[1]
                        en = energy_data[2]
                        on = energy_data[3]
                        inc = int(energy_data[4])
                        
                        _LOGGER.debug(f"[{plug.sn}] - Parsed entry -> Timestamp: {ts}, Uptime: {up}, Energy: {en}, Ontime: {on}, Increment: {inc}")

                        # Update plug's uptime and ontime
                        plug.uptime, plug.ontime = up, on
                        
                        # Calculate new total energy
                        new_energy = en
                        if inc > 0:
                            current_en, _ = plug.energy
                            # Only add if the current value is a valid number
                            if current_en != "unknown":
                                try:
                                    calculated_energy = str(float(current_en) + float(en))
                                    _LOGGER.debug(f"[{plug.sn}] - Incremental energy. Current: {current_en}, Increment: {en}, New Total: {calculated_energy}")
                                    new_energy = calculated_energy
                                except (ValueError, TypeError):
                                    _LOGGER.warning(f"[{plug.sn}] - Could not calculate incremental energy. Current value '{current_en}' is not a number.")
                        
                        # Set the final energy value with its timestamp
                        dt_object = datetime.fromtimestamp(ts)
                        plug.set_energy(new_energy, dt_object)
                        _LOGGER.info(f"[{plug.sn}] - Energy updated to {new_energy} kWh, Uptime: {up}s, Ontime: {on}s (Timestamp: {dt_object.isoformat()})")
                        
                        # A small delay to allow Home Assistant to process updates if many come in at once
                        await asyncio.sleep(0.05)

                    except (ValueError, IndexError) as e:
                        _LOGGER.warning(f"[{plug.sn}] - Could not parse energy data entry '{entry}'. Error: {e}")
                else:
                    _LOGGER.warning(f"[{plug.sn}] - Energy data entry has fewer than 5 parts: '{entry}'")
                    
        except Exception as err:
            _LOGGER.error(f"[{plug.sn}] - Unexpected error processing energy packet: {err}", exc_info=True)

    async def remove_plug(self, serial_number: str) -> bool:
        """
        Remove a plug from the connected devices and clean up resources.
        
        Args:
            serial_number: Serial number of plug to remove
            
        Returns:
            True if successfully removed, False otherwise
        """
        try:
            plug = self.get_plug_by_serial_number(serial_number)
            if not plug:
                _LOGGER.warning("Plug %s not found for removal", serial_number)
                return False
                
            address = plug.ip_address
            
            # Close connection gracefully
            if plug._writer and not plug._writer.is_closing():
                plug._writer.close()
                await plug._writer.wait_closed()

            await self._disconnect_plug(plug, "manual_remove")
                
            _LOGGER.info("Plug %s removed successfully", serial_number)
            return True
            
        except Exception as err:
            _LOGGER.error("Error removing plug %s: %s", serial_number, err, exc_info=True)
            return False

    def get_hub_information(self) -> Dict[str, Any]:
        """
        Get comprehensive information about the hub state and configuration.
        
        Returns:
            Dictionary containing hub status, statistics, configuration, and connected devices
        """
        return {
            "state": self._state.value,
            "statistics": {
                key: value for key, value in self._statistics.__dict__.items()
            },
            "configuration": {
                "home_assistant_ip": self._ha_ip,
                "provisioning_server_ip": self._provisioning_server_ip,
                "timeout": DEFAULT_TIMEOUT,
                "port": DEFAULT_PORT
            },
            "connected_plugs": [
                plug.get_statistics() for plug in self._connected_plugs.values()
            ]
        }

    # Compatibility alias for old code
    def get_hub_info(self) -> Dict[str, Any]:
        """Legacy method name for backward compatibility."""
        return self.get_hub_information()