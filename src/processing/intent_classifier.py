"""Lightweight purchasing-intent classification."""

from __future__ import annotations

import re

INTENT_KEYWORDS = {
    "purchase": ["buy", "purchase", "paid", "pricing", "cost", "quote"],
    "evaluation": ["try", "trial", "test", "evaluate", "review"],
    "support": ["help", "support", "issue", "problem", "question"],
    "churn": ["switch", "move", "leave", "cancel", "replace", "migrate"],
}


class IntentClassifier:
    def predict_intent(self, text: str) -> str:
        cleaned = text.lower()
        counts = {intent: 0 for intent in INTENT_KEYWORDS}
        for intent, keywords in INTENT_KEYWORDS.items():
            for keyword in keywords:
                counts[intent] += len(re.findall(rf"\b{re.escape(keyword)}\b", cleaned))

        best_intent = max(counts, key=counts.get)
        if counts[best_intent] == 0:
            return "unknown"
        return best_intent
