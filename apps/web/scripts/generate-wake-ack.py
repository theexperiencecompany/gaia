"""Render the assistant popup's wake acknowledgment ("mm-hmm") via ElevenLabs.

Credentials come from Infisical using the machine identity in apps/api/.env
(ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID, environment: production). Run it
through the API virtualenv, which has the Infisical SDK installed:

    cd apps/api && uv run python ../web/scripts/generate-wake-ack.py

Output: apps/web/public/audio/wake-ack.mp3 (served via WAKE_ACK_AUDIO_SRC in
src/features/desktop-popup/constants.ts).
"""

import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

from dotenv import dotenv_values
from infisical_sdk import InfisicalSDKClient

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ENV_PATH = REPO_ROOT / "apps/api/.env"
OUTPUT_PATH = REPO_ROOT / "apps/web/public/audio/wake-ack.mp3"

TEXT = "mm-hmm?"
MODEL_ID = "eleven_turbo_v2_5"
OUTPUT_FORMAT = "mp3_44100_128"
VOICE_SETTINGS = {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35}


def fetch_secret(client: InfisicalSDKClient, env: dict[str, str | None], name: str) -> str:
    secret = client.secrets.get_secret_by_name(
        secret_name=name,
        project_id=env["INFISICAL_PROJECT_ID"],
        environment_slug="production",
        secret_path="/",
    )
    return secret.secretValue


def main() -> int:
    env = dotenv_values(API_ENV_PATH)
    client = InfisicalSDKClient(host=env.get("INFISICAL_URL") or "https://app.infisical.com")
    client.auth.universal_auth.login(
        client_id=env["INFISICAL_MACHINE_IDENTITY_CLIENT_ID"],
        client_secret=env["INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"],
    )

    api_key = fetch_secret(client, env, "ELEVENLABS_API_KEY")
    voice_id = fetch_secret(client, env, "ELEVENLABS_VOICE_ID")

    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={OUTPUT_FORMAT}",
        data=json.dumps(
            {"text": TEXT, "model_id": MODEL_ID, "voice_settings": VOICE_SETTINGS}
        ).encode(),
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            OUTPUT_PATH.write_bytes(response.read())
    except urllib.error.HTTPError as error:
        print(f"ElevenLabs request failed ({error.code}): {error.read().decode()[:300]}")
        return 1

    print(f"Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
