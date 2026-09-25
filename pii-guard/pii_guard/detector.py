"""Detectarea datelor personale (PII) in text, cu focus pe documente romanesti.

Fiecare detector returneaza o lista de potriviri (Match). Detectoarele cu
validare (CNP, IBAN, card) accepta doar valori care trec suma de control,
ca sa reducem alarmele false.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    value: str      # textul exact din document
    canonical: str  # forma normalizata (fara spatii/separatori) folosita drept cheie
    kind: str       # CNP, IBAN, CUI, EMAIL, TELEFON, CARD, SERIE_CI, ADRESA, TERMEN


# ---------------------------------------------------------------------------
# Validari
# ---------------------------------------------------------------------------

_CNP_WEIGHTS = [2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9]


def is_valid_cnp(cnp: str) -> bool:
    if not re.fullmatch(r"[1-9]\d{12}", cnp):
        return False
    month, day = int(cnp[3:5]), int(cnp[5:7])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    control = sum(int(d) * w for d, w in zip(cnp[:12], _CNP_WEIGHTS)) % 11
    if control == 10:
        control = 1
    return control == int(cnp[12])


def is_valid_iban(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def is_valid_card(number: str) -> bool:
    """Verificare Luhn pentru numere de card (16 cifre)."""
    digits = [int(d) for d in number]
    if len(digits) != 16:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Expresii regulate
# ---------------------------------------------------------------------------

_RE_CNP = re.compile(r"(?<!\d)[1-9]\d{12}(?!\d)")
_RE_IBAN = re.compile(r"(?<![A-Z0-9])RO\d{2}(?:\s?[A-Z0-9]{4}){5}(?![A-Z0-9])", re.IGNORECASE)
_RE_CUI = re.compile(r"\b(?:CUI|CIF)[:\s]*((?:RO\s?)?\d{2,10})\b", re.IGNORECASE)
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_RE_CARD = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)")
_RE_TELEFON = re.compile(r"(?<![\d.])(?:\+40|0040|0)[0-9 .\-]{8,13}(?![\d.])")
_RE_SERIE_CI = re.compile(r"\bseria?\s+[A-Z]{2}\s*,?\s*(?:nr\.?\s*)?\d{6}\b", re.IGNORECASE)
_RE_ADRESA = re.compile(
    r"\b(?:str(?:ada)?\.?|b(?:-|ule)?v?(?:ardul)?\.?|calea|aleea|[sș]os(?:eaua)?\.?"
    r"|intrarea|splaiul|pia[tț]a)\s+[A-ZĂÂÎȘȚ0-9][\w .\-ăâîșțĂÂÎȘȚ]{2,40}?"
    r"(?:[,\s]+(?:nr|bl|sc|et|ap)\.?\s*[0-9A-Za-z/]+)+",
    re.IGNORECASE,
)


def _valid_phone(raw: str) -> bool:
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+40"):
        rest = digits[3:]
    elif digits.startswith("0040"):
        rest = digits[4:]
    elif digits.startswith("0"):
        rest = digits[1:]
    else:
        return False
    # 9 cifre ramase; mobil (7xx) sau fix (2xx/3xx)
    return len(rest) == 9 and rest[0] in "237"


# ---------------------------------------------------------------------------
# Detectarea propriu-zisa
# ---------------------------------------------------------------------------

def _canonical(kind: str, value: str) -> str:
    if kind in ("IBAN", "CARD", "TELEFON"):
        return re.sub(r"[ .\-]", "", value).upper()
    if kind == "CUI":
        return re.sub(r"\s", "", value).upper()
    return value


def detect(text: str, custom_terms: list[str] | None = None) -> list[Match]:
    """Gaseste toate datele personale din text.

    Suprapunerile se rezolva pastrand potrivirea mai lunga (ex. un CNP inclus
    intr-un IBAN nu se raporteaza separat).
    """
    found: list[Match] = []

    def add(kind: str, start: int, end: int, value: str) -> None:
        found.append(Match(start, end, value, _canonical(kind, value), kind))

    for m in _RE_IBAN.finditer(text):
        if is_valid_iban(m.group()):
            add("IBAN", m.start(), m.end(), m.group())

    for m in _RE_CNP.finditer(text):
        if is_valid_cnp(m.group()):
            add("CNP", m.start(), m.end(), m.group())

    for m in _RE_CUI.finditer(text):
        add("CUI", m.start(1), m.end(1), m.group(1))

    for m in _RE_EMAIL.finditer(text):
        add("EMAIL", m.start(), m.end(), m.group())

    for m in _RE_CARD.finditer(text):
        if is_valid_card(re.sub(r"[ -]", "", m.group())):
            add("CARD", m.start(), m.end(), m.group())

    for m in _RE_TELEFON.finditer(text):
        value = m.group().rstrip(" .-")
        if _valid_phone(value):
            add("TELEFON", m.start(), m.start() + len(value), value)

    for m in _RE_SERIE_CI.finditer(text):
        add("SERIE_CI", m.start(), m.end(), m.group())

    for m in _RE_ADRESA.finditer(text):
        add("ADRESA", m.start(), m.end(), m.group())

    # Termeni protejati adaugati manual (nume de persoane, firme, etc.)
    for term in custom_terms or []:
        term = term.strip()
        if len(term) < 2:
            continue
        for m in re.finditer(re.escape(term), text, re.IGNORECASE):
            add("TERMEN", m.start(), m.end(), m.group())

    # Rezolvarea suprapunerilor: pastram potrivirile mai lungi
    found.sort(key=lambda x: (x.start, -(x.end - x.start)))
    result: list[Match] = []
    last_end = -1
    for match in found:
        if match.start >= last_end:
            result.append(match)
            last_end = match.end
    return result
