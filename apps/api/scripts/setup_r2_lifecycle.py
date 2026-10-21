"""Apply the R2 lifecycle rule that expires browser step screenshots.

Browser task recaps are backed by step screenshots in R2 under ``browser_steps/``
(see ``app/services/browser/screenshots.py``). Nothing deletes them, so they
accumulate forever. This applies a bucket lifecycle rule that expires those
objects after the retention window, keeping storage bounded. A task's recap stops
working once its screenshots expire — the history is expected to degrade
gracefully past the window.

Idempotent: re-running replaces the bucket's lifecycle configuration. Run once
per environment (or after changing the retention):

    ENV=development uv run --group backend python scripts/setup_r2_lifecycle.py
"""

import boto3

from app.config.settings import settings

# Keep recaps replayable for this long; screenshots older than this are reclaimed.
RETENTION_DAYS = 90
_LIFECYCLE_RULE_ID = "expire-browser-step-screenshots"
_SCREENSHOT_PREFIX = "browser_steps/"


def main() -> None:
    if not (
        settings.CLOUDFLARE_ACCOUNT_ID
        and settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_BUCKET
    ):
        raise SystemExit("R2 is not configured (CLOUDFLARE_ACCOUNT_ID / R2_* settings missing).")

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    # NOSONAR python:S7608 — ExpectedBucketOwner is redundant here, and R2 does not
    # implement it. The endpoint above is
    # https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com, so the account is
    # already pinned by the URL this client talks to: there is no cross-account
    # bucket this call could reach for the parameter to guard against.
    client.put_bucket_lifecycle_configuration(  # NOSONAR python:S7608
        Bucket=settings.R2_BUCKET,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": _LIFECYCLE_RULE_ID,
                    "Filter": {"Prefix": _SCREENSHOT_PREFIX},
                    "Status": "Enabled",
                    "Expiration": {"Days": RETENTION_DAYS},
                }
            ]
        },
    )
    print(
        f"Applied R2 lifecycle rule '{_LIFECYCLE_RULE_ID}' on bucket "
        f"'{settings.R2_BUCKET}': {_SCREENSHOT_PREFIX}* expire after {RETENTION_DAYS} days."
    )


if __name__ == "__main__":
    main()
