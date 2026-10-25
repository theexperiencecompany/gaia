# The self-host local coding sandbox image. LocalDockerSandbox builds it on the
# host daemon the first time a container is created, tagged by the hash of this
# file, so an edit here builds a new image and replaces older containers.
#
# Beyond the coding tools' bash, coreutils and python, it carries what the
# coding-agent runs need, the same tools the E2B template bakes in: curl for the
# Claude Code and OpenCode installers and the run hook's callback, sqlite3 for
# saving OpenCode's database, git for the agents' repos. SANDBOX_USER_HOME is
# the agents' home on both backends; any uid may write it, since the container
# runs as the API's uid, which has no passwd entry here.
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

ARG SANDBOX_USER_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git procps sqlite3 unzip \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "${SANDBOX_USER_HOME}" \
    && chmod 1777 "${SANDBOX_USER_HOME}"
