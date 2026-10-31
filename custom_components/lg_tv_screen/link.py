"""Find the LG webOS TV integration's already-open client.

A second websocket that uses the same client key disconnects the media player.
Capture must send on the client object that integration already holds, and
must not call ``connect()`` with that key.
"""

from __future__ import annotations

from aiowebostv import WebOsClient

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import WEBOSTV_DOMAIN


def webostv_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    """Return LG webOS TV config entries, loaded or not."""
    return list(hass.config_entries.async_entries(WEBOSTV_DOMAIN))


def matching_webostv_entry(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
    unique_id: str | None = None,
    host: str | None = None,
) -> ConfigEntry | None:
    """Find the LG webOS TV entry for this screen.

    Prefer the entry id chosen in the flow, then the TV's unique id, then the host.
    """
    entries = webostv_entries(hass)
    if entry_id:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
    if unique_id:
        for entry in entries:
            if entry.unique_id == unique_id:
                return entry
    if host:
        for entry in entries:
            if entry.data.get(CONF_HOST) == host:
                return entry
    return None


def shared_client(entry: ConfigEntry) -> WebOsClient | None:
    """Return the live client for a loaded LG webOS TV entry.

    ``runtime_data.client`` is the object the media player uses. Connecting
    again with its key is what drops that player.
    """
    if entry.state is not ConfigEntryState.LOADED:
        return None
    runtime = entry.runtime_data
    client = getattr(runtime, "client", None)
    if isinstance(client, WebOsClient):
        return client
    return None


def entry_host(entry: ConfigEntry) -> str | None:
    """Return the host stored on an entry, if it has one."""
    host = entry.data.get(CONF_HOST)
    if isinstance(host, str) and host:
        return host
    return None
