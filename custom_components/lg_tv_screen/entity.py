"""Shared device info for the LG TV screen entities."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .tv import LgTvScreenConfigEntry, LgTvScreenRuntime


class LgTvScreenEntity(Entity):
    """Base entity attached to the TV device."""

    _attr_has_entity_name = True

    def __init__(
        self, runtime: LgTvScreenRuntime, entry: LgTvScreenConfigEntry
    ) -> None:
        """Store the runtime and continue platform initialization."""
        super().__init__()
        self._runtime = runtime
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Identify the TV. Share the media-player device when that integration is set up."""
        identifiers = self._runtime.device_identifiers()
        if self._runtime.linked_webostv_unique_id:
            return DeviceInfo(identifiers=identifiers)
        return DeviceInfo(
            identifiers=identifiers,
            manufacturer="LG",
            model=self._runtime.model,
            name=self._entry.title,
            sw_version=self._runtime.webos_version,
        )

    async def async_added_to_hass(self) -> None:
        """Refresh when the TV connects or capture settings change."""
        await super().async_added_to_hass()
        self.async_on_remove(self._runtime.add_listener(self.async_write_ha_state))
