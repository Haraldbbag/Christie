"""DLP cinema projectors (Christie, Barco, Kinoton)."""

from __future__ import annotations

from typing import Any, Mapping

import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .barco_driver import BarcoDriver
from .christie_driver import ChristieDriver
from .common import ProjectorError
from .const import (
    BRAND_CHRISTIE,
    CONF_BRAND,
    CONF_CHANNELS,
    DEFAULT_PORTS,
    DOMAIN,
    MANUFACTURERS,
)
from .coordinator import ProjectorConfigEntry, ProjectorCoordinator
from .driver import Driver

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SEND_COMMAND = "send_command"
SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("command"): cv.string,
    }
)


def create_driver(data: Mapping[str, Any], options: Mapping[str, Any] | None = None) -> Driver:
    """Driver for a config entry's data (also used by the config flow)."""
    brand = data.get(CONF_BRAND, BRAND_CHRISTIE)
    port = data.get(CONF_PORT, DEFAULT_PORTS[brand])
    if brand == BRAND_CHRISTIE:
        text = (options or {}).get(CONF_CHANNELS) or ""
        names = [x.strip() for x in text.replace(",", "\n").splitlines() if x.strip()]
        return ChristieDriver(
            data[CONF_HOST], port, data.get(CONF_USERNAME), data.get(CONF_PASSWORD), names
        )
    return BarcoDriver(data[CONF_HOST], port, MANUFACTURERS[brand])


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def send_command(call: ServiceCall) -> ServiceResponse:
        device = dr.async_get(hass).async_get(call.data["device_id"])
        coordinator: ProjectorCoordinator | None = None
        if device is not None:
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
                    coordinator = entry.runtime_data
                    break
        if coordinator is None:
            raise ServiceValidationError("Kein eingerichteter Projektor für dieses Gerät.")
        replies = await coordinator.async_send_raw(call.data["command"])
        return {"replies": replies}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        send_command,
        schema=SEND_COMMAND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ProjectorConfigEntry) -> bool:
    driver = create_driver(entry.data, entry.options)
    try:
        info = await driver.device_info()
    except ProjectorError as err:
        await driver.close()
        raise ConfigEntryNotReady(f"{entry.data[CONF_HOST]} nicht erreichbar: {err}") from err

    coordinator = ProjectorCoordinator(hass, entry, driver, info)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await driver.close()
        raise
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ProjectorConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ProjectorConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
