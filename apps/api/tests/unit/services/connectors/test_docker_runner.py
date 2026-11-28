"""A failed docker install reports what the install script said, not docker's own build noise."""

from app.services.connectors.docker_runner import install_step_output

# The tail of a real plain-progress build of an amd64-only terraform spec on an arm64 host.
_BUILD_LOG = """#4 [1/5] FROM docker.io/library/gaia-local-sandbox:b5cb4e2a0d29
#4 DONE 0.1s
#5 [2/5] COPY install.sh /usr/local/lib/gaia-connector/install.sh
#5 CACHED
#6 [3/5] RUN bash /usr/local/lib/gaia-connector/install.sh && rm -f /usr/local/lib/gaia-connector/install.sh
#6 0.120 sha256sum: OK
#6 0.432 no terraform build for aarch64
#6 ERROR: process "/bin/sh -c bash /usr/local/lib/gaia-connector/install.sh" did not complete successfully: exit code: 1
------
 > [3/5] RUN bash /usr/local/lib/gaia-connector/install.sh:
0.432 no terraform build for aarch64
------
ERROR: failed to build: failed to solve: process did not complete successfully: exit code: 1"""


def test_the_install_scripts_own_lines_are_what_a_failed_build_reports() -> None:
    assert install_step_output(_BUILD_LOG) == "sha256sum: OK\nno terraform build for aarch64"


def test_a_build_that_failed_before_the_install_step_keeps_the_whole_log() -> None:
    log = "#1 [internal] load build definition\nERROR: failed to read dockerfile"

    assert install_step_output(log) == log
