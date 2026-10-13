"""Christie cinema projectors."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .client import ChristieClient, ChristieError
from .const import DEFAULT_PORT, DOMAIN
from .coordinator import ChristieConfigEntry, ChristieCoordinator

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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def send_command(call: ServiceCall) -> ServiceResponse:
        device = dr.async_get(hass).async_get(call.data["device_id"])
        coordinator: ChristieCoordinator | None = None
        if device is not None:
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
                    coordinator = entry.runtime_data
                    break
        if coordinator is None:
            raise ServiceValidationError("Kein eingerichteter Christie-Projektor für dieses Gerät.")
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


async def async_setup_entry(hass: HomeAssistant, entry: ChristieConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    client = ChristieClient(
        host,
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
    )
    try:
        info = await client.device_info()
    except ChristieError as err:
        await client.close()
        raise ConfigEntryNotReady(f"{host} nicht erreichbar: {err}") from err

    coordinator = ChristieCoordinator(hass, entry, client, info)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ChristieConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ChristieConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
