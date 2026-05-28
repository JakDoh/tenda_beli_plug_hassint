"""
Constants and configuration for the Tenda Beli Smart Plug Integration.

This module defines all constants used throughout the integration,
including network settings, device information, and protocol specifications.

"""

# Integration metadata
DOMAIN = "tendabeli"
HUB = "hub"

# Supported Home Assistant platforms
PLATFORMS: list[str] = ["switch", "sensor", "button"]

# Network configuration
DEFAULT_TIMEOUT = 101  # Timeout in seconds before marking a plug as dead
DEFAULT_PORT = 1822    # Default provisioning server port
RENDEZVOUS_PORT = 1821 # Rendezvous server port for device discovery

# Hub operational settings
HUB_HEALTH_CHECK_INTERVAL = DEFAULT_TIMEOUT + 10  # Health check interval in seconds
HUB_RETRY_DELAY = 30   # Delay between retries on error (seconds)
HUB_RESTART_DELAY = 2  # Delay between stop and start during restart (seconds)
HUB_UPDATE_INTERVAL = 600  # Hub status update interval (seconds)

# Packet types for Tenda protocol communication
PACKET_TYPES = {
    101: "KEEPALIVE",      # 0x65 - Keepalive packet
    102: "STATUS",         # 0x66 - Device status with serial number
    94:  "COMMAND_RESP",   # 0x5E - Command response packet
    103: "SERIAL",         # 0x67 - Serial number packet
    213: "POWER",          # 0xD5 - Power consumption data
    137: "ENERGY"          # 0x89 - Energy consumption history
}

# Protocol command constants
COMMANDS = {
    "TOGGLE": bytes.fromhex("24000300015d000c000000005f0c00007b22616374696f6e223a317d"),
    "POWER_REQUEST": bytes.fromhex("2400030000d500000205000000000000"),
    "ENERGY_REQUEST": bytes.fromhex("2400030000d500000208000000000000"),
    "KEEPALIVE_ACK": bytes.fromhex("24000300006600000000000000000000"),
    "ENERGY_ACK": bytes.fromhex("24000300018c000400000000000000006e756c6c"),
    "HANDSHAKE_RESPONSE": bytes.fromhex(
        "24000300001a001d0000000000000000000700010000080001000009000100000a00020064000b000400015180"
    )
}

# Device information
MANUFACTURER = "Tenda"
MODEL_PLUG = "Not detected"
MODEL_HUB = "Tenda Beli Hub"

# Entity naming patterns
ENTITY_NAME_PATTERNS = {
    "switch": "Switch",
    "power": "Power",
    "energy": "Energy", 
    "uptime": "Uptime",
    "on_time": "On Time",
    "status": "Status",
    "last_seen": "Last Seen",
    "power_refresh": "Power Refresh",
    "energy_refresh": "Energy Refresh",
    "disconnect": "Disconnect"
}

# Hub entity patterns
HUB_ENTITY_PATTERNS = {
    "state": "Hub State",
    "uptime": "Hub Uptime", 
    "connections": "Hub Connections",
    "packets": "Hub Packets Received",
    "errors": "Hub Errors",
    "start": "Start Hub",
    "stop": "Stop Hub",
    "restart": "Restart Hub",
    "status": "Hub Status"
}

# Setup and teardown keys for platform management
SETUP_DONE_KEYS = {
    "switch": "switch_setup_done",
    "sensor": "sensor_setup_done", 
    "button": "button_setup_done"
}

# Error messages
ERROR_MESSAGES = {
    "INVALID_IP": "Invalid IP address format",
    "HANDSHAKE_TIMEOUT": "Handshake timeout with device",
    "CONNECTION_LOST": "Connection lost to device",
    "COMMAND_FAILED": "Failed to send command to device",
    "SETUP_FAILED": "Failed to set up platform"
}

# Default values for entity attributes
DEFAULT_VALUES = {
    "power": "unknown",
    "energy": "unknown", 
    "uptime": "unknown",
    "on_time": "unknown"
}