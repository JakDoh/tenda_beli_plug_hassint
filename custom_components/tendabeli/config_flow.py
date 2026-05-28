"""Single-step configuration flow for Tenda Beli Smart Plug."""

from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.network import async_get_source_ip
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class TendaBeliConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Very small config flow: one form, then create entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Dict[str, Any] | None = None
    ) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            try:
                source_ip = await async_get_source_ip(self.hass)
            except Exception as err:  # pragma: no cover
                _LOGGER.error("Network setup error: %s", err, exc_info=True)
                source_ip = ""

            if not source_ip:
                _LOGGER.warning("Proceeding without detected IP address; hub will attempt default binding.")

            return self.async_create_entry(
                title="Tenda Beli Smart Plug Hub",
                data={
                    "ha_ip": source_ip,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )

    async def async_step_import(
        self, import_config: Dict[str, Any]
    ) -> FlowResult:  # pragma: no cover
        return await self.async_step_user(user_input={})
