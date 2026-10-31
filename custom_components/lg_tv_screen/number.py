"""Number entity for the screen refresh interval."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MAX_FRAME_INTERVAL, MIN_FRAME_INTERVAL
from .entity import LgTvScreenEntity
from .tv import LgTvScreenConfigEntry, LgTvScreenRuntime

INTERVAL_NUMBER = NumberEntityDescription(
    key="interval",
    translation_key="interval",
    name="Interval",
    native_min_value=MIN_FRAME_INTERVAL,
    native_max_value=MAX_FRAME_INTERVAL,
    native_step=1,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LgTvScreenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the interval control for this TV."""
    async_add_entities([LgTvScreenIntervalNumber(entry.runtime_data, entry)])


class LgTvScreenIntervalNumber(LgTvScreenEntity, NumberEntity):
    """How many seconds the dashboard waits between stills."""

    entity_description = INTERVAL_NUMBER

    def __init__(
        self, runtime: LgTvScreenRuntime, entry: LgTvScreenConfigEntry
    ) -> None:
        """Attach the interval control to the TV."""
        super().__init__(runtime, entry)
        self._attr_unique_id = f"{entry.unique_id}_interval"

    @property
    def native_value(self) -> float:
        """Return the current interval."""
        return float(self._runtime.frame_interval)

    async def async_set_native_value(self, value: float) -> None:
        """Store a new interval. The next picture uses it."""
        self._runtime.set_frame_interval(int(value))
