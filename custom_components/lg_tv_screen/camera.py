"""Camera that shows the TV's current picture, as a still or as video."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    async_get_still_stream,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LgTvScreenEntity
from .tv import LgTvScreenConfigEntry, LgTvScreenRuntime

SCREEN_CAMERA = CameraEntityDescription(
    key="screen",
    translation_key="screen",
    name="Screen",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgTvScreenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the screen camera for this TV."""
    async_add_entities([LgTvScreenCamera(entry.runtime_data, entry)])


class LgTvScreenCamera(LgTvScreenEntity, Camera):
    """The TV picture. Live view plays successive JPEGs as MJPEG video.

    ``CameraEntityFeature.STREAM`` stays off. That flag tells the frontend to
    open HLS or WebRTC, and this TV has no stream URL. Without the flag,
    Home Assistant plays ``/api/camera_proxy_stream`` from these stills.
    """

    entity_description = SCREEN_CAMERA
    _attr_content_type = "image/jpeg"

    def __init__(
        self, runtime: LgTvScreenRuntime, entry: LgTvScreenConfigEntry
    ) -> None:
        """Attach the camera to the TV device."""
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.unique_id}_screen"
        self._video_viewers = 0
        self._last_video_frame: bytes | None = None
        self._published: tuple[Any, ...] | None = None

    @property
    def available(self) -> bool:
        """The camera is available while the websocket is connected."""
        return self._runtime.is_connected()

    @property
    def frame_interval(self) -> float:
        """Seconds between pictures, including each frame of a live view."""
        return float(self._runtime.frame_interval)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the capture result without the image itself."""
        attributes: dict[str, Any] = {
            "screen_on": self._runtime.screen_is_on(),
            "webos_version": self._runtime.webos_version,
            "capture_method": self._runtime.capture_method,
            "uses_media_player_connection": self._runtime.shares_connection(),
        }
        if self._runtime.capture_uri:
            attributes["capture_service"] = self._runtime.capture_uri
        if self._runtime.captured_size:
            width, height = self._runtime.captured_size
            attributes["capture_width"] = width
            attributes["capture_height"] = height
        if app_id := self._runtime.current_app_id():
            attributes["app_id"] = app_id
        if self._runtime.last_error:
            attributes["last_error"] = self._runtime.last_error
        return attributes

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a JPEG of the current display.

        The TV chooses the capture size. ``width`` and ``height`` from the
        frontend are ignored so Home Assistant does not scale a protected
        black frame into a different request.
        """
        image = await self._runtime.async_capture()
        self._publish_capture()
        return image

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse:
        """Play the screen as video: one JPEG per interval, for this viewer."""
        self._note_viewer(1)
        try:
            return await async_get_still_stream(
                request, self._video_frame, self.content_type, self.frame_interval
            )
        finally:
            self._note_viewer(-1)

    async def _video_frame(self) -> bytes | None:
        """Return the next JPEG, or the previous one if this capture failed.

        One empty capture would otherwise end the MJPEG response, and the
        card would stay blank until the page was opened again.
        """
        image = await self._runtime.async_capture()
        self._publish_capture()
        if image is not None:
            self._last_video_frame = image
        return self._last_video_frame

    def _note_viewer(self, delta: int) -> None:
        """Mark the camera streaming while at least one live view is open."""
        self._video_viewers = max(0, self._video_viewers + delta)
        streaming = self._video_viewers > 0
        if self.is_streaming == streaming:
            return
        self._attr_is_streaming = streaming
        # ``is_streaming`` is cached. Drop it so the state follows the viewers.
        self.__dict__.pop("is_streaming", None)
        self.async_write_ha_state()

    def _publish_capture(self) -> None:
        """Write state when the capture result changed, not on every frame."""
        signature = (
            self._runtime.last_error,
            self._runtime.capture_method,
            self._runtime.capture_uri,
            self._runtime.captured_size,
            self._runtime.current_app_id(),
            self._runtime.screen_is_on(),
            self._runtime.is_connected(),
            self._runtime.shares_connection(),
        )
        if signature == self._published:
            return
        self._published = signature
        self.async_write_ha_state()
