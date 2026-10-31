# LG TV Screen

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiwaili&repository=home-assistant-lg-tv&category=integration)

Home Assistant custom integration that captures a still of what an LG webOS TV is showing. Written for a **32LM6300PCB on webOS 4.10**. The same screenshot call works on other webOS 4 sets.

The TV has no video stream for the panel. Each refresh is a new JPEG. On webOS 4 the picture, including HDMI and streaming apps, comes from `com.webos.service.tv.capture/executeOneShot` with method `SCREEN_WITH_SOURCE_VIDEO`. The older `tv/executeOneShot` `DISPLAY` call often returns only the graphics plane, which is a black video area.

## What you need

- The TV and Home Assistant on the same LAN
- The TV switched on (standby does not accept the connection)
- The built-in **LG webOS TV** integration, already paired, when you want the media player to stay connected
- No root and no developer mode

Add **LG TV Screen** and select that TV. Capture sends requests on the websocket the media player already holds. It does not call `connect()` with that client key, which is what used to drop the player. A TV that is not in the LG webOS TV integration can still be paired on its own; that uses a different key and does not touch the media player.

## Install

### Home Assistant Community Store

[Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=kiwaili&repository=home-assistant-lg-tv&category=integration). If it is not in your HACS yet, add it as a custom repository:

1. HACS → Integrations → menu → **Custom repositories**
2. Repository: `https://github.com/kiwaili/home-assistant-lg-tv`
3. Category: **Integration**
4. Add the repository, then download **LG TV Screen**
5. Restart Home Assistant

In Home Assistant, go to Settings → Devices & services → Add integration → **LG TV Screen**, and choose the TV that is already in **LG webOS TV**. No second prompt. The camera is added to that same device.

### Manual

Copy `custom_components/lg_tv_screen` into your Home Assistant config directory:

```text
config/custom_components/lg_tv_screen
```

Restart Home Assistant, then add **LG TV Screen** the same way.

The device has three entities:

- **Screen**, the camera, for example `camera.lg_32lm6300pcb_screen`
- **Capture**, a switch. Off stops new pictures and does not close the TV connection. On takes a new still on the next refresh.
- **Interval**, seconds between stills, from 2 to 300. The default is 10.

Add **Capture** and **Interval** to the dashboard next to the picture card. `uses_media_player_connection` is true while the camera is sharing the LG webOS TV socket.

On webOS 4.10 the capture is **960×540 JPEG**. That size is required: this generation returns an error when width and height are left out. The default method is **Auto**. Auto asks the video-plane service first (`SCREEN_WITH_SOURCE_VIDEO`, then `VIDEO`, `SOURCE` and `BLENDED`) and keeps the first frame that is not flat black. That is the path that includes Netflix, Disney+ and HDMI when this firmware composites the video plane into the capture. `capture_method` and `capture_service` on the entity show which call produced the current still.

## Use the picture

Open the camera entity, or add a picture glance / picture entity card.

Save a still from an automation:

```yaml
action: camera.snapshot
target:
  entity_id: camera.lg_32lm6300pcb_screen
data:
  filename: /media/tv.jpg
```

The camera refreshes every 10 seconds by default (2–300). A request inside that window returns the last JPEG instead of asking the TV again.

`last_error` on the entity is empty when the last capture worked. Other values:

| Value | Meaning |
| --- | --- |
| `disabled` | Capture is turned off. |
| `not_connected` | The TV did not accept the websocket. It is usually off. |
| `not_paired` | The pairing key was rejected. Home Assistant starts pairing again. |
| `screen_off` | The panel is off. |
| `not_supported` | This firmware has no `executeOneShot` service. |
| `not_permitted` | The TV answered `401 insufficient permissions` (common on webOS 6 and newer, not on 4.10). |
| `refused` | The TV rejected the capture parameters. |
| `timed_out` | The TV did not answer in time. |
| `download_failed` | The socket accepted the capture but the JPEG URL did not download. |
| `not_jpeg` | The file was not a JPEG. |
| `protected` | Every capture call returned a flat black frame. The TV withheld the video plane. |

`app_id` is the foreground app (`com.webos.app.hdmi1`, `com.webos.app.livetv`, and so on).

## Limits

- Stills, not a live video stream. webOS has no continuous capture API.
- Auto includes the video plane. If the firmware still returns a uniform black frame for a protected app or an HDCP source, `last_error` is `protected`. This integration does not root the TV or strip HDCP; it can only show the picture the capture service returns.
- After a blank result, the same app is not probed again for 60 seconds.

## References

The capture call and the webOS 4 payload come from existing projects:

- [home-assistant-libs/aiowebostv](https://github.com/home-assistant-libs/aiowebostv) — pairing and the SSAP websocket used by Home Assistant's LG webOS TV integration. This component requires `aiowebostv==0.10.0`, the same release Home Assistant core pins.
- [chros73/bscpylgtv](https://github.com/chros73/bscpylgtv) — `executeOneShot` methods. `DISPLAY` is the graphics plane. `SCREEN_WITH_SOURCE_VIDEO`, `VIDEO`, `SOURCE` and `BLENDED` include the video plane.
- [nicohabets/glowcast](https://github.com/nicohabets/glowcast) — webOS 4 refuses a full-screen capture that does not include width and height. The working payload is 960×540, `DISPLAY`, `JPG`, path under `/tmp`.
- [undefjs/ha-webos-camera](https://github.com/undefjs/ha-webos-camera) — a camera that shells into a **rooted** TV over SSH. This integration does not do that. A stock 32LM6300PCB does not need root for `executeOneShot`.

To list it in the default HACS store, open a request in [hacs/default](https://github.com/hacs/default). Custom repositories work without that request. The GitHub repository needs a description, at least one topic, issues enabled, and an OSI license. Those are set on the repository; HACS reads them from GitHub.
