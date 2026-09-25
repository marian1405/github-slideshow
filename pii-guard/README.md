# PII Guard Chat

Aplicație desktop (Python) pentru a lucra cu Claude **fără a trimite date
personale** în cloud. Tu scrii sau lipești documente cu date reale; aplicația
detectează local CNP-uri, IBAN-uri, e-mailuri, telefoane, adrese etc., le
înlocuiește cu placeholdere (`[CNP_1]`, `[IBAN_1]`, ...), trimite la Claude
doar versiunea anonimizată, iar în răspuns reintroduce automat valorile reale
— totul pe calculatorul tău.

```
tu (date reale) ──► detectare + anonimizare (local) ──► Claude API (doar placeholdere)
tu (date reale) ◄── de-anonimizare (local) ◄──────────── răspuns cu placeholdere
```

## Ce detectează automat

| Tip | Exemplu | Validare |
|---|---|---|
| CNP | `1800101221144` | cifră de control + lună/zi valide |
| IBAN | `RO49 AAAA 1B31 0075 9384 0000` | mod 97 |
| CUI / CIF | `CUI RO12345678` | prefix CUI/CIF |
| Card bancar | `4111 1111 1111 1111` | algoritmul Luhn |
| Telefon | `0722 123 456`, `+40 21 ...` | format RO |
| Serie CI | `seria AB nr. 123456` | — |
| Adresă | `Str. Victoriei, nr. 10, bl. A2` | euristic |
| Termeni proprii | nume de persoane, firme etc. | adăugați manual din panoul lateral |

Numele de persoane **nu pot fi detectate fiabil** doar cu reguli — adaugă-le ca
„termeni protejați" în panoul din dreapta (se salvează și se aplică mereu).

## Instalare (Windows / macOS / Linux)

1. Instalează [Python 3.10+](https://www.python.org/downloads/) (pe Windows
   bifează *Add python.exe to PATH* la instalare).
2. În folderul `pii-guard`:
   ```
   pip install -r requirements.txt
   python run.py
   ```
3. La prima pornire, introdu cheia API în fereastra **Setări API**. O obții
   din contul tău de pe <https://platform.claude.com> → *API keys*.
   Cheia se salvează doar local, în `~/.pii-guard/config.json`.

## Utilizare

- Scrie mesajul (sau **📄 Deschide fișier…** pentru .txt/.md/.csv) și apasă
  **Trimite** sau `Ctrl+Enter`.
- Dacă textul conține date personale, apare o fereastră de confirmare cu
  **exact ce se trimite** la Claude — verifici și confirmi.
- Panoul din dreapta arată toate datele anonimizate în sesiunea curentă și
  placeholder-ul fiecăreia. Valorile reale nu părăsesc calculatorul.
- **Conversație nouă** golește istoricul și harta de anonimizare.
- Modelul se alege din bara de sus (implicit `claude-opus-5`; `claude-sonnet-5`
  e mai ieftin, `claude-haiku-4-5` cel mai rapid/ieftin).

## Structura codului (pentru modificări)

```
pii-guard/
├── run.py                  # pornirea aplicației
├── pii_guard/
│   ├── detector.py         # AICI adaugi tipuri noi de PII (regex + validare)
│   ├── anonymizer.py       # harta placeholder ↔ valoare reală
│   ├── claude_client.py    # apelurile la API (model, system prompt, streaming)
│   ├── config.py           # setări locale (~/.pii-guard/config.json)
│   └── app.py              # interfața Tkinter
└── tests/test_pii_guard.py # rulează cu: python -m pytest tests/ -v
```

Idei de extins: suport PDF/DOCX la „Deschide fișier" (`pypdf`, `python-docx`),
detector de nume cu NLP local (`spacy` + modelul `ro_core_news_sm`), export
conversație.

## Limitări oneste

- Detectarea pe bază de reguli nu prinde 100% din date (mai ales nume și
  adrese atipice) — de aceea există fereastra de confirmare: citește ce se
  trimite înainte să apeși *Trimite*.
- Anonimizarea schimbă contextul: Claude nu poate valida un CNP anonimizat sau
  calcula vârsta din el.
