"""The one identity Fortress presents in every browser context of the shared engine.

Fortress draws a fresh persona for each created context unless every --uxr-*
surface is pinned, and its page-side values then disagree with its headers.
Pinned, all contexts present this identity with page == headers. Canvas and
audio noise stay per context by Fortress's design. Timezone and languages are
settings (browser_host_settings), whose defaults are below.
"""

from app.constants.browser import BROWSER_VIEWPORT_HEIGHT, BROWSER_VIEWPORT_WIDTH

#: Where the gaia image installs Fortress's launcher, which sets up its persona and fonts.
FORTRESS_IMAGE_BIN = "/opt/fortress/tilion"

#: Pinning the timezone turns off the launcher's egress-geo matching: production sets its egress zone.
FORTRESS_DEFAULT_TIMEZONE = "Asia/Kolkata"
#: Any other first language (en-IN measured) makes created contexts send a different Accept-Language.
FORTRESS_REQUIRED_FIRST_LANGUAGE = "en-US"
FORTRESS_DEFAULT_LANGUAGES: tuple[str, ...] = (FORTRESS_REQUIRED_FIRST_LANGUAGE, "en")

#: speechSynthesis voices as --uxr-voices-list entries, name|lang|local|default; ASCII only.
FORTRESS_VOICES: tuple[str, ...] = (
    "Microsoft David - English (United States)|en-US|1|1",
    "Microsoft Zira - English (United States)|en-US|1|0",
    "Microsoft Mark - English (United States)|en-US|1|0",
    "Google Deutsch|de-DE|0|0",
    "Google US English|en-US|0|0",
    "Google UK English Female|en-GB|0|0",
    "Google UK English Male|en-GB|0|0",
    "Google Bahasa Indonesia|id-ID|0|0",
    "Google italiano|it-IT|0|0",
    "Google Nederlands|nl-NL|0|0",
    "Google polski|pl-PL|0|0",
)

#: browser-use defaults that delete a surface the persona pins: a Windows Chrome has speechSynthesis.
FORTRESS_UNSUPPRESSED_DEFAULT_ARGS = frozenset(
    {"--disable-speech-synthesis-api", "--disable-speech-api"}
)

#: A Windows 11 desktop on an RTX 3060: every surface but timezone and languages.
FORTRESS_PERSONA_ARGS: tuple[str, ...] = (
    "--uxr-platform=Win32",
    "--uxr-ua-platform=Windows",
    "--uxr-ua-os=Windows NT 10.0; Win64; x64",
    "--uxr-ua-arch=x86",
    "--uxr-ua-bitness=64",
    "--uxr-ua-platform-version=15.0.0",
    "--uxr-ua-brand=Google Chrome",
    "--uxr-hw-concurrency=8",
    "--uxr-device-memory=8",
    "--uxr-webgl-vendor=Google Inc. (NVIDIA)",
    "--uxr-webgl-renderer=ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002504) Direct3D11 vs_5_0 ps_5_0, D3D11)",
    "--uxr-webgl-fullparams=1",
    "--uxr-webgl-max-viewport-dims=32767,32767",
    "--uxr-webgl-max-texture-size=16384",
    "--uxr-webgl-max-cube=16384",
    "--uxr-webgl-max-renderbuffer=16384",
    "--uxr-webgpu-vendor=nvidia",
    "--uxr-webgpu-architecture=ampere",
    "--uxr-webgpu-description=",
    "--uxr-screen-width=1920",
    "--uxr-screen-height=1080",
    "--uxr-device-pixel-ratio=1",
    "--uxr-screen-avail-width=1920",
    "--uxr-screen-avail-height=1032",
    "--uxr-screen-avail-top=0",
    "--uxr-screen-avail-left=0",
    "--uxr-screen-color-depth=24",
    # The host's window is the viewport (--window-size), so outer matches what inner implies.
    f"--uxr-outer-width={BROWSER_VIEWPORT_WIDTH}",
    f"--uxr-outer-height={BROWSER_VIEWPORT_HEIGHT}",
    "--uxr-color-gamut=srgb",
    "--uxr-dynamic-range=standard",
    "--uxr-color-scheme=light",
    "--uxr-battery-level=1",
    "--uxr-battery-charging=true",
    "--uxr-battery-charging-time=0",
    "--uxr-net-effective-type=4g",
    "--uxr-net-rtt=50",
    "--uxr-net-downlink=10",
    "--uxr-net-save-data=0",
    "--uxr-storage-quota=300000000000",
    "--uxr-media-devices=ai:1,vi:1,ao:1",
    "--uxr-voices-list=" + ";".join(FORTRESS_VOICES),
)
