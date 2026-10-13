#!/bin/bash
# Only SSH and the GAIA proxy (HTTP, and HTTPS with a domain) are reachable.
set -euo pipefail

ufw limit ssh
ufw allow http
ufw allow https
ufw --force enable
