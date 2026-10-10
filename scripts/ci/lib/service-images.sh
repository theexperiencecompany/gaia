#!/usr/bin/env bash
# service-images.sh — the ONE place the test-service image pins live.
#
# Digest-pinned (the tag is a readability label; the digest is what is pulled)
# so every run boots identical bits and a flake can never be image drift.
#
# There is exactly one other copy of these references, deliberately: the local
# Dagger harness at .dagger/src/gaia_ci/main.py, which must give a dev machine
# the same topology CI gets. Bump the two together — nothing else may hold a
# service image reference.
#
# Sourced by scripts/ci/test-services.sh, and read textually by
# gaia-infra:self-hosted-runner/create-runner-user.sh (which greps
# ^[A-Z_]*_IMAGE= to pre-seed the runner user's docker daemon), so keep the
# assignments one per line, double-quoted, with no interpolation.
# shellcheck disable=SC2034  # consumed by sourcing scripts
POSTGRES_IMAGE="postgres:16.14-alpine3.24@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
REDIS_IMAGE="redis:7.4.9-alpine3.21@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
MONGO_IMAGE="mongo:7.0.37@sha256:340c1c56fb10e95cf79ff547f8664b96bc6ead9909bc355238cbf865a9695a6f"
CHROMA_IMAGE="chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6"
RABBITMQ_IMAGE="rabbitmq:3.13.7-alpine@sha256:d7af1c87c5f1eda13fcfca06db452bf3aeab6619fc3358b68535c0c02c4e52bc"
