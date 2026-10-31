"""Config flow for LG TV screen capture."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any, Self
from urllib.parse import urlparse

import aiohttp
from aiowebostv import WebOsClient
from aiowebostv.exceptions import WebOsTvError, WebOsTvPairError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_FRIENDLY_NAME,
    ATTR_UPNP_UDN,
    SsdpServiceInfo,
)

from .capture import CAPTURE_METHODS, DEFAULT_HEIGHT, DEFAULT_METHOD, DEFAULT_WIDTH
from .const import (
    CONF_CAPTURE_HEIGHT,
    CONF_CAPTURE_METHOD,
    CONF_CAPTURE_WIDTH,
    CONF_ENABLED,
    CONF_FRAME_INTERVAL,
    CONF_MODEL,
    CONF_WEBOS_ENTRY,
    CONF_WEBOS_VERSION,
    CONNECT_TIMEOUT,
    DEFAULT_ENABLED,
    DEFAULT_FRAME_INTERVAL,
    DEFAULT_NAME,
    DOMAIN,
    MAX_CAPTURE_HEIGHT,
    MAX_CAPTURE_WIDTH,
    MAX_FRAME_INTERVAL,
    MIN_CAPTURE_EDGE,
    MIN_FRAME_INTERVAL,
)
from .link import entry_host, matching_webostv_entry, webostv_entries
from .tv import LgTvScreenConfigEntry

_PAIR_NEW = "pair_new"

_LOGGER = logging.getLogger(__name__)

_CONNECT_FAILURES = (
    TimeoutError,
    OSError,
    aiohttp.ClientError,
    WebOsTvError,
)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
    }
)


@dataclass(frozen=True, slots=True)
class PairedTv:
    """Facts collected while the pairing socket is open."""

    client_key: str
    uuid: str
    model: str | None
    webos_version: str | None


def _entry_data(host: str, paired: PairedTv) -> dict[str, Any]:
    """Build config-entry data. The client key is stored as a secret."""
    data: dict[str, Any] = {
        CONF_HOST: host,
        CONF_CLIENT_SECRET: paired.client_key,
    }
    if paired.model:
        data[CONF_MODEL] = paired.model
    if paired.webos_version:
        data[CONF_WEBOS_VERSION] = paired.webos_version
    return data


def _title(model: str | None, fallback: str | None) -> str:
    """Prefer the TV's model name, for example LG 32LM6300PCB."""
    if model:
        return f"LG {model}"
    return fallback or DEFAULT_NAME


async def async_pair_tv(
    hass: HomeAssistant, host: str, client_key: str | None
) -> PairedTv:
    """Pair or reconnect, then close the socket so setup can open its own."""
    client = WebOsClient(
        host,
        client_key,
        connect_timeout=CONNECT_TIMEOUT,
        client_session=async_get_clientsession(hass),
    )
    try:
        await client.connect()
        key = client.client_key
        uuid = client.tv_info.hello.get("deviceUUID")
        model = client.tv_info.system.get("modelName")
        version = client.tv_info.hello.get("deviceOSReleaseVersion")
    finally:
        await client.disconnect()

    if not key:
        raise WebOsTvPairError("TV did not return a client key")
    if not uuid:
        raise WebOsTvError("TV did not return a device id")
    _LOGGER.info("Paired %s webOS %s at %s", model or "LG TV", version or "unknown", host)
    return PairedTv(
        client_key=key,
        uuid=str(uuid),
        model=str(model) if model else None,
        webos_version=str(version) if version else None,
    )


class LgTvScreenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair with an LG webOS TV and create a screen-capture device."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with no discovered host."""
        super().__init__()
        self._host = ""
        self._name = ""
        self._webostv_entry_id = ""

    def _set_flow_title(self) -> None:
        """Name the flow. Discovery may replace this with the TV's name."""
        self.context["title_placeholders"] = {"name": self._name or DEFAULT_NAME}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: LgTvScreenConfigEntry,
    ) -> LgTvScreenOptionsFlow:
        """Return the capture options flow."""
        return LgTvScreenOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prefer a TV already paired by the LG webOS TV integration."""
        self._set_flow_title()
        choices = {
            entry.entry_id: entry.title for entry in webostv_entries(self.hass)
        }
        if not choices:
            return await self.async_step_manual()
        choices[_PAIR_NEW] = "Pair a TV that is not in LG webOS TV"
        if user_input is not None:
            selected = user_input[CONF_WEBOS_ENTRY]
            if selected == _PAIR_NEW:
                return await self.async_step_manual()
            return await self._async_create_shared_entry(selected)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_WEBOS_ENTRY): vol.In(choices)}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair a TV that is not already in the LG webOS TV integration."""
        self._set_flow_title()
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: self._host})
            return await self.async_step_pairing()

        return self.async_show_form(step_id="manual", data_schema=_USER_SCHEMA)

    async def _async_create_shared_entry(self, entry_id: str) -> ConfigFlowResult:
        """Create a screen entry that uses the media player's websocket."""
        source = next(
            (entry for entry in webostv_entries(self.hass) if entry.entry_id == entry_id),
            None,
        )
        if source is None:
            return self.async_abort(reason="cannot_connect")
        host = entry_host(source) or ""
        target_id = source.unique_id or source.entry_id
        if self.unique_id != target_id:
            await self.async_set_unique_id(target_id)
        self._abort_if_unique_id_configured()
        self._async_abort_entries_match({CONF_WEBOS_ENTRY: source.entry_id})
        if host:
            self._async_abort_entries_match({CONF_HOST: host})
        data: dict[str, Any] = {CONF_WEBOS_ENTRY: source.entry_id}
        if host:
            data[CONF_HOST] = host
        self._name = source.title
        self._set_flow_title()
        return self.async_create_entry(title=source.title, data=data)

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Connect after the user is ready to accept the prompt on the TV."""
        self._set_flow_title()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                paired = await async_pair_tv(self.hass, self._host, None)
            except WebOsTvPairError:
                errors["base"] = "error_pairing"
            except _CONNECT_FAILURES:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error pairing with %s", self._host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(paired.uuid, raise_on_progress=False)
                self._abort_if_unique_id_configured({CONF_HOST: self._host})
                title = _title(paired.model, self._name)
                return self.async_create_entry(
                    title=title, data=_entry_data(self._host, paired)
                )

        return self.async_show_form(step_id="pairing", errors=errors)

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Offer a TV found on the LAN."""
        if not discovery_info.ssdp_location:
            return self.async_abort(reason="cannot_connect")
        host = urlparse(discovery_info.ssdp_location).hostname
        if not host:
            return self.async_abort(reason="cannot_connect")

        self._host = host
        friendly = discovery_info.upnp.get(ATTR_UPNP_FRIENDLY_NAME, DEFAULT_NAME)
        self._name = friendly.replace("[LG]", "LG").strip() or DEFAULT_NAME
        uuid = discovery_info.upnp.get(ATTR_UPNP_UDN, "")
        uuid = uuid.removeprefix("uuid:")

        self._async_abort_entries_match({CONF_HOST: host})
        if self.hass.config_entries.flow.async_has_matching_flow(self):
            return self.async_abort(reason="already_in_progress")

        existing = matching_webostv_entry(
            self.hass, unique_id=uuid or None, host=host
        )
        self._set_flow_title()
        if existing is not None:
            self._webostv_entry_id = existing.entry_id
            self._name = existing.title or self._name
            return await self.async_step_attach()

        if uuid:
            await self.async_set_unique_id(uuid)
            self._abort_if_unique_id_configured({CONF_HOST: host})
        return await self.async_step_pairing()

    async def async_step_attach(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm using the LG webOS TV connection instead of pairing again."""
        self._set_flow_title()
        if user_input is not None:
            return await self._async_create_shared_entry(self._webostv_entry_id)
        return self.async_show_form(step_id="attach")

    def is_matching(self, other_flow: Self) -> bool:
        """Match discovery flows for the same host."""
        return other_flow._host == self._host

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start pairing again after the TV rejected the saved key."""
        if not entry_data.get(CONF_CLIENT_SECRET):
            return self.async_abort(reason="use_webostv_reauth")
        self._host = entry_data[CONF_HOST]
        self._name = self._get_reauth_entry().title
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait until the user can accept a new prompt."""
        self._set_flow_title()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                paired = await async_pair_tv(self.hass, self._host, None)
            except WebOsTvPairError:
                errors["base"] = "error_pairing"
            except _CONNECT_FAILURES:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error re-pairing with %s", self._host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(paired.uuid)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data=_entry_data(self._host, paired),
                )

        return self.async_show_form(step_id="reauth_confirm", errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update the host when the TV's IP address changes."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_WEBOS_ENTRY):
            return await self.async_step_reconfigure_shared()
        errors: dict[str, str] = {}
        self._name = entry.title
        self._set_flow_title()
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                paired = await async_pair_tv(
                    self.hass, host, entry.data.get(CONF_CLIENT_SECRET)
                )
            except WebOsTvPairError:
                errors["base"] = "error_pairing"
            except _CONNECT_FAILURES:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error updating host to %s", host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(paired.uuid)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                for existing in self._async_current_entries():
                    if (
                        existing.entry_id != entry.entry_id
                        and existing.data.get(CONF_HOST) == host
                    ):
                        return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    data=_entry_data(host, paired),
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): cv.string,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_shared(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """This screen follows the LG webOS TV integration's address."""
        self._name = self._get_reconfigure_entry().title
        self._set_flow_title()
        if user_input is not None:
            return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(step_id="reconfigure_shared")


class LgTvScreenOptionsFlow(OptionsFlowWithReload):
    """Choose how often, and at what size, the still is taken."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save capture options."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLED,
                        default=options.get(CONF_ENABLED, DEFAULT_ENABLED),
                    ): cv.boolean,
                    vol.Required(
                        CONF_FRAME_INTERVAL,
                        default=options.get(CONF_FRAME_INTERVAL, DEFAULT_FRAME_INTERVAL),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_FRAME_INTERVAL, max=MAX_FRAME_INTERVAL),
                    ),
                    vol.Required(
                        CONF_CAPTURE_WIDTH,
                        default=options.get(CONF_CAPTURE_WIDTH, DEFAULT_WIDTH),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_CAPTURE_EDGE, max=MAX_CAPTURE_WIDTH),
                    ),
                    vol.Required(
                        CONF_CAPTURE_HEIGHT,
                        default=options.get(CONF_CAPTURE_HEIGHT, DEFAULT_HEIGHT),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_CAPTURE_EDGE, max=MAX_CAPTURE_HEIGHT),
                    ),
                    vol.Required(
                        CONF_CAPTURE_METHOD,
                        default=options.get(CONF_CAPTURE_METHOD, DEFAULT_METHOD),
                    ): vol.In(CAPTURE_METHODS),
                }
            ),
        )
