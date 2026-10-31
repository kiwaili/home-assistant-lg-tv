"""Camera that shows the TV's current picture."""

from __future__ import annotations

from typing import Any

from homeassistant.components.camera import Camera, CameraEntityDescription
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
    """A still of the TV picture, refreshed on each request."""

    entity_description = SCREEN_CAMERA
    _attr_content_type = "image/jpeg"

    def __init__(
        self, runtime: LgTvScreenRuntime, entry: LgTvScreenConfigEntry
    ) -> None:
        """Attach the camera to the TV device."""
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.unique_id}_screen"

    @property
    def available(self) -> bool:
        """The camera is available while the websocket is connected."""
        return self._runtime.is_connected()

    @property
    def frame_interval(self) -> float:
        """Seconds the frontend should wait between stills."""
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
        self.async_write_ha_state()
        return image
