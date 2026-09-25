"""Teste pentru detectare si anonimizare: python -m pytest tests/ -v"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pii_guard.anonymizer import Anonymizer
from pii_guard.detector import detect, is_valid_cnp, is_valid_iban

# CNP si IBAN de test, valide ca suma de control (nu apartin unor persoane reale)
VALID_CNP = "1800101221144"
VALID_IBAN = "RO49AAAA1B31007593840000"


def kinds(text, terms=None):
    return {m.kind for m in detect(text, terms)}


def test_cnp_checksum():
    assert is_valid_cnp(VALID_CNP)
    assert not is_valid_cnp("1234567890123")  # suma de control gresita
    assert not is_valid_cnp("1801341221144")  # luna 34 invalida


def test_iban_checksum():
    assert is_valid_iban(VALID_IBAN)
    assert is_valid_iban("RO49 AAAA 1B31 0075 9384 0000")
    assert not is_valid_iban("RO11AAAA1B31007593840000")


def test_detect_basic():
    text = (
        f"Subsemnatul, CNP {VALID_CNP}, email ion.popescu@example.com, "
        f"telefon 0722 123 456, cont {VALID_IBAN}, "
        "domiciliat pe Strada Victoriei, nr. 10, bl. A2, ap. 5."
    )
    found = kinds(text)
    assert {"CNP", "EMAIL", "TELEFON", "IBAN", "ADRESA"} <= found


def test_detect_cui_and_serie_ci():
    assert "CUI" in kinds("Firma cu CUI RO12345678 a emis factura.")
    assert "SERIE_CI" in kinds("CI seria AB nr. 123456, eliberata de SPCLEP.")


def test_random_digits_not_flagged():
    # 13 cifre oarecare nu trebuie marcate drept CNP
    assert kinds("Comanda numarul 1234567890123 a fost livrata.") == set()


def test_custom_terms():
    matches = detect("Contract intre Ion Popescu si firma X.", ["Ion Popescu"])
    assert any(m.kind == "TERMEN" for m in matches)


def test_anonymize_roundtrip():
    anon = Anonymizer()
    text = f"CNP: {VALID_CNP}, email: ana@example.com"
    result = anon.anonymize(text)
    assert VALID_CNP not in result.text
    assert "ana@example.com" not in result.text
    assert "[CNP_1]" in result.text and "[EMAIL_1]" in result.text
    # Raspunsul lui Claude cu placeholdere se rescrie cu valorile reale
    reply = "Persoana cu [CNP_1] poate fi contactata la [EMAIL_1]."
    assert anon.deanonymize(reply) == (
        f"Persoana cu {VALID_CNP} poate fi contactata la ana@example.com."
    )


def test_same_value_same_placeholder():
    anon = Anonymizer()
    first = anon.anonymize(f"CNP {VALID_CNP}").text
    second = anon.anonymize(f"Confirm CNP {VALID_CNP}").text
    assert "[CNP_1]" in first and "[CNP_1]" in second


def test_iban_spacing_shares_placeholder():
    anon = Anonymizer()
    a = anon.anonymize(VALID_IBAN).text
    b = anon.anonymize("RO49 AAAA 1B31 0075 9384 0000").text
    assert "[IBAN_1]" in a and "[IBAN_1]" in b
