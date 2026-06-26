"""Dual-axis sentiment analysis for feedback signals."""

from __future__ import annotations

import re

POSITIVE = {"good", "great", "love", "excellent", "positive", "happy", "benefit", "easy", "fast"}
NEGATIVE = {"bad", "problem", "issue", "poor", "slow", "hard", "difficult", "frustrated", "hate"}


class DualSentimentAnalyzer:
    def analyze(self, text: str) -> dict[str, object]:
        cleaned = text.lower()
        words = re.findall(r"\w+", cleaned)
        positive = sum(1 for word in words if word in POSITIVE)
        negative = sum(1 for word in words if word in NEGATIVE)
        polarity = "neutral"
        if positive > negative:
            polarity = "positive"
        elif negative > positive:
            polarity = "negative"

        intensity = min(1.0, max(0.0, (positive + negative) / max(len(words), 1)))
        urgency = "low"
        if re.search(r"\b(urgent|asap|immediately|soon|critical|important|emergency)\b", cleaned):
            urgency = "high"
        elif re.search(r"\b(soon|important|needed|required)\b", cleaned):
            urgency = "medium"

        return {
            "polarity": polarity,
            "intensity": round(intensity, 3),
            "urgency": urgency,
        }
