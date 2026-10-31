"""LG webOS TV screen capture for Home Assistant."""

from __future__ import annotations

import logging

import aiohttp
from aiowebostv.exceptions import WebOsTvError, WebOsTvPairError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import PLATFORMS
from .tv import LgTvScreenRuntime

_LOGGER = logging.getLogger(__name__)

type LgTvScreenConfigEntry = ConfigEntry[LgTvScreenRuntime]

_STARTUP_FAILURES = (
    TimeoutError,
    OSError,
    aiohttp.ClientError,
    WebOsTvError,
)


async def async_setup_entry(hass: HomeAssistant, entry: LgTvScreenConfigEntry) -> bool:
    """Connect to the TV and create the screen camera."""
    runtime = LgTvScreenRuntime(hass, entry)
    try:
        await runtime.async_connect()
    except WebOsTvPairError as err:
        await runtime.async_close()
        raise ConfigEntryAuthFailed("TV rejected the saved pairing") from err
    except _STARTUP_FAILURES:
        _LOGGER.warning(
            "Could not reach the TV at %s. The camera will connect when it is on",
            runtime.host,
        )

    entry.runtime_data = runtime
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await runtime.async_close()
        raise
    runtime.async_start_watch()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LgTvScreenConfigEntry) -> bool:
    """Remove the camera and close the TV socket."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_close()
    return unload_ok
