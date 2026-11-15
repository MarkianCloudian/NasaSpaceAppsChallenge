"""Exit codes (contracts/cli.md) and exceptions that carry them."""

OK = 0
UNEXPECTED = 1
USAGE = 2
SOURCE_CHECK_FAILED = 3
VALIDATION_FAILED = 4
PROFILE_CONFLICT = 5
PARTIAL_RESULT = 6
NO_CANDIDATES = 7
PUBLISH_REFUSED = 8


class AnalogError(Exception):
    exit_code = UNEXPECTED


class ConfigError(AnalogError):
    exit_code = VALIDATION_FAILED


class ValidationError(AnalogError):
    exit_code = VALIDATION_FAILED


class ProfileConflictError(AnalogError):
    exit_code = PROFILE_CONFLICT


class SourceCheckError(AnalogError):
    exit_code = SOURCE_CHECK_FAILED


class SourceError(AnalogError):
    """A fetch failed after retries and fallbacks."""
    exit_code = SOURCE_CHECK_FAILED
