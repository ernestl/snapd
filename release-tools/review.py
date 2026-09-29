"""Result of one area review.

An area script returns AreaReview from review(). pr-annotation-review.py collects
those results. This module does not read GitHub.
"""

from typing import NamedTuple


class Finding(NamedTuple):
    """One sanity-check result from an area.

    severity is warning or error.
    """

    severity: str
    message: str


class AreaReview(NamedTuple):
    """Facts, label words, and findings for one area.

    facts are short lines for the information section. labels are words
    the area wants applied. findings are empty until the area has a check.
    """

    name: str
    facts: tuple
    labels: tuple
    findings: tuple
