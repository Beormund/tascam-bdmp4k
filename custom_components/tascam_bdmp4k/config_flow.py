"""Config flow for Tascam BD-MP4K integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import callback
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, DEFAULT_NAME
from .tascam import TascamController

_LOGGER = logging.getLogger(__name__)

class TascamConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tascam BD-MP4K."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host: str | None = None
        self._mac: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Get IP and MAC and validate the connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            # Standardize MAC format (e.g., aa:bb:cc...)
            mac = dr.format_mac(user_input[CONF_MAC])

            # 1. Set Unique ID to prevent double-entries
            await self.async_set_unique_id(mac)
            self._abort_if_unique_id_configured()

            # 2. Test connectivity
            client = TascamController(host, mac)
            try:
                if not await client.connect():
                    errors["base"] = "cannot_connect"
                else:
                    self._host = host
                    self._mac = mac
                    await client.disconnect()
                    return await self.async_step_name()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error connecting to Tascam")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_MAC): str,
            }),
            errors=errors
        )

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Allow user to set a custom name for the entities."""
        if user_input is not None:
            name = user_input[CONF_NAME]
            return self.async_create_entry(
                title=name,
                data={
                    CONF_HOST: self._host,
                    CONF_MAC: self._mac,
                    CONF_NAME: name,
                },
            )

        return self.async_show_form(
            step_id="name",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            })
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TascamOptionsFlowHandler:
        """Return the options flow handler."""
        return TascamOptionsFlowHandler(config_entry)


class TascamOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle options (settings) for the Tascam after it's installed."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        # self.config_entry is automatically available in OptionsFlow

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options and validate connection before saving."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            # Standardize MAC format just like in the config flow
            mac = dr.format_mac(user_input[CONF_MAC])
            name = user_input[CONF_NAME]

            # 1. Test connectivity with the NEW details
            client = TascamController(host, mac)
            try:
                if not await client.connect():
                    errors["base"] = "cannot_connect"
                else:
                    await client.disconnect()
                    
                    # 2. SUCCESS: Update the existing config entry data.
                    # We update 'data' directly because this integration uses 
                    # OptionsFlowWithReload to refresh the connection.
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, 
                        data={
                            CONF_HOST: host,
                            CONF_MAC: mac,
                            CONF_NAME: name,
                        },
                        title=name
                    )
                    # Create empty entry to satisfy the flow (reload is handled by the parent class)
                    return self.async_create_entry(title="", data={})
                    
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error reconfiguring Tascam")
                errors["base"] = "unknown"

        # Get current values to show as defaults in the UI if user_input is None
        # or if we are returning to the form after an error.
        current_host = user_input.get(CONF_HOST) if user_input else self.config_entry.data.get(CONF_HOST)
        current_mac = user_input.get(CONF_MAC) if user_input else self.config_entry.data.get(CONF_MAC)
        current_name = user_input.get(CONF_NAME) if user_input else self.config_entry.title

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=current_host): str,
                vol.Required(CONF_MAC, default=current_mac): str,
                vol.Required(CONF_NAME, default=current_name): str,
            }),
            errors=errors
        )