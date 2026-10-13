"""Constants for the Christie projector integration."""

DOMAIN = "christie"
MANUFACTURER = "Christie"

DEFAULT_PORT = 5000
DEFAULT_SCAN_INTERVAL = 5  # seconds
LIST_REFRESH = 600  # seconds between re-reading channel and test pattern lists

CONF_SCAN_INTERVAL = "scan_interval"
CONF_READ_ONLY = "read_only"
CONF_CHANNELS = "channels"

# Channel names used when the projector cannot list its channels (CineLife defaults)
DEFAULT_CHANNELS = ["Media Block Flat", "Media Block Scope", "HDMI A", "HDMI B", "HDMI 3D LR"]

PATTERN_OFF = "Aus"

# PWR values
PWR_LIGHT_OFF = 0
PWR_ON = 1
PWR_STANDBY = 3
PWR_HIBERNATE = -2
PWR_COOLING = 10
PWR_WARMING = 11

POWER_STATES = {
    PWR_LIGHT_OFF: "lamp_off",
    PWR_ON: "lamp_on",
    PWR_STANDBY: "standby",
    PWR_HIBERNATE: "hibernate",
    PWR_COOLING: "cooling",
    PWR_WARMING: "warming_up",
}

# select option -> PWR value
POWER_COMMANDS = {"standby": PWR_STANDBY, "lamp_off": PWR_LIGHT_OFF, "lamp_on": PWR_ON}

BURST_INTERVAL = 1.0  # fast polling after a command ...
BURST_SECONDS = 10
POWER_BURST_SECONDS = 120  # ... longer after a power change (warm-up / cool-down)
