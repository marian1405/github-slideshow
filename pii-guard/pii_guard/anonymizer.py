"""Anonimizarea si de-anonimizarea textului.

Anonymizer tine harta valorilor reale <-> placeholdere pe durata sesiunii,
astfel incat aceeasi valoare primeste mereu acelasi placeholder, iar
raspunsurile lui Claude pot fi rescrise local cu datele reale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .detector import Match, detect


@dataclass
class AnonymizedText:
    text: str                 # textul cu placeholdere, sigur de trimis
    matches: list[Match]      # ce s-a inlocuit in acest text


@dataclass
class Anonymizer:
    # cheie: (kind, canonical) -> placeholder, ex. ("CNP", "187...") -> "[CNP_1]"
    _placeholders: dict[tuple[str, str], str] = field(default_factory=dict)
    # placeholder -> valoarea reala originala
    _values: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    @property
    def mapping(self) -> dict[str, str]:
        """Placeholder -> valoare reala (pentru afisare in interfata)."""
        return dict(self._values)

    def _placeholder_for(self, match: Match) -> str:
        key = (match.kind, match.canonical)
        if key not in self._placeholders:
            self._counters[match.kind] = self._counters.get(match.kind, 0) + 1
            placeholder = f"[{match.kind}_{self._counters[match.kind]}]"
            self._placeholders[key] = placeholder
            self._values[placeholder] = match.value
        return self._placeholders[key]

    def anonymize(self, text: str, custom_terms: list[str] | None = None) -> AnonymizedText:
        matches = detect(text, custom_terms)
        # Inlocuim de la coada spre inceput ca sa nu stricam pozitiile
        result = text
        for match in sorted(matches, key=lambda m: m.start, reverse=True):
            result = result[: match.start] + self._placeholder_for(match) + result[match.end:]
        return AnonymizedText(result, matches)

    def deanonymize(self, text: str) -> str:
        """Inlocuieste placeholderele dintr-un raspuns cu valorile reale, local."""
        if not self._values:
            return text
        pattern = re.compile(
            "|".join(re.escape(ph) for ph in sorted(self._values, key=len, reverse=True))
        )
        return pattern.sub(lambda m: self._values[m.group()], text)

    def reset(self) -> None:
        self._placeholders.clear()
        self._values.clear()
        self._counters.clear()
