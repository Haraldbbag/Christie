"""Config flow for Christie projectors."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import ChristieAuthError, ChristieClient, ChristieError, DeviceInfo
from .const import (
    CONF_CHANNELS,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ChristieConfigEntry

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(data: dict[str, Any]) -> DeviceInfo:
    client = ChristieClient(
        data[CONF_HOST], data[CONF_PORT], data.get(CONF_USERNAME), data.get(CONF_PASSWORD)
    )
    try:
        return await client.device_info()
    finally:
        await client.close()


def _unique_id(info: DeviceInfo, host: str) -> str:
    return info.serial.strip() if info.serial and info.serial.strip() else host


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {
        CONF_HOST: user_input[CONF_HOST].strip(),
        CONF_PORT: user_input[CONF_PORT],
    }
    if user_input.get(CONF_USERNAME):
        data[CONF_USERNAME] = user_input[CONF_USERNAME]
        data[CONF_PASSWORD] = user_input.get(CONF_PASSWORD, "")
    return data


class ChristieConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(entry: ChristieConfigEntry) -> OptionsFlow:
        return ChristieOptionsFlow()

    async def _try(self, data: dict[str, Any], errors: dict[str, str]) -> DeviceInfo | None:
        try:
            return await _validate(data)
        except ChristieAuthError as err:
            _LOGGER.debug("Login to %s failed: %s", data[CONF_HOST], err)
            errors["base"] = "invalid_auth"
        except ChristieError as err:
            _LOGGER.debug("Cannot connect to %s: %s", data[CONF_HOST], err)
            errors["base"] = "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            self._async_abort_entries_match({CONF_HOST: data[CONF_HOST]})
            if (info := await self._try(data, errors)) is not None:
                await self.async_set_unique_id(_unique_id(info, data[CONF_HOST]))
                self._abort_if_unique_id_configured(updates=data)
                name = user_input.get(CONF_NAME) or f"Christie {data[CONF_HOST]}"
                return self.async_create_entry(title=name, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.Coerce(int),
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): _PASSWORD,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            if (info := await self._try(data, errors)) is not None:
                if entry.unique_id != entry.data[CONF_HOST]:
                    await self.async_set_unique_id(_unique_id(info, data[CONF_HOST]))
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT): vol.Coerce(int),
                vol.Optional(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): _PASSWORD,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or dict(entry.data)),
            errors=errors,
        )


class ChristieOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                vol.Required(CONF_READ_ONLY, default=opts.get(CONF_READ_ONLY, False)): bool,
                vol.Optional(
                    CONF_CHANNELS,
                    description={"suggested_value": opts.get(CONF_CHANNELS, "")},
                ): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
