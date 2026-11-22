"""The failures a repository reports, so no caller above it names a database driver's types."""


class RepositoryError(Exception):
    """The store failed the operation: unreachable, timed out, or refused the write."""


class AlreadyExistsError(RepositoryError):
    """A unique index refused the write: the row it would create or rename to already exists."""
