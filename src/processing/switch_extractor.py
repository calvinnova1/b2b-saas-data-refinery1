"""Competitive switch mention extraction from feedback text."""

from __future__ import annotations

import re
from typing import List

SWITCH_PATTERNS = [
    r"switch(?:ing)? to (?P<vendor>[A-Za-z0-9_\- ]+)",
    r"move(?:d|ing)? from (?P<source>[A-Za-z0-9_\- ]+) to (?P<target>[A-Za-z0-9_\- ]+)",
    r"(?:instead of|rather than) (?P<competitor>[A-Za-z0-9_\- ]+)",
]


class SwitchExtractor:
    def extract_switches(self, text: str) -> List[str]:
        normalized = text.lower()
        matches: List[str] = []
        for pattern in SWITCH_PATTERNS:
            for match in re.finditer(pattern, normalized):
                data = match.groupdict()
                if data.get("vendor"):
                    matches.append(data["vendor"].strip())
                elif data.get("source") and data.get("target"):
                    matches.append(f"{data['source'].strip()} -> {data['target'].strip()}")
                elif data.get("competitor"):
                    matches.append(data["competitor"].strip())
        return matches
