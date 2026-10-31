"""Constants for the LG TV screen integration."""

from __future__ import annotations

from homeassistant.const import Platform

from .capture import (
    CAPTURE_METHODS,
    DEFAULT_HEIGHT,
    DEFAULT_METHOD,
    DEFAULT_WIDTH,
)

DOMAIN = "lg_tv_screen"
WEBOSTV_DOMAIN = "webostv"
DEFAULT_NAME = "LG TV"

CONF_MODEL = "model"
CONF_WEBOS_VERSION = "webos_version"
CONF_WEBOS_ENTRY = "webos_entry_id"
CONF_FRAME_INTERVAL = "frame_interval"
CONF_CAPTURE_WIDTH = "capture_width"
CONF_CAPTURE_HEIGHT = "capture_height"
CONF_CAPTURE_METHOD = "capture_method"

DEFAULT_FRAME_INTERVAL = 10
MIN_FRAME_INTERVAL = 2
MAX_FRAME_INTERVAL = 300
MIN_CAPTURE_EDGE = 160
MAX_CAPTURE_WIDTH = 1920
MAX_CAPTURE_HEIGHT = 1080

CONNECT_TIMEOUT = 10
RECONNECT_INTERVAL = 30
# After a blank video plane, wait before probing every capture method again.
PROTECTED_COOLDOWN = 60

PLATFORMS: list[Platform] = [Platform.CAMERA]

__all__ = [
    "CAPTURE_METHODS",
    "CONF_CAPTURE_HEIGHT",
    "CONF_CAPTURE_METHOD",
    "CONF_CAPTURE_WIDTH",
    "CONF_FRAME_INTERVAL",
    "CONF_MODEL",
    "CONF_WEBOS_ENTRY",
    "CONF_WEBOS_VERSION",
    "CONNECT_TIMEOUT",
    "DEFAULT_FRAME_INTERVAL",
    "DEFAULT_HEIGHT",
    "DEFAULT_METHOD",
    "DEFAULT_NAME",
    "DEFAULT_WIDTH",
    "DOMAIN",
    "MAX_CAPTURE_HEIGHT",
    "MAX_CAPTURE_WIDTH",
    "MAX_FRAME_INTERVAL",
    "MIN_CAPTURE_EDGE",
    "MIN_FRAME_INTERVAL",
    "PLATFORMS",
    "PROTECTED_COOLDOWN",
    "RECONNECT_INTERVAL",
    "WEBOSTV_DOMAIN",
]
