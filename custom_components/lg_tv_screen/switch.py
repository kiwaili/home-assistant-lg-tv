"""Switch that turns screen capture on and off."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import LgTvScreenEntity
from .tv import LgTvScreenConfigEntry, LgTvScreenRuntime

CAPTURE_SWITCH = SwitchEntityDescription(
    key="capture",
    translation_key="capture",
    name="Capture",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgTvScreenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the capture switch for this TV."""
    async_add_entities([LgTvScreenCaptureSwitch(entry.runtime_data, entry)])


class LgTvScreenCaptureSwitch(LgTvScreenEntity, SwitchEntity):
    """Turn picture capture on or off. The TV socket stays as it was."""

    entity_description = CAPTURE_SWITCH

    def __init__(
        self, runtime: LgTvScreenRuntime, entry: LgTvScreenConfigEntry
    ) -> None:
        """Attach the switch to the TV."""
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.unique_id}_capture"

    @property
    def is_on(self) -> bool:
        """Return whether capture is enabled."""
        return self._runtime.enabled

    async def async_turn_on(self, **kwargs: object) -> None:
        """Start taking stills again."""
        self._runtime.set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Stop asking the TV for pictures."""
        self._runtime.set_enabled(False)
