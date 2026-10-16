"""Config flow for DLP cinema projectors."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import create_driver
from .common import ProjectorAuthError, ProjectorError, ProjectorInfo
from .const import (
    BRAND_BARCO,
    BRAND_CHRISTIE,
    BRAND_KINOTON,
    CONF_BRAND,
    CONF_CHANNELS,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    CONF_VISIBLE_CHANNELS,
    CONF_VISIBLE_PATTERNS,
    DEFAULT_PORTS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURERS,
)
from .coordinator import ProjectorConfigEntry

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _validate(data: dict[str, Any]) -> ProjectorInfo:
    driver = create_driver(data)
    try:
        return await driver.device_info()
    finally:
        await driver.close()


def _unique_id(info: ProjectorInfo, host: str) -> str:
    return info.serial.strip() if info.serial and info.serial.strip() else host


def _clean(brand: str, user_input: dict[str, Any]) -> dict[str, Any]:
    data = {
        CONF_BRAND: brand,
        CONF_HOST: user_input[CONF_HOST].strip(),
        CONF_PORT: user_input[CONF_PORT],
    }
    if brand == BRAND_CHRISTIE and user_input.get(CONF_USERNAME):
        data[CONF_USERNAME] = user_input[CONF_USERNAME]
        data[CONF_PASSWORD] = user_input.get(CONF_PASSWORD, "")
    return data


def _schema(brand: str, with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORTS[brand]): vol.Coerce(int),
    }
    if with_name:
        fields[vol.Optional(CONF_NAME)] = str
    if brand == BRAND_CHRISTIE:
        fields[vol.Optional(CONF_USERNAME)] = str
        fields[vol.Optional(CONF_PASSWORD)] = _PASSWORD
    return vol.Schema(fields)


class ProjectorConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(entry: ProjectorConfigEntry) -> OptionsFlow:
        return ProjectorOptionsFlow()

    async def _try(self, data: dict[str, Any], errors: dict[str, str]) -> ProjectorInfo | None:
        try:
            return await _validate(data)
        except ProjectorAuthError as err:
            _LOGGER.debug("Login to %s failed: %s", data[CONF_HOST], err)
            errors["base"] = "invalid_auth"
        except ProjectorError as err:
            _LOGGER.debug("Cannot connect to %s: %s", data[CONF_HOST], err)
            errors["base"] = "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[BRAND_CHRISTIE, BRAND_BARCO, BRAND_KINOTON]
        )

    async def async_step_christie(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_brand(BRAND_CHRISTIE, user_input)

    async def async_step_barco(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_brand(BRAND_BARCO, user_input)

    async def async_step_kinoton(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_brand(BRAND_KINOTON, user_input)

    async def _async_step_brand(
        self, brand: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(brand, user_input)
            self._async_abort_entries_match({CONF_HOST: data[CONF_HOST]})
            if (info := await self._try(data, errors)) is not None:
                await self.async_set_unique_id(_unique_id(info, data[CONF_HOST]))
                self._abort_if_unique_id_configured(updates=data)
                name = user_input.get(CONF_NAME) or f"{MANUFACTURERS[brand]} {data[CONF_HOST]}"
                # Barco/Kinoton start read-only until tested on the real projector.
                options = {CONF_READ_ONLY: brand != BRAND_CHRISTIE}
                return self.async_create_entry(title=name, data=data, options=options)
        return self.async_show_form(
            step_id=brand,
            data_schema=self.add_suggested_values_to_schema(_schema(brand, True), user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        brand = entry.data.get(CONF_BRAND, BRAND_CHRISTIE)
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(brand, user_input)
            if (info := await self._try(data, errors)) is not None:
                if entry.unique_id != entry.data[CONF_HOST]:
                    await self.async_set_unique_id(_unique_id(info, data[CONF_HOST]))
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _schema(brand, False), user_input or dict(entry.data)
            ),
            errors=errors,
        )


class ProjectorOptionsFlow(OptionsFlow):
    """Menu: general settings, visible channels, visible test patterns."""

    def _save(self, values: dict[str, Any]) -> ConfigFlowResult:
        # The options flow replaces all options: keep the ones of the other pages.
        return self.async_create_entry(data={**self.config_entry.options, **values})

    def _lists(self) -> tuple[list[str], list[str]] | None:
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED or entry.runtime_data.data is None:
            return None
        data = entry.runtime_data.data
        return list(data.channels), list(data.patterns)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = ["general", "visible_channels"]
        entry = self.config_entry
        if entry.state is ConfigEntryState.LOADED and entry.runtime_data.driver.has_patterns:
            options.append("visible_patterns")
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_general(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(user_input)
        opts = self.config_entry.options
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
            vol.Required(CONF_READ_ONLY, default=opts.get(CONF_READ_ONLY, False)): bool,
        }
        if self.config_entry.data.get(CONF_BRAND, BRAND_CHRISTIE) == BRAND_CHRISTIE:
            fields[
                vol.Optional(CONF_CHANNELS, description={"suggested_value": opts.get(CONF_CHANNELS, "")})
            ] = TextSelector(TextSelectorConfig(multiline=True))
        return self.async_show_form(step_id="general", data_schema=vol.Schema(fields))

    async def async_step_visible_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._checkboxes("visible_channels", CONF_VISIBLE_CHANNELS, 0, user_input)

    async def async_step_visible_patterns(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._checkboxes("visible_patterns", CONF_VISIBLE_PATTERNS, 1, user_input)

    async def _checkboxes(
        self, step_id: str, key: str, index: int, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        lists = self._lists()
        if lists is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            return self._save({key: list(user_input.get(key, []))})
        selected = list(self.config_entry.options.get(key, []))
        items = lists[index]
        # Keep checked names the projector no longer reports, so they can be unchecked.
        items += [x for x in selected if x not in items]
        if not items:
            return self.async_abort(reason="no_items")
        schema = vol.Schema(
            {
                vol.Optional(key, default=selected): SelectSelector(
                    SelectSelectorConfig(
                        options=items, multiple=True, mode=SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders={"count": str(len(lists[index]))},
        )
