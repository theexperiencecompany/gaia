#!/usr/bin/env bash
# Single source of truth for the GHCR repos each deployable image group maps
# to. Sourced by `release.sh resolve-image-tags` (build), `deploy.sh retag`
# (deploy/rollback) and `release.sh promote-latest` (gate) so the ends of the
# pipeline can never disagree about which repos share a tag. Keep in sync with the
# image: lines in the prod compose (lives in gaia-infra) and nx.json release groups.
# shellcheck disable=SC2034  # consumed by sourcing scripts
GHCR_NAMESPACE="ghcr.io/theexperiencecompany"
# nx release group "apps" — one commit produces the same tag for both.
APPS_IMAGE_REPOS=(gaia gaia-voice-agent)
# nx release group "bots" — fixed relationship, all five share the tag.
BOTS_IMAGE_REPOS=(gaia-bot-discord gaia-bot-slack gaia-bot-telegram gaia-bot-whatsapp gaia-bot-imessage)
GRAFANA_IMAGE_REPO="gaia-grafana"
# Self-host package image (never Swarm-deployed); :latest promoted by
# `release.sh promote-latest` after the quality gate instead of the deploy retag.
WEB_IMAGE_REPO="gaia-web"
