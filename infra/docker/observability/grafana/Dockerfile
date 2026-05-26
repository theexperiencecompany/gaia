# Bakes Grafana provisioning (datasources, dashboards, alerting) into the image
# so production needs no host bind mount — the swarm stack then deploys cleanly
# from CI via a remote Docker context. Built and pushed by
# .github/workflows/build.yml as ghcr.io/theexperiencecompany/gaia-grafana.
#
# Build context is this directory:
#   docker build -t gaia-grafana infra/docker/observability/grafana
FROM grafana/grafana:11.4.0

COPY provisioning /etc/grafana/provisioning
