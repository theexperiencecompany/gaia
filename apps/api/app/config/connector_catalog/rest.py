"""Catalog connectors that call a provider's REST API through GAIA's host-locked request helper."""

from app.config.connector_catalog.row import CatalogRow

REST_CONNECTORS: list[CatalogRow] = [
    CatalogRow(
        id="resend",
        name="Resend",
        description=(
            "Resend is an email API for developers. GAIA can send email, and manage your "
            "sending domains, audiences and contacts."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "resend.com",
            "capability": "Send email and manage domains, audiences and contacts with Resend",
            "rest": {"base_url": "https://api.resend.com"},
            "credential": {
                "label": "Resend API key",
                "token_url": "https://resend.com/api-keys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Endpoints: GET /domains, GET /audiences, POST /audiences {name}, "
                    "DELETE /audiences/{id}, GET /audiences/{id}/contacts, POST /emails "
                    "{from, to, subject, html}. A sending-only key answers 401 "
                    "restricted_api_key to anything but POST /emails."
                )
            },
            "allowed_hosts": ["api.resend.com"],
            "verify": {"args": ["GET", "/domains"], "identity": {"json_path": "data.0.name"}},
        },
    ),
]
