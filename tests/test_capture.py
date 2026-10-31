"""Tests for the webOS 4 capture payload and download URL."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_capture():
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "lg_tv_screen"
        / "capture.py"
    )
    spec = importlib.util.spec_from_file_location("lg_tv_screen_capture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load_capture()


class CapturePayloadTest(unittest.TestCase):
    def test_webos4_payload_includes_size_and_jpg(self) -> None:
        payload = capture.build_capture_payload(960, 540, "DISPLAY")
        self.assertEqual(payload["method"], "DISPLAY")
        self.assertEqual(payload["format"], "JPG")
        self.assertEqual(payload["width"], 960)
        self.assertEqual(payload["height"], 540)
        self.assertIn("/tmp/ha_lg_screen_", payload["path"])

    def test_unknown_method_asks_for_the_video_plane(self) -> None:
        payload = capture.build_capture_payload(1920, 1080, "NOPE")
        self.assertEqual(payload["method"], "SCREEN_WITH_SOURCE_VIDEO")
        self.assertEqual(payload["width"], 1920)
        self.assertEqual(payload["height"], 1080)

    def test_auto_tries_the_video_plane_before_the_graphics_alias(self) -> None:
        attempts = capture.attempts_for("AUTO")
        self.assertEqual(
            attempts[0],
            (
                "com.webos.service.tv.capture/executeOneShot",
                "SCREEN_WITH_SOURCE_VIDEO",
                "JPEG",
            ),
        )
        self.assertEqual(attempts[-1][0], "tv/executeOneShot")
        self.assertEqual(attempts[-1][1], "DISPLAY")

    def test_named_method_uses_the_video_plane_service_first(self) -> None:
        attempts = capture.attempts_for("SCREEN_WITH_SOURCE_VIDEO")
        self.assertEqual(attempts[0][0], "com.webos.service.tv.capture/executeOneShot")
        self.assertTrue(all(item[1] == "SCREEN_WITH_SOURCE_VIDEO" for item in attempts))


class BlankFrameTest(unittest.TestCase):
    def test_uniform_black_is_blank(self) -> None:
        self.assertTrue(capture.samples_are_blank([0] * 64))

    def test_a_picture_with_variation_is_not_blank(self) -> None:
        samples = [10, 40, 80, 120, 200] * 16
        self.assertFalse(capture.samples_are_blank(samples))


class CaptureUrlTest(unittest.TestCase):
    def test_rewrites_localhost_and_keeps_port_and_path(self) -> None:
        url = capture.capture_download_url(
            {"imageUri": "http://127.0.0.1:3000/tmp/ha_lg_screen.jpg"},
            "192.168.1.40",
        )
        self.assertEqual(url, "http://192.168.1.40:3000/tmp/ha_lg_screen.jpg")

    def test_rewrites_https_hostname(self) -> None:
        url = capture.capture_download_url(
            {"imageUri": "https://lgwebostv:3001/tmp/capture.jpg?x=1"},
            "192.168.1.40",
        )
        self.assertEqual(url, "https://192.168.1.40:3001/tmp/capture.jpg?x=1")

    def test_relative_path_uses_port_3000(self) -> None:
        url = capture.capture_download_url(
            {"imageUri": "/tmp/ha_lg_screen.jpg"},
            "192.168.1.40",
        )
        self.assertEqual(url, "http://192.168.1.40:3000/tmp/ha_lg_screen.jpg")

    def test_missing_uri_uses_the_requested_path(self) -> None:
        url = capture.capture_download_url({}, "192.168.1.40")
        self.assertEqual(url, "http://192.168.1.40:3000/tmp/ha_lg_screen.jpg")

    def test_image_url_alias(self) -> None:
        url = capture.capture_download_url(
            {"imageUrl": "http://10.0.0.2:3000/tmp/ha_lg_screen.jpg"},
            "192.168.1.40",
        )
        self.assertEqual(url, "http://192.168.1.40:3000/tmp/ha_lg_screen.jpg")

    def test_http_without_port_defaults_to_3000(self) -> None:
        url = capture.capture_download_url(
            {"imageUri": "http://lgwebostv/tmp/ha_lg_screen.jpg"},
            "192.168.1.40",
        )
        self.assertEqual(url, "http://192.168.1.40:3000/tmp/ha_lg_screen.jpg")


if __name__ == "__main__":
    unittest.main()
