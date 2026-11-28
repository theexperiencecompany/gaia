"""Catalog connectors that run a provider's own CLI, pinned per CPU and checksummed."""

from app.config.connector_catalog.row import CatalogRow

_GH_VERSION = "2.106.0"
# From the release's gh_2.106.0_checksums.txt.
_GH_SHA256 = {
    "amd64": "a476449fa9625413c54a3734eded62e9e480e49f421ff08e7f3b3879c059a033",
    "arm64": "5e8a0c51e1a8345f36bd0b8bb88604b6a5388df16f3ab3e3b9b6d794fa223a67",
}
# Release assets that name amd64 by its uname.
_X86_64 = {"amd64": "x86_64", "arm64": "arm64"}

_STRIPE_VERSION = "1.55.15"
# From the release's stripe-linux-checksums.txt.
_STRIPE_SHA256 = {
    "amd64": "c9210819dfd19b5e077a0617af7a6eaffd8fb7295477f764d84eeee39f4e7e45",
    "arm64": "cf7bbda1ae637f8f8b1ed2fa80ede7694a5bd8f85c8847cb39a4c59990fba16c",
}

_FLYCTL_VERSION = "0.5.19"
# From the release's flyctl_0.5.19_checksums.txt.
_FLYCTL_SHA256 = {
    "amd64": "403d14a46d495d112c98dcf42aacd397833f5e471eb2b6c6f42cde4bbca45a0a",
    "arm64": "461d00c87ae9f28c5644b86317798b6d5ca48b40757e00ceb1d176bdc1d9e129",
}

_SUPABASE_VERSION = "3.4.0"
# From the release's checksums.txt.
_SUPABASE_SHA256 = {
    "amd64": "d82f8fc8a1611c45b9422b10378f61df614325f7e25624acda3704544513d6ac",
    "arm64": "35f211ede3b4b6ae479cb6aaf6f323dbf56f7268dab503cf4f549b2973580402",
}

_DOPPLER_VERSION = "3.77.1"
# From the release's checksums.txt.
_DOPPLER_SHA256 = {
    "amd64": "001f89a42629f9cb827cd86683c4c2dbf87c6299a8d6130643b98044bf5ed80a",
    "arm64": "a7f4be5b30295921dfe1cdc34f905cd017210ec3264a47d46e315ab09cb03e1c",
}

_RAILWAY_VERSION = "5.77.0"
# No checksums file in the release: shasum of each asset, equal to GitHub's asset digest.
_RAILWAY_SHA256 = {
    "amd64": "65d52da2650171a3bf0c752e3eb6f533a948b0aaf7475f48f1cb26c8c6c5fed9",
    "arm64": "327059a9b1ab79b98053a7e89cf97954166064296646021f1d04b9e45b701a7b",
}
_RAILWAY_TARGET = {"amd64": "x86_64", "arm64": "aarch64"}

_VERCEL_VERSION = "68.0.0"
# The last release that runs on Node 20: E2B's base image ships v20.9.
_WRANGLER_VERSION = "4.86.0"
_HEROKU_VERSION = "11.14.0"
_AWSCLI_VERSION = "1.46.3"

CLI_CONNECTORS: list[CatalogRow] = [
    CatalogRow(
        id="github-cli",
        name="GitHub CLI",
        description=(
            "GitHub's own command line tool. GAIA can read repositories, issues, pull "
            "requests, Actions runs and releases, and call any GitHub API endpoint."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "github.com",
            "capability": "Read and manage your GitHub repositories, pull requests and Actions",
            "command": "gh",
            "install": [
                {
                    "manager": "binary",
                    "name": "gh",
                    "version": _GH_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/cli/cli/releases/download/v{_GH_VERSION}/"
                        f"gh_{_GH_VERSION}_linux_{arch}.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": f"gh_{_GH_VERSION}_linux_{arch}/bin/gh",
                }
                for arch, sha256 in _GH_SHA256.items()
            ],
            "credential": {
                "env": ["GH_TOKEN"],
                "label": "personal access token",
                "token_url": "https://github.com/settings/tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "Pass --repo OWNER/REPO on every repo-scoped command: there is no checkout. "
                    "list/view commands take --json FIELDS (run with --json alone to see the "
                    'fields). `api` reaches any REST path, e.g. ["api", "repos/OWNER/REPO"].'
                ),
            },
            "risk": {
                "read_commands": [
                    "api",
                    "auth status",
                    "search",
                    "status",
                    "repo list",
                    "repo view",
                    "issue list",
                    "issue view",
                    "issue status",
                    "pr list",
                    "pr view",
                    "pr diff",
                    "pr checks",
                    "pr status",
                    "run list",
                    "run view",
                    "workflow list",
                    "workflow view",
                    "release list",
                    "release view",
                    "gist list",
                    "gist view",
                    "label list",
                    "org list",
                    "cache list",
                    "variable list",
                    "secret list",
                ],
                "write_flags": ["-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"],
            },
            "allowed_hosts": ["api.github.com", "github.com", "uploads.github.com"],
            "verify": {"args": ["api", "user"], "identity": {"json_path": "login"}},
        },
    ),
    CatalogRow(
        id="stripe-cli",
        name="Stripe CLI",
        description=(
            "Stripe's own command line tool for payments. GAIA can look up customers, "
            "charges, invoices, subscriptions and balances, and call any Stripe API endpoint."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "stripe.com",
            "capability": "Look up and manage your Stripe customers, payments, invoices and subscriptions",
            "command": "stripe",
            "install": [
                {
                    "manager": "binary",
                    "name": "stripe",
                    "version": _STRIPE_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/stripe/stripe-cli/releases/download/v{_STRIPE_VERSION}/"
                        f"stripe_{_STRIPE_VERSION}_linux_{_X86_64[arch]}.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": "stripe",
                }
                for arch, sha256 in _STRIPE_SHA256.items()
            ],
            "credential": {
                "env": ["STRIPE_API_KEY"],
                "label": "secret key",
                "token_url": "https://dashboard.stripe.com/apikeys",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "guidance": (
                    'Output is JSON. `get` reads any endpoint, e.g. ["get", "/v1/customers", "-d", '
                    '"limit=10"]; resource commands such as `customers list` and `invoices retrieve ID` '
                    "work too. `post` and `delete` write, with -d key=value for parameters."
                ),
            },
            "risk": {
                "read_commands": [
                    "get",
                    "balance retrieve",
                    "customers list",
                    "customers retrieve",
                    "customers search",
                    "charges list",
                    "charges retrieve",
                    "invoices list",
                    "invoices retrieve",
                    "subscriptions list",
                    "subscriptions retrieve",
                    "products list",
                    "products retrieve",
                    "prices list",
                    "prices retrieve",
                    "events list",
                    "events retrieve",
                    "payouts list",
                    "refunds list",
                    "disputes list",
                ],
            },
            "allowed_hosts": ["api.stripe.com", "files.stripe.com"],
            "verify": {"args": ["get", "/v1/account"], "identity": {"json_path": "id"}},
        },
    ),
    CatalogRow(
        id="vercel-cli",
        name="Vercel CLI",
        description=(
            "Vercel's own command line tool for frontend hosting. GAIA can list projects and "
            "deployments, read build and runtime logs, and manage domains and environment variables."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "vercel.com",
            "capability": "Check your Vercel deployments, logs, domains and environment variables",
            "command": "vercel",
            "install": [{"manager": "npm", "name": "vercel", "version": _VERCEL_VERSION}],
            "credential": {
                "env": ["VERCEL_TOKEN"],
                "label": "access token",
                "token_url": "https://vercel.com/account/settings/tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--format=json",
                "guidance": (
                    "Pass --scope TEAM_SLUG for team resources and --yes to skip prompts: there is "
                    "no linked project, so name the project or deployment URL explicitly. "
                    "`list PROJECT` shows deployments, `inspect URL --logs` shows a build log."
                ),
            },
            "risk": {
                "read_commands": [
                    "whoami",
                    "list",
                    "ls",
                    "inspect",
                    "logs",
                    "project ls",
                    "project list",
                    "project inspect",
                    "projects ls",
                    "projects list",
                    "projects inspect",
                    "domains ls",
                    "domains list",
                    "domains inspect",
                    "dns ls",
                    "dns list",
                    "env ls",
                    "env list",
                    "teams ls",
                    "teams list",
                    "alias ls",
                    "alias list",
                    "certs ls",
                    "certs list",
                ],
            },
            "allowed_hosts": ["api.vercel.com", "vercel.com"],
            "verify": {"args": ["whoami", "--format=json"], "identity": {"json_path": "username"}},
        },
    ),
    CatalogRow(
        id="wrangler",
        name="Cloudflare Wrangler",
        description=(
            "Cloudflare's own command line tool for Workers and the developer platform. GAIA can "
            "list Workers, deployments, KV, D1, R2 and Pages, and read their settings."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "cloudflare.com",
            "capability": "Check and manage your Cloudflare Workers, Pages, KV, D1 and R2",
            "command": "wrangler",
            "install": [{"manager": "npm", "name": "wrangler", "version": _WRANGLER_VERSION}],
            "credential": {
                "env": ["CLOUDFLARE_API_TOKEN"],
                "label": "API token",
                "token_url": "https://dash.cloudflare.com/profile/api-tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "There is no wrangler.toml, so pass --name WORKER on Worker commands. A token "
                    "that reaches several accounts cannot pick one here: account-scoped commands "
                    "need a token limited to one account. `whoami --json` lists the accounts."
                ),
            },
            "risk": {
                "read_commands": [
                    "whoami",
                    "deployments list",
                    "deployments status",
                    "versions list",
                    "versions view",
                    "kv namespace list",
                    "kv key list",
                    "kv key get",
                    "d1 list",
                    "d1 info",
                    "r2 bucket list",
                    "r2 bucket info",
                    "queues list",
                    "pages project list",
                    "pages deployment list",
                    "secret list",
                    "hyperdrive list",
                    "vectorize list",
                ],
            },
            "allowed_hosts": ["api.cloudflare.com"],
            "verify": {"args": ["whoami", "--json"], "identity": {"json_path": "accounts.0.name"}},
        },
    ),
    CatalogRow(
        id="flyctl",
        name="Fly.io CLI",
        description=(
            "Fly.io's own command line tool for running apps close to users. GAIA can list apps "
            "and machines, check status and releases, and read recent logs."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "fly.io",
            "capability": "Check and manage your Fly.io apps, machines, releases and logs",
            "command": "flyctl",
            "install": [
                {
                    "manager": "binary",
                    "name": "flyctl",
                    "version": _FLYCTL_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/superfly/flyctl/releases/download/v{_FLYCTL_VERSION}/"
                        f"flyctl_{_FLYCTL_VERSION}_Linux_{_X86_64[arch]}.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": "flyctl",
                }
                for arch, sha256 in _FLYCTL_SHA256.items()
            ],
            "credential": {
                "env": ["FLY_API_TOKEN"],
                "label": "personal access token",
                "token_url": "https://fly.io/user/personal_access_tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "Pass --app NAME on every app-scoped command: there is no fly.toml. "
                    "Use `logs --app NAME --no-tail` for a snapshot, since plain `logs` streams "
                    "until the call times out."
                ),
            },
            "risk": {
                "read_commands": [
                    "auth whoami",
                    "apps list",
                    "status",
                    "machine list",
                    "machine status",
                    "machines list",
                    "machines status",
                    "logs",
                    "releases",
                    "orgs list",
                    "platform regions",
                    "volumes list",
                    "secrets list",
                    "ips list",
                    "certs list",
                    "config show",
                    "scale show",
                    "checks list",
                    "image show",
                ],
            },
            "allowed_hosts": ["api.fly.io", "api.machines.dev"],
            "verify": {"args": ["auth", "whoami", "--json"], "identity": {"json_path": "email"}},
        },
    ),
    CatalogRow(
        id="supabase-cli",
        name="Supabase CLI",
        description=(
            "Supabase's own command line tool for its Postgres backend platform. GAIA can list "
            "organizations, projects, edge functions, branches and secrets names."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "supabase.com",
            "capability": "Check and manage your Supabase projects, edge functions and branches",
            "command": "supabase",
            "install": [
                {
                    "manager": "binary",
                    "name": "supabase",
                    "version": _SUPABASE_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/supabase/cli/releases/download/v{_SUPABASE_VERSION}/"
                        f"supabase_{_SUPABASE_VERSION}_linux_{arch}.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": "supabase",
                }
                for arch, sha256 in _SUPABASE_SHA256.items()
            ],
            "credential": {
                "env": ["SUPABASE_ACCESS_TOKEN"],
                "label": "access token",
                "token_url": "https://supabase.com/dashboard/account/tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--output json",
                "guidance": (
                    "Pass --project-ref REF on project commands: there is no linked project. "
                    "`projects list` shows each project's ref. Commands that need a local "
                    "supabase/ folder or a database password (db, migration, link) do not work here."
                ),
            },
            "risk": {
                "read_commands": [
                    "orgs list",
                    "projects list",
                    "functions list",
                    "secrets list",
                    "branches list",
                    "branches get",
                    "snippets list",
                    "backups list",
                    "domains get",
                    "sso list",
                    "network-bans get",
                    "network-restrictions get",
                    "postgres-config get",
                    "ssl-enforcement get",
                ],
            },
            "allowed_hosts": ["api.supabase.com"],
            "verify": {
                "args": ["orgs", "list", "--output", "json"],
                "identity": {"json_path": "0.name"},
            },
        },
    ),
    CatalogRow(
        id="aws-cli",
        name="AWS CLI",
        description=(
            "Amazon Web Services' own command line tool. GAIA can read EC2, S3, Lambda, IAM, "
            "CloudFormation, CloudWatch and billing data across your AWS account."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "amazonaws.com",
            "capability": "Look into and manage your AWS resources: EC2, S3, Lambda, IAM, logs and costs",
            "command": "aws",
            "install": [{"manager": "pip", "name": "awscli", "version": _AWSCLI_VERSION}],
            "credential": {
                "files": [
                    {
                        "path": "~/.aws/credentials",
                        "template": (
                            "[default]\n"
                            "aws_access_key_id = {secret_user}\n"
                            "aws_secret_access_key = {secret_password}\n"
                        ),
                    }
                ],
                "label": "access key (ACCESS_KEY_ID:SECRET_ACCESS_KEY)",
                "token_url": "https://console.aws.amazon.com/iam/home#/security_credentials",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                # `help` needs a man renderer the runners lack; --version proves the install.
                "help_args": ["--version"],
                "json_flag": "--output json",
                "guidance": (
                    "Pass --region REGION (e.g. us-east-1) on every call: no default region is "
                    "set. Commands are SERVICE OPERATION, e.g. ec2 describe-instances or "
                    "s3 ls s3://BUCKET; add --output json. `help` pages cannot render here "
                    "(no man renderer), so rely on known AWS CLI operation names."
                ),
            },
            "risk": {
                "read_commands": [
                    "sts get-caller-identity",
                    "s3 ls",
                    "s3api list-buckets",
                    "s3api list-objects-v2",
                    "ec2 describe-instances",
                    "ec2 describe-regions",
                    "ec2 describe-vpcs",
                    "ec2 describe-subnets",
                    "ec2 describe-security-groups",
                    "lambda list-functions",
                    "lambda get-function",
                    "iam list-users",
                    "iam list-roles",
                    "iam get-user",
                    "cloudformation list-stacks",
                    "cloudformation describe-stacks",
                    "logs describe-log-groups",
                    "logs filter-log-events",
                    "cloudwatch describe-alarms",
                    "dynamodb list-tables",
                    "dynamodb describe-table",
                    "rds describe-db-instances",
                    "ecs list-clusters",
                    "ecs list-services",
                    "ecs describe-services",
                    "eks list-clusters",
                    "sqs list-queues",
                    "sns list-topics",
                    "route53 list-hosted-zones",
                    "ce get-cost-and-usage",
                ],
            },
            "allowed_hosts": ["*.amazonaws.com"],
            "verify": {
                "args": ["sts", "get-caller-identity", "--output", "json", "--region", "us-east-1"],
                "identity": {"json_path": "Arn"},
            },
        },
    ),
    CatalogRow(
        id="doppler-cli",
        name="Doppler CLI",
        description=(
            "Doppler's own command line tool for secrets management. GAIA can list projects, "
            "configs and environments, and read secret names and values."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "doppler.com",
            "capability": "Read and manage your Doppler projects, configs and secrets",
            "command": "doppler",
            "install": [
                {
                    "manager": "binary",
                    "name": "doppler",
                    "version": _DOPPLER_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/DopplerHQ/cli/releases/download/{_DOPPLER_VERSION}/"
                        f"doppler_{_DOPPLER_VERSION}_linux_{arch}.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": "doppler",
                }
                for arch, sha256 in _DOPPLER_SHA256.items()
            ],
            "credential": {
                "env": ["DOPPLER_TOKEN"],
                "label": "personal token",
                "token_url": "https://dashboard.doppler.com",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "Pass --project NAME --config NAME on secrets and config commands: there is no "
                    "setup in the working directory. `secrets names` lists names without values."
                ),
            },
            "risk": {
                "read_commands": [
                    "me",
                    "projects get",
                    "configs get",
                    "environments get",
                    "secrets get",
                    "secrets names",
                    "activity get",
                ],
            },
            "allowed_hosts": ["api.doppler.com"],
            "verify": {"args": ["me", "--json"], "identity": {"json_path": "workplace.name"}},
        },
    ),
    CatalogRow(
        id="railway-cli",
        name="Railway CLI",
        description=(
            "Railway's own command line tool for deploying apps and databases. GAIA can list "
            "projects and services, check deployments and read their logs."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "railway.com",
            "capability": "Check and manage your Railway projects, services, deployments and logs",
            "command": "railway",
            "install": [
                {
                    "manager": "binary",
                    "name": "railway",
                    "version": _RAILWAY_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/railwayapp/cli/releases/download/v{_RAILWAY_VERSION}/"
                        f"railway-v{_RAILWAY_VERSION}-{_RAILWAY_TARGET[arch]}-unknown-linux-musl.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": "railway",
                }
                for arch, sha256 in _RAILWAY_SHA256.items()
            ],
            "credential": {
                "env": ["RAILWAY_API_TOKEN"],
                "label": "account token",
                "token_url": "https://railway.com/account/tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "There is no linked project: pass --project ID, --service NAME and "
                    "--environment NAME where a command takes them. `list --json` shows projects."
                ),
            },
            "risk": {
                "read_commands": [
                    "whoami",
                    "list",
                    "status",
                    "logs",
                    "variable list",
                    "variable ls",
                    "variables list",
                    "variables ls",
                ],
            },
            "allowed_hosts": ["backboard.railway.com"],
            "verify": {"args": ["whoami", "--json"], "identity": {"json_path": "email"}},
        },
    ),
    CatalogRow(
        id="heroku-cli",
        name="Heroku CLI",
        description=(
            "Heroku's own command line tool for its app platform. GAIA can list apps, dynos, "
            "add-ons, releases and config vars, and run any other Heroku command you approve."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "heroku.com",
            "capability": "Check and manage your Heroku apps, dynos, add-ons and releases",
            "command": "heroku",
            "install": [{"manager": "npm", "name": "heroku", "version": _HEROKU_VERSION}],
            "credential": {
                "env": ["HEROKU_API_KEY"],
                "label": "API key",
                "token_url": "https://dashboard.heroku.com/account",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "Commands are TOPIC:COMMAND (apps:info, ps:scale). Pass --app NAME on every "
                    "app-scoped command: there is no git remote. Destructive commands need "
                    "--confirm APP_NAME to run without a prompt."
                ),
            },
            "risk": {
                "read_commands": [
                    "whoami",
                    "apps",
                    "status",
                    "regions",
                    "addons",
                    "releases",
                    "ps",
                    "config",
                    "domains",
                    "pipelines",
                    "spaces",
                    "teams",
                    "drains",
                    "features",
                    "buildpacks",
                    "access",
                    "certs",
                ],
            },
            "allowed_hosts": ["api.heroku.com"],
            "verify": {"args": ["whoami"], "identity": {"regex": r"(\S+@\S+)"}},
        },
    ),
]
