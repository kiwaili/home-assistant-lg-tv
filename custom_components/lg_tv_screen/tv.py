"""Connection and still-image capture for one LG webOS TV."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
from typing import Any

import aiohttp
from aiowebostv import WebOsClient
from aiowebostv.exceptions import (
    WebOsTvCommandError,
    WebOsTvError,
    WebOsTvPairError,
    WebOsTvResponseTypeError,
    WebOsTvServiceNotFoundError,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_SECRET, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .capture import (
    attempts_for,
    build_capture_payload,
    capture_download_url,
    jpeg_is_blank,
)
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
    DEFAULT_HEIGHT,
    DEFAULT_METHOD,
    DEFAULT_WIDTH,
    MAX_FRAME_INTERVAL,
    MIN_FRAME_INTERVAL,
    DOMAIN,
    PROTECTED_COOLDOWN,
    RECONNECT_INTERVAL,
    WEBOSTV_DOMAIN,
)
from .link import entry_host, matching_webostv_entry, shared_client

_LOGGER = logging.getLogger(__name__)

_JPEG_SOI = b"\xff\xd8"
_INSUFFICIENT_PERMISSIONS = "401 insufficient permissions"
_STOP_ERRORS = {"not_permitted", "timed_out", "download_failed"}
_UNREACHABLE = (
    TimeoutError,
    OSError,
    aiohttp.ClientError,
    WebOsTvError,
)

type LgTvScreenConfigEntry = ConfigEntry[LgTvScreenRuntime]
type _Attempt = tuple[str, str, str]


class LgTvScreenRuntime:
    """Capture one JPEG at a time, on the media player's socket when it exists."""

    def __init__(self, hass: HomeAssistant, entry: LgTvScreenConfigEntry) -> None:
        """Store the entry. The websocket is opened later, and only if we own it."""
        self.hass = hass
        self.entry = entry
        self.host = entry.data.get(CONF_HOST, "")
        self.model: str | None = entry.data.get(CONF_MODEL)
        self.webos_version: str | None = entry.data.get(CONF_WEBOS_VERSION)
        self.linked_webostv_unique_id: str | None = None
        self.last_error: str | None = None
        self.captured_size: tuple[int, int] | None = None
        self.capture_method: str = DEFAULT_METHOD
        self.capture_uri: str | None = None
        self._owned: WebOsClient | None = None
        self._listened: WebOsClient | None = None
        self._using_shared = False
        self._lock = asyncio.Lock()
        self._cache: bytes | None = None
        self._cache_at = 0.0
        self._cache_key: tuple[Any, ...] | None = None
        self._cache_error: str | None = None
        self._winner: _Attempt | None = None
        self._winner_app: str | None = None
        self._logged_attempt: _Attempt | None = None
        self._protected_app: str | None = None
        self._protected_at = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._watch: asyncio.Task[None] | None = None
        self._reauth_started = False
        self._closing = False
        self._fallback_logged: tuple[int, int] | None = None

    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for connection and power changes."""
        self._listeners.append(update)

        def _remove() -> None:
            if update in self._listeners:
                self._listeners.remove(update)

        return _remove

    def shares_connection(self) -> bool:
        """Return whether capture is using the LG webOS TV integration's socket."""
        return self._shared_client() is not None

    def device_identifiers(self) -> set[tuple[str, str]]:
        """Attach the camera to the media-player device when that TV is set up."""
        linked = self._linked_unique_id()
        if linked:
            return {(WEBOSTV_DOMAIN, linked)}
        unique_id = self.entry.unique_id or self.entry.entry_id
        return {(DOMAIN, unique_id)}

    @property
    def enabled(self) -> bool:
        """Return whether picture capture is turned on."""
        return bool(self.entry.options.get(CONF_ENABLED, DEFAULT_ENABLED))

    @property
    def frame_interval(self) -> int:
        """Return the refresh interval in seconds."""
        try:
            value = int(self.entry.options.get(CONF_FRAME_INTERVAL, DEFAULT_FRAME_INTERVAL))
        except (TypeError, ValueError):
            return DEFAULT_FRAME_INTERVAL
        return min(MAX_FRAME_INTERVAL, max(MIN_FRAME_INTERVAL, value))

    def set_enabled(self, enabled: bool) -> None:
        """Turn picture capture on or off without closing the TV socket."""
        if enabled:
            self._cache = None
            self._cache_key = None
        self._update_option(CONF_ENABLED, enabled)

    def set_frame_interval(self, seconds: int) -> None:
        """Set how many seconds the dashboard waits between stills."""
        value = min(MAX_FRAME_INTERVAL, max(MIN_FRAME_INTERVAL, int(seconds)))
        self._cache_key = None
        self._update_option(CONF_FRAME_INTERVAL, value)

    def _update_option(self, key: str, value: Any) -> None:
        """Store one option and refresh entities. Other options stay as they are."""
        options = dict(self.entry.options)
        if options.get(key) == value:
            return
        options[key] = value
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self._notify()

    def is_connected(self) -> bool:
        """Return whether the webOS websocket is up."""
        client = self._current_client()
        return client is not None and client.is_connected()

    def screen_is_on(self) -> bool:
        """Return whether the TV is on and the panel is not in screen-off."""
        client = self._current_client()
        if client is None or not client.is_connected():
            return False
        state = client.tv_state
        if not state.power_state and not state.current_app_id:
            return True
        return bool(state.is_on and state.is_screen_on)

    def current_app_id(self) -> str | None:
        """Return the foreground app id, when the socket is up."""
        client = self._current_client()
        if client is None or not client.is_connected():
            return None
        return client.tv_state.current_app_id or None

    async def async_connect(self) -> None:
        """Use the media player's socket, or open our own if that TV is not set up."""
        async with self._lock:
            await self._activate_locked(connect_owned=True)

    async def async_capture(self) -> bytes | None:
        """Capture the current picture, including the video plane when the TV allows it."""
        async with self._lock:
            if self._closing:
                return None
            if not self.enabled:
                self.last_error = "disabled"
                return None
            try:
                client = await self._activate_locked(connect_owned=True)
            except WebOsTvPairError:
                return None
            if client is None or not client.is_connected():
                self.last_error = "not_connected"
                self._cache = None
                return None
            if not self.screen_is_on():
                self.last_error = "screen_off"
                self._cache = None
                return None

            app_id = client.tv_state.current_app_id or ""
            if self._protected_hold(app_id):
                self.last_error = "protected"
                return self._cache

            key = self._capture_key(app_id)
            cached = self._fresh_cache(key)
            if cached is not None:
                self.last_error = self._cache_error
                return cached

            width = int(self.entry.options.get(CONF_CAPTURE_WIDTH, DEFAULT_WIDTH))
            height = int(self.entry.options.get(CONF_CAPTURE_HEIGHT, DEFAULT_HEIGHT))
            method = str(self.entry.options.get(CONF_CAPTURE_METHOD, DEFAULT_METHOD))
            sizes = [(width, height)]
            if (width, height) != (DEFAULT_WIDTH, DEFAULT_HEIGHT):
                sizes.append((DEFAULT_WIDTH, DEFAULT_HEIGHT))

            last_error = "refused"
            for size in sizes:
                image, error = await self._probe(
                    client, size[0], size[1], attempts_for(method), app_id
                )
                if error == "protected" and image is not None:
                    self.last_error = "protected"
                    self._store_cache(key, image, "protected")
                    return image
                if image is not None and error is None:
                    self.last_error = None
                    self._store_cache(key, image, None)
                    if size != (width, height) and self._fallback_logged != (width, height):
                        self._fallback_logged = (width, height)
                        _LOGGER.warning(
                            "The TV refused %sx%s and returned %sx%s instead. "
                            "Set the capture size to %sx%s",
                            width,
                            height,
                            size[0],
                            size[1],
                            size[0],
                            size[1],
                        )
                    return image
                if error in _STOP_ERRORS:
                    self.last_error = error
                    return None
                if error:
                    last_error = error

            self.last_error = last_error
            return None

    async def async_close(self) -> None:
        """Stop watching. Close only a socket this integration opened."""
        self._closing = True
        watch = self._watch
        self._watch = None
        if watch is not None:
            watch.cancel()
            try:
                await watch
            except asyncio.CancelledError:
                pass
        self._drop_listener()
        owned = self._owned
        self._owned = None
        self._using_shared = False
        if owned is not None:
            await owned.disconnect()

    def async_start_watch(self) -> None:
        """Reconnect our own socket, or follow the media player's socket."""
        if self._watch is None:
            self._watch = self.hass.async_create_background_task(
                self._async_watch(),
                name="lg_tv_screen reconnect",
            )

    async def _async_watch(self) -> None:
        """Keep a picture source without opening the media player's key twice."""
        try:
            while not self._closing:
                await asyncio.sleep(RECONNECT_INTERVAL)
                if self._closing:
                    return
                if self._shared_client() is not None:
                    async with self._lock:
                        await self._activate_locked(connect_owned=False)
                    self._notify()
                    continue
                if self._owned is not None and self._owned.is_connected():
                    continue
                try:
                    await self.async_connect()
                except WebOsTvPairError:
                    self._start_reauth()
                    return
                except _UNREACHABLE:
                    _LOGGER.debug("TV is still unreachable")
                else:
                    if self.is_connected():
                        _LOGGER.info("Reconnected to the TV at %s", self.host)
                    self._notify()
        except asyncio.CancelledError:
            raise

    async def _activate_locked(self, *, connect_owned: bool) -> WebOsClient | None:
        """Select the shared client, or connect a client this integration owns.

        Caller holds the lock. The shared client is never passed to ``connect()``.
        """
        shared = self._shared_client()
        if shared is not None:
            if self._owned is not None:
                owned = self._owned
                self._owned = None
                if self._listened is owned:
                    self._drop_listener()
                await owned.disconnect()
            await self._listen(shared)
            self._using_shared = True
            if shared.is_connected():
                self._remember_tv_info(shared)
            return shared

        self._using_shared = False
        secret = self.entry.data.get(CONF_CLIENT_SECRET)
        if not secret or not self.host:
            return None
        if self._owned is None:
            self._owned = WebOsClient(
                self.host,
                secret,
                connect_timeout=CONNECT_TIMEOUT,
                client_session=async_get_clientsession(self.hass),
            )
        await self._listen(self._owned)
        if self._owned.is_connected() or not connect_owned:
            if self._owned.is_connected():
                self._remember_tv_info(self._owned)
            return self._owned
        try:
            await self._owned.connect()
        except WebOsTvPairError:
            self.last_error = "not_paired"
            self._start_reauth()
            raise
        except _UNREACHABLE:
            self.last_error = "not_connected"
            return self._owned
        self._remember_tv_info(self._owned)
        _LOGGER.info(
            "Connected to %s webOS %s at %s",
            self.model or "LG TV",
            self.webos_version or "unknown",
            self.host,
        )
        return self._owned

    async def _probe(
        self,
        client: WebOsClient,
        width: int,
        height: int,
        attempts: tuple[_Attempt, ...],
        app_id: str,
    ) -> tuple[bytes | None, str | None]:
        """Try capture calls until one returns a picture that is not a blank video plane."""
        ordered = attempts
        if self._winner and self._winner_app == app_id and self._winner in attempts:
            ordered = (self._winner, *(item for item in attempts if item != self._winner))

        not_found = 0
        refused = 0
        download_failed = False
        blank: bytes | None = None
        for attempt in ordered:
            uri, method, image_format = attempt
            payload = build_capture_payload(width, height, method, image_format)
            try:
                response = await client.request(uri, payload)
            except WebOsTvServiceNotFoundError:
                not_found += 1
                continue
            except WebOsTvResponseTypeError as err:
                if _insufficient_permissions(err):
                    return None, "not_permitted"
                refused += 1
                continue
            except WebOsTvCommandError:
                refused += 1
                continue
            except TimeoutError:
                return None, "timed_out"

            url = capture_download_url(response, self.host, str(payload["path"]))
            try:
                data = await self._download(url)
            except (TimeoutError, aiohttp.ClientError, OSError):
                _LOGGER.debug("Could not download %s %s", uri, method)
                download_failed = True
                continue
            if not data.startswith(_JPEG_SOI):
                refused += 1
                continue

            self.captured_size = (width, height)
            self.capture_method = method
            self.capture_uri = uri
            if jpeg_is_blank(data):
                blank = data
                continue

            self._winner = attempt
            self._winner_app = app_id
            self._protected_app = None
            if self._logged_attempt != attempt:
                self._logged_attempt = attempt
                _LOGGER.info("Capturing with %s method %s", uri, method)
            return data, None

        if blank is not None:
            self._protected_app = app_id or None
            self._protected_at = asyncio.get_running_loop().time()
            return blank, "protected"
        if download_failed and not refused and not not_found:
            return None, "download_failed"
        if not_found and not refused:
            return None, "not_supported"
        return None, "refused"

    async def _download(self, url: str) -> bytes:
        """Download the JPEG. Retry once; the 2019 set can lag behind the URI."""
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=10)
        for attempt in (1, 2):
            async with session.get(url, ssl=False, timeout=timeout) as response:
                if response.status == 404 and attempt == 1:
                    await asyncio.sleep(0.5)
                    continue
                response.raise_for_status()
                return await response.read()
        raise aiohttp.ClientError("capture file was not available")

    def _shared_client(self) -> WebOsClient | None:
        """Return the media player's client when that integration is connected."""
        entry = matching_webostv_entry(
            self.hass,
            entry_id=self.entry.data.get(CONF_WEBOS_ENTRY),
            unique_id=self.entry.unique_id,
            host=self.host or self.entry.data.get(CONF_HOST),
        )
        if entry is None:
            self.linked_webostv_unique_id = None
            return None
        if entry.unique_id:
            self.linked_webostv_unique_id = entry.unique_id
        host = entry_host(entry)
        if host:
            self.host = host
        return shared_client(entry)

    def _current_client(self) -> WebOsClient | None:
        """Return the shared client, or our own if the media player is not set up."""
        shared = self._shared_client()
        if shared is not None:
            return shared
        return self._owned

    def _linked_unique_id(self) -> str | None:
        """Remember the LG webOS TV device id, even before its socket is up."""
        if self.linked_webostv_unique_id:
            return self.linked_webostv_unique_id
        entry = matching_webostv_entry(
            self.hass,
            entry_id=self.entry.data.get(CONF_WEBOS_ENTRY),
            unique_id=self.entry.unique_id,
            host=self.host or self.entry.data.get(CONF_HOST),
        )
        if entry is None or not entry.unique_id:
            return None
        self.linked_webostv_unique_id = entry.unique_id
        return entry.unique_id

    async def _listen(self, client: WebOsClient) -> None:
        """Follow power updates for this client object only."""
        if self._listened is client:
            return
        self._drop_listener()
        await client.register_state_update_callback(self._on_state)
        self._listened = client

    def _drop_listener(self) -> None:
        """Remove our callback. Do not clear the media player's callbacks."""
        if self._listened is None:
            return
        self._listened.unregister_state_update_callback(self._on_state)
        self._listened = None

    def _capture_key(self, app_id: str) -> tuple[Any, ...]:
        """Identify the settings and app that produced the cached JPEG."""
        return (
            self.host,
            int(self.entry.options.get(CONF_CAPTURE_WIDTH, DEFAULT_WIDTH)),
            int(self.entry.options.get(CONF_CAPTURE_HEIGHT, DEFAULT_HEIGHT)),
            str(self.entry.options.get(CONF_CAPTURE_METHOD, DEFAULT_METHOD)),
            app_id,
        )

    def _fresh_cache(self, key: tuple[Any, ...]) -> bytes | None:
        """Return the cached JPEG when it is still inside the refresh interval."""
        if self._cache is None or self._cache_key != key:
            return None
        interval = float(self.frame_interval)
        if asyncio.get_running_loop().time() - self._cache_at >= interval:
            return None
        return self._cache

    def _protected_hold(self, app_id: str) -> bool:
        """Skip another full probe while this app's video plane stays blank."""
        if not app_id or self._protected_app != app_id or self._cache is None:
            return False
        return asyncio.get_running_loop().time() - self._protected_at < PROTECTED_COOLDOWN

    def _store_cache(self, key: tuple[Any, ...], image: bytes, error: str | None) -> None:
        """Remember the last JPEG and whether it was a blank protected frame."""
        self._cache = image
        self._cache_key = key
        self._cache_error = error
        self._cache_at = asyncio.get_running_loop().time()

    def _remember_tv_info(self, client: WebOsClient) -> None:
        """Keep the model and webOS release for the device registry."""
        info = client.tv_info
        if model := info.system.get("modelName"):
            self.model = str(model)
        if version := info.hello.get("deviceOSReleaseVersion"):
            self.webos_version = str(version)

    async def _on_state(self, _state: Any) -> None:
        """Forward power and app updates to the camera entity."""
        self._notify()

    def _notify(self) -> None:
        """Tell listeners that availability or attributes changed."""
        for update in list(self._listeners):
            try:
                update()
            except Exception:
                _LOGGER.exception("Screen listener failed")

    def _start_reauth(self) -> None:
        """Ask Home Assistant to pair again. Never for the media player's key."""
        if self._reauth_started or self._closing or self._using_shared:
            return
        if not self.entry.data.get(CONF_CLIENT_SECRET):
            return
        self._reauth_started = True
        self.entry.async_start_reauth(self.hass)


def _insufficient_permissions(err: WebOsTvResponseTypeError) -> bool:
    """Return whether the TV refused the call for lack of permission."""
    response = err.args[0] if err.args else None
    if isinstance(response, dict):
        return response.get("error") == _INSUFFICIENT_PERMISSIONS
    return False
