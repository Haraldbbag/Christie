"""Constants for the DLP cinema projector integration."""

DOMAIN = "dlp_cinema_projector"

CONF_BRAND = "brand"
BRAND_CHRISTIE = "christie"
BRAND_BARCO = "barco"
BRAND_KINOTON = "kinoton"  # Barco DP in a Kinoton housing, same protocol

DEFAULT_PORTS = {BRAND_CHRISTIE: 5000, BRAND_BARCO: 43728, BRAND_KINOTON: 43728}
MANUFACTURERS = {BRAND_CHRISTIE: "Christie", BRAND_BARCO: "Barco", BRAND_KINOTON: "Kinoton"}

DEFAULT_SCAN_INTERVAL = 5  # seconds
LIST_REFRESH = 600  # seconds between re-reading channel and test pattern lists

CONF_SCAN_INTERVAL = "scan_interval"
CONF_READ_ONLY = "read_only"
CONF_CHANNELS = "channels"

PATTERN_OFF = "Aus"

BURST_INTERVAL = 1.0  # fast polling after a command ...
BURST_SECONDS = 10
POWER_BURST_SECONDS = 120  # ... longer after a power change (warm-up / cool-down)
