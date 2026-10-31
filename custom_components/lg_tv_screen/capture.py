"""Build webOS 4 capture requests and decide whether a still is blank.

``tv/executeOneShot`` with ``DISPLAY``, ``JPG``, and an explicit size is the
call that returns an HTTP ``imageUri`` on webOS 4.10. Width and height are
required; without them the TV answers ``CAPTURE_ERROR_03``. A frame whose
center is flat black is treated as graphics-only, and the next method is
tried (``SCREEN_WITH_SOURCE_VIDEO``, then ``VIDEO``, ``SOURCE``, ``BLENDED``).
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

# SSAP first. ``tv/executeOneShot`` is the call that returns an HTTP imageUri
# on webOS 4. The luna service name often is not an SSAP method, so it must
# not run ahead of the call that can actually deliver a JPEG. Each item is
# (uri, method, format).
_AUTO_ATTEMPTS: tuple[tuple[str, str, str], ...] = (
    (SSAP_ALIAS_URI, "DISPLAY", "JPG"),
    (SSAP_ALIAS_URI, "SCREEN_WITH_SOURCE_VIDEO", "JPG"),
    (SSAP_ALIAS_URI, "VIDEO", "JPG"),
    (SSAP_ALIAS_URI, "SOURCE", "JPG"),
    (SSAP_ALIAS_URI, "BLENDED", "JPG"),
    (VIDEO_PLANE_URI, "SCREEN_WITH_SOURCE_VIDEO", "JPG"),
    (VIDEO_PLANE_URI, "DISPLAY", "JPG"),
)


def attempts_for(method: str) -> tuple[tuple[str, str, str], ...]:
    """Return capture calls to try, the SSAP screenshot call before the luna service."""
    if method == AUTO_METHOD or method not in DIRECT_METHODS:
        return _AUTO_ATTEMPTS
    return (
        (SSAP_ALIAS_URI, method, "JPG"),
        (VIDEO_PLANE_URI, method, "JPG"),
        (VIDEO_PLANE_URI, method, "JPEG"),
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
    kind = "jpeg" if image_format.upper() == "JPEG" else suffix
    safe = "".join(ch if ch.isalnum() else "_" for ch in method.lower())
    return f"/tmp/ha_lg_screen_{safe}_{kind}.{suffix}"


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


def center_samples(samples: Sequence[int], width: int, height: int) -> list[int]:
    """Return the middle half of a row-major luminance grid.

    Streaming apps leave the video in the center and the UI around the edge.
    A black center with a bright edge is a graphics-only capture.
    """
    if width < 4 or height < 4 or len(samples) != width * height:
        return []
    x0 = width // 4
    x1 = width - x0
    y0 = height // 4
    y1 = height - y0
    picked: list[int] = []
    for y in range(y0, y1):
        row = y * width
        picked.extend(samples[row + x0 : row + x1])
    return picked


def _jpeg_samples(data: bytes) -> list[int] | None:
    """Downscale a JPEG to a 32×18 luminance grid. None when it cannot be read."""
    try:
        from PIL import Image
    except ImportError:
        return None
    import io

    try:
        with Image.open(io.BytesIO(data)) as image:
            small = image.convert("L").resize((32, 18))
            return [int(pixel) for pixel in small.getdata()]
    except (OSError, ValueError):
        return None


def jpeg_is_blank(data: bytes) -> bool:
    """Return whether a JPEG is a blank frame. Needs Pillow, which Home Assistant ships."""
    samples = _jpeg_samples(data)
    if samples is None:
        return False
    return samples_are_blank(samples)


def jpeg_center_is_blank(data: bytes) -> bool:
    """Return whether the video area in the middle of the JPEG is flat black."""
    samples = _jpeg_samples(data)
    if not samples:
        return False
    return samples_are_blank(center_samples(samples, 32, 18))


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
    raw = ""
    for key in ("imageUri", "imageUrl", "imageURL", "uri"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            raw = value.strip()
            break
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


def capture_download_urls(
    payload: Mapping[str, Any],
    host: str,
    fallback_path: str = CAPTURE_PATH,
) -> list[str]:
    """Return download URLs, HTTP :3000 and HTTPS :3001 for the same file.

    webOS serves the JPEG on one of those ports. The response names one of
    them; the other is only needed when that port does not connect.
    """
    primary = capture_download_url(payload, host, fallback_path)
    parts = urlsplit(primary)
    host_part = parts.hostname or host
    if ":" in host_part and not host_part.startswith("["):
        host_part = f"[{host_part}]"
    path = parts.path or fallback_path
    query = f"?{parts.query}" if parts.query else ""
    alternate_scheme = "http" if parts.scheme == "https" else "https"
    alternate_port = 3000 if alternate_scheme == "http" else 3001
    alternate = f"{alternate_scheme}://{host_part}:{alternate_port}{path}{query}"
    if alternate == primary:
        return [primary]
    return [primary, alternate]
