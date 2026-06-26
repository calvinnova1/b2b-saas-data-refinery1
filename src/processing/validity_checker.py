"""Basic validity checks for incoming feedback signals."""

from __future__ import annotations

import re


class ValidityChecker:
    def is_valid(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False

        sanitized = text.strip()
        if len(sanitized) < 10:
            return False

        if re.search(r"\b(lorem|ipsum|test|dummy|asdf)\b", sanitized.lower()):
            return False

        return True
