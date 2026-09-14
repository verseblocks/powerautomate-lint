"""Rule registry. Importing this package registers every shipped rule."""

from . import references  # noqa: F401  (import registers the rules)
from .base import Finding, Registry, Rule, Severity, registry, severity_rank
from .references import (
    check_action_references,
    check_functions,
    check_variables,
)

#: Checks are run explicitly rather than by iterating registry.all(), because
#: two rules (PAL102, PAL107) are produced as a by-product of another rule's
#: pass and would otherwise be run twice.
CHECKS = (
    check_action_references,
    check_variables,
    check_functions,
)

__all__ = [
    "CHECKS",
    "Finding",
    "Registry",
    "Rule",
    "Severity",
    "check_action_references",
    "check_functions",
    "check_variables",
    "registry",
    "severity_rank",
]
