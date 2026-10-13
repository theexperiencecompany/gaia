#!/bin/bash
# Bake Docker, Node and the GAIA CLI into the image. Nothing instance-specific
# happens here: machine secrets are generated on each Droplet's first boot
# (files/var/lib/cloud/scripts/per-instance/001_onboot), never in the snapshot.
set -euo pipefail

curl -fsSL https://get.docker.com | sh
systemctl enable docker

# The CLI needs Node >= 20; NodeSource keeps it system-wide for every user.
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get -qqy install nodejs
npm install -g --ignore-scripts @heygaia/cli

useradd --create-home --shell /bin/bash --groups docker gaia
