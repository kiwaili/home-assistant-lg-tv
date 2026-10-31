"""Build webOS 4 capture requests and decide whether a still is blank.

``DISPLAY`` on this generation often returns only the graphics plane, so
Netflix, Disney+ and HDMI look black. ``com.webos.service.tv.capture`` with
``SCREEN_WITH_SOURCE_VIDEO`` is the call that includes the video plane
(bscpylgtv's method list, and the capture path used by plx-native). webOS 4
still requires width and height (Glowcast).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

CAPTURE_PATH = "/tmp/ha_lg_screen.jpg"
VIDEO_PLANE_URI = "com.webos.service.tv.capture/executeOneShot"
SSAP_ALIAS_URI = "tv/executeOneShot"

DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 540
AUTO_METHOD = "AUTO"
DEFAULT_METHOD = AUTO_METHOD

DIRECT_METHODS: tuple[str, ...] = (
    "SCREEN_WITH_SOURCE_VIDEO",
    "DISPLAY",
    "VIDEO",
    "SOURCE",
    "GRAPHIC",
    "BLENDED",
)
CAPTURE_METHODS: tuple[str, ...] = (AUTO_METHOD, *DIRECT_METHODS)

# Video plane first. The SSAP alias is last because on webOS 4 it often
# captures graphics only. Each item is (uri, method, format).
_AUTO_ATTEMPTS: tuple[tuple[str, str, str], ...] = (
    (VIDEO_PLANE_URI, "SCREEN_WITH_SOURCE_VIDEO", "JPEG"),
    (VIDEO_PLANE_URI, "SCREEN_WITH_SOURCE_VIDEO", "JPG"),
    (SSAP_ALIAS_URI, "SCREEN_WITH_SOURCE_VIDEO", "JPG"),
    (VIDEO_PLANE_URI, "VIDEO", "JPEG"),
    (VIDEO_PLANE_URI, "SOURCE", "JPEG"),
    (VIDEO_PLANE_URI, "BLENDED", "JPEG"),
    (SSAP_ALIAS_URI, "DISPLAY", "JPG"),
)


def attempts_for(method: str) -> tuple[tuple[str, str, str], ...]:
    """Return capture calls to try, video plane before the graphics alias."""
    if method == AUTO_METHOD or method not in DIRECT_METHODS:
        return _AUTO_ATTEMPTS
    return (
        (VIDEO_PLANE_URI, method, "JPEG"),
        (VIDEO_PLANE_URI, method, "JPG"),
        (SSAP_ALIAS_URI, method, "JPG"),
    )


def build_capture_payload(
    width: int,
    height: int,
    method: str,
    image_format: str = "JPG",
    path: str | None = None,
) -> dict[str, Any]:
    """Return an executeOneShot payload webOS 4 will accept."""
    if method not in DIRECT_METHODS:
        method = "SCREEN_WITH_SOURCE_VIDEO"
    return {
        "path": path or _capture_path(method, image_format),
        "method": method,
        "format": image_format,
        "width": int(width),
        "height": int(height),
    }


def _capture_path(method: str, image_format: str) -> str:
    """Give each attempt its own file so a failed call cannot reuse the last JPEG."""
    suffix = "jpg" if image_format.upper() in {"JPG", "JPEG"} else image_format.lower()
    safe = "".join(ch if ch.isalnum() else "_" for ch in method.lower())
    return f"/tmp/ha_lg_screen_{safe}.{suffix}"


def samples_are_blank(samples: Sequence[int]) -> bool:
    """Return whether luminance samples are a flat, near-black frame.

    A protected video plane is uniform black. A dark scene still has variation,
    so variance keeps those frames.
    """
    count = len(samples)
    if count < 16:
        return False
    mean = sum(samples) / count
    variance = sum((sample - mean) ** 2 for sample in samples) / count
    return mean < 12 and variance < 4


def jpeg_is_blank(data: bytes) -> bool:
    """Return whether a JPEG is a blank frame. Needs Pillow, which Home Assistant ships."""
    try:
        from PIL import Image
    except ImportError:
        return False
    import io

    try:
        with Image.open(io.BytesIO(data)) as image:
            small = image.convert("L").resize((32, 18))
            samples = [int(pixel) for pixel in small.getdata()]
    except (OSError, ValueError):
        return False
    return samples_are_blank(samples)


def capture_download_url(
    payload: Mapping[str, Any],
    host: str,
    fallback_path: str = CAPTURE_PATH,
) -> str:
    """Turn the TV's imageUri into a URL fetched from the configured host.

    The set often advertises localhost, 127.0.0.1, or its own hostname. Those
    are not reachable from Home Assistant, so the host is replaced and the
    port and path are kept.
    """
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    raw = payload.get("imageUri") or payload.get("imageUrl") or ""
    if not isinstance(raw, str):
        raw = ""
    raw = raw.strip()
    if not raw:
        return f"http://{host_part}:3000{fallback_path}"
    if raw.startswith("/"):
        return f"http://{host_part}:3000{raw}"
    if "://" not in raw:
        return f"http://{host_part}:3000/{raw.lstrip('/')}"

    parts = urlsplit(raw)
    scheme = parts.scheme or "http"
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        port = 3001 if scheme == "https" else 3000
    path = parts.path or fallback_path
    query = f"?{parts.query}" if parts.query else ""
    return f"{scheme}://{host_part}:{port}{path}{query}"
