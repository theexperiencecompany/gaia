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
    CatalogRow(
        id="openai-api",
        name="OpenAI API",
        description=(
            "OpenAI's platform API for GPT models, embeddings, images and audio. GAIA can "
            "run models and embeddings, and manage your files, batches and vector stores."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "openai.com",
            "capability": "Run OpenAI models and manage your files, batches and vector stores",
            "rest": {"base_url": "https://api.openai.com/v1"},
            "credential": {
                "label": "OpenAI API key",
                "token_url": "https://platform.openai.com/api-keys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Endpoints: GET /models, POST /responses {model, input}, POST /embeddings "
                    "{model, input}, GET /files, GET /batches, GET /vector_stores. A project "
                    "key only sees its own project's resources."
                )
            },
            "allowed_hosts": ["api.openai.com"],
            "verify": {"args": ["GET", "/me"], "identity": {"json_path": "email"}},
        },
    ),
    CatalogRow(
        id="cloudflare-api",
        name="Cloudflare API",
        description=(
            "Cloudflare runs DNS, CDN, Workers and R2 for your domains. GAIA can read and "
            "change your zones, DNS records, Workers and cache settings."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "cloudflare.com",
            "capability": "Manage your Cloudflare zones, DNS records, Workers and cache",
            "rest": {"base_url": "https://api.cloudflare.com/client/v4"},
            "credential": {
                "label": "API token",
                "token_url": "https://dash.cloudflare.com/profile/api-tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Endpoints: GET /zones, GET /zones/{zone_id}/dns_records, POST "
                    "/zones/{zone_id}/dns_records {type, name, content, ttl}, GET /accounts, "
                    "GET /accounts/{account_id}/workers/scripts, POST "
                    "/zones/{zone_id}/purge_cache {files}. Every reply wraps its data in "
                    "result, with success and errors beside it."
                )
            },
            "allowed_hosts": ["api.cloudflare.com"],
            # The verify endpoint names the token, not an account: its id is the one stable name.
            "verify": {
                "args": ["GET", "/user/tokens/verify"],
                "identity": {"json_path": "result.id"},
            },
        },
    ),
    CatalogRow(
        id="twilio",
        name="Twilio",
        description=(
            "Twilio is a cloud platform for SMS, voice calls and phone numbers. GAIA can read "
            "your account, messages, calls, phone numbers and usage."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "twilio.com",
            "capability": "Read your Twilio messages, calls, phone numbers and usage",
            "rest": {
                "base_url": "https://api.twilio.com",
                "auth_template": "Basic {secret_base64}",
            },
            "credential": {
                "label": "Account SID and Auth Token",
                "token_url": "https://console.twilio.com/",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "The key is ACCOUNT_SID:AUTH_TOKEN. Endpoints: GET "
                    "/2010-04-01/Accounts.json, GET /2010-04-01/Accounts/{sid}/Messages.json, "
                    "and the same account's Calls.json, IncomingPhoneNumbers.json and "
                    "Usage/Records.json. Reads only: Twilio writes take form-encoded bodies, "
                    "which this connector cannot send."
                )
            },
            "allowed_hosts": ["api.twilio.com"],
            "verify": {
                "args": ["GET", "/2010-04-01/Accounts.json"],
                "identity": {"json_path": "accounts.0.friendly_name"},
            },
        },
    ),
    CatalogRow(
        id="sendgrid",
        name="SendGrid",
        description=(
            "SendGrid is Twilio's email delivery API. GAIA can send email, and read your "
            "templates, contacts, suppressions and sending stats."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "sendgrid.com",
            "capability": "Send email and read templates, contacts and stats with SendGrid",
            "rest": {"base_url": "https://api.sendgrid.com/v3"},
            "credential": {
                "label": "SendGrid API key",
                "token_url": "https://app.sendgrid.com/settings/api_keys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Endpoints: POST /mail/send {personalizations: [{to: [{email}]}], from: "
                    "{email}, subject, content: [{type, value}]}, GET /templates with "
                    "generations=dynamic, GET /marketing/contacts, GET /suppression/bounces, "
                    "GET /stats with start_date=YYYY-MM-DD. A restricted key answers 403 "
                    "outside its scopes."
                )
            },
            "allowed_hosts": ["api.sendgrid.com"],
            "verify": {"args": ["GET", "/user/username"], "identity": {"json_path": "username"}},
        },
    ),
    CatalogRow(
        id="postmark",
        name="Postmark",
        description=(
            "Postmark is a transactional email service. GAIA can send email, and read one "
            "server's messages, bounces, templates and delivery stats."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "postmarkapp.com",
            "capability": "Send email and read messages, bounces and stats on a Postmark server",
            "rest": {
                "base_url": "https://api.postmarkapp.com",
                "auth_header": "X-Postmark-Server-Token",
                "auth_template": "{secret}",
            },
            "credential": {
                "label": "Server API token",
                "token_url": "https://account.postmarkapp.com/servers",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "The token is one server's. Endpoints: POST /email {From, To, Subject, "
                    "HtmlBody}, GET /messages/outbound, GET /bounces, GET /templates, GET "
                    "/stats/outbound. List endpoints require count and offset query values."
                )
            },
            "allowed_hosts": ["api.postmarkapp.com"],
            "verify": {"args": ["GET", "/server"], "identity": {"json_path": "Name"}},
        },
    ),
    CatalogRow(
        id="digitalocean",
        name="DigitalOcean",
        description=(
            "DigitalOcean is a cloud provider for droplets, apps, databases and storage. GAIA "
            "can read and manage your droplets, apps, domains and databases."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "digitalocean.com",
            "capability": "Manage your DigitalOcean droplets, apps, domains and databases",
            "rest": {"base_url": "https://api.digitalocean.com/v2"},
            "credential": {
                "label": "personal access token",
                "token_url": "https://cloud.digitalocean.com/account/api/tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Endpoints: GET /droplets, POST /droplets/{id}/actions {type: reboot}, GET "
                    "/apps, GET /domains, GET /domains/{name}/records, GET /databases, GET "
                    "/customers/my/balance. Lists page with per_page (max 200) and page."
                )
            },
            "allowed_hosts": ["api.digitalocean.com"],
            "verify": {"args": ["GET", "/account"], "identity": {"json_path": "account.email"}},
        },
    ),
    CatalogRow(
        id="sentry",
        name="Sentry",
        description=(
            "Sentry tracks errors and performance in your apps. GAIA can read your "
            "organizations, projects, issues and events, and resolve or assign issues."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "sentry.io",
            "capability": "Read Sentry issues and events, and resolve or assign issues",
            "rest": {"base_url": "https://sentry.io/api/0"},
            "credential": {
                "label": "user auth token",
                "token_url": "https://sentry.io/settings/account/api/auth-tokens/",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Paths end with a slash. Endpoints: GET /organizations/, GET "
                    "/organizations/{org}/projects/, GET /projects/{org}/{project}/issues/ "
                    "with query=is:unresolved, GET /issues/{id}/events/latest/, PUT "
                    "/organizations/{org}/issues/ with id={id} and {status: resolved}."
                )
            },
            "allowed_hosts": ["sentry.io"],
            "verify": {"args": ["GET", "/organizations/"], "identity": {"json_path": "0.slug"}},
        },
    ),
    CatalogRow(
        id="render",
        name="Render",
        description=(
            "Render hosts web services, static sites, cron jobs and Postgres. GAIA can read "
            "your services, deploys and logs, and trigger deploys."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "render.com",
            "capability": "Read your Render services, deploys and logs, and trigger deploys",
            "rest": {"base_url": "https://api.render.com/v1"},
            "credential": {
                "label": "API key",
                "token_url": "https://dashboard.render.com/u/settings#api-keys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "Endpoints: GET /owners, GET /services, GET /services/{id}/deploys, POST "
                    "/services/{id}/deploys {}, GET /logs with ownerId and resource, GET "
                    "/postgres. Lists return [{cursor, <item>}] and page with cursor and limit."
                )
            },
            "allowed_hosts": ["api.render.com"],
            "verify": {"args": ["GET", "/users"], "identity": {"json_path": "email"}},
        },
    ),
    CatalogRow(
        id="hetzner-cloud",
        name="Hetzner Cloud",
        description=(
            "Hetzner Cloud runs servers, volumes, load balancers and firewalls. GAIA can read "
            "and manage the servers and networking in one of your projects."
        ),
        spec={
            "kind": "rest",
            "provider_domain": "hetzner.cloud",
            "capability": "Manage servers, volumes and firewalls in a Hetzner Cloud project",
            "rest": {"base_url": "https://api.hetzner.cloud/v1"},
            "credential": {
                "label": "API token",
                "token_url": "https://console.hetzner.cloud/projects",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    "The token belongs to one project (Security, API tokens). Endpoints: GET "
                    "/servers, POST /servers/{id}/actions/reboot, GET /volumes, GET "
                    "/firewalls, GET /load_balancers, GET /pricing. Lists page with page and "
                    "per_page."
                )
            },
            "allowed_hosts": ["api.hetzner.cloud"],
            # A project token names no account or project; the first server's name is the best hint.
            "verify": {
                "args": ["GET", "/servers", "--query", "per_page=1"],
                "identity": {"json_path": "servers.0.name"},
            },
        },
    ),
]
