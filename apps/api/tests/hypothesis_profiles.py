"""The Hypothesis profiles every tier runs under, and the few examples a mutation run affords."""

import os

from hypothesis import HealthCheck, settings

#: scripts/ci/mutation.py sets this for every mutated module's pytest run, which reruns per mutant.
_MUTATION_RUN_ENV = "MUTMUT_SCOPED_MODULE"
MUTATION_PROFILE = "mutation"

# "ci" (PRs, queue) is derandomized so the queue reproduces the PR's verdict; "ci-full"
# (master) explores, seeded per commit by pytest.sh's --hypothesis-seed.
# differing_executors: mutmut's in-process runner reinstantiates the @given class.
settings.register_profile(
    "ci",
    max_examples=25,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.differing_executors],
)
settings.register_profile(
    "ci-full",
    max_examples=200,
    deadline=None,
    # Explicit: under CI=true a new profile inherits Hypothesis's built-in "ci", which derandomizes.
    derandomize=False,
    database=None,
    suppress_health_check=[HealthCheck.differing_executors],
)
settings.register_profile(
    "default",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.differing_executors],
)
# A mutant is killed or not by the same few examples on every run.
settings.register_profile(
    MUTATION_PROFILE,
    max_examples=50,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.differing_executors],
)


def mutation_run() -> bool:
    """Return whether mutmut is running the suite, once per mutant."""
    return bool(os.environ.get(_MUTATION_RUN_ENV))


def load_profile() -> None:
    """Load the mutation profile under mutmut, else the one HYPOTHESIS_PROFILE names."""
    settings.load_profile(
        MUTATION_PROFILE if mutation_run() else os.getenv("HYPOTHESIS_PROFILE", "default")
    )


def property_examples(explored: int) -> int:
    """Return explored, or the mutation profile's examples when every mutant reruns the test."""
    return settings.get_profile(MUTATION_PROFILE).max_examples if mutation_run() else explored
