"""Comunicarea cu API-ul Claude (Anthropic).

Istoricul conversatiei este pastrat DOAR in forma anonimizata - datele reale
nu parasesc niciodata acest calculator. Claude primeste instructiuni sa
pastreze placeholderele neatinse, iar raspunsul este de-anonimizat local.
"""

from __future__ import annotations

from typing import Callable

import anthropic

AVAILABLE_MODELS = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]
DEFAULT_MODEL = AVAILABLE_MODELS[0]

SYSTEM_PROMPT = """Ești un asistent util care lucrează cu documente românești.

Textul primit poate conține placeholdere de forma [CNP_1], [IBAN_2], [EMAIL_1],
[TELEFON_1], [ADRESA_1], [TERMEN_1] etc. Acestea înlocuiesc date personale
anonimizate local de utilizator.

Reguli obligatorii:
1. Tratează fiecare placeholder ca pe valoarea reală pe care o reprezintă
   (de ex. [CNP_1] este un CNP valid al unei persoane).
2. Când te referi la acea valoare în răspuns, copiază placeholderul EXACT,
   caracter cu caracter, inclusiv parantezele pătrate. Nu-l reformula,
   nu-l traduce, nu inventa valori în locul lui.
3. Nu cere utilizatorului valorile reale - nu sunt necesare pentru sarcină."""


class ClaudeChat:
    """O conversatie multi-turn cu Claude, cu istoric anonimizat."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.messages: list[dict] = []

    def send(self, anonymized_text: str, on_text: Callable[[str], None] | None = None) -> str:
        """Trimite un mesaj (deja anonimizat!) si returneaza raspunsul complet.

        `on_text` este apelat cu fiecare fragment de text pe masura ce vine
        (streaming), ca interfata sa se actualizeze in timp real.
        """
        self.messages.append({"role": "user", "content": anonymized_text})
        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=16000,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=self.messages,
            ) as stream:
                for text in stream.text_stream:
                    if on_text:
                        on_text(text)
                response = stream.get_final_message()
        except Exception:
            # Mesajul nu a primit raspuns - il scoatem din istoric ca sa poata
            # fi retrimis dupa remedierea erorii (ex. cheie API gresita).
            self.messages.pop()
            raise

        if response.stop_reason == "refusal":
            self.messages.pop()
            detail = ""
            if response.stop_details and response.stop_details.explanation:
                detail = f" ({response.stop_details.explanation})"
            raise RuntimeError("Claude a refuzat această cerere din motive de siguranță." + detail)

        reply = "".join(block.text for block in response.content if block.type == "text")
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def reset(self) -> None:
        self.messages.clear()


def friendly_error(exc: Exception) -> str:
    """Transforma erorile API in mesaje pe intelesul utilizatorului."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "Cheia API este invalidă. Verifică-o în Setări."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "Cheia API nu are permisiunile necesare."
    if isinstance(exc, anthropic.NotFoundError):
        return "Modelul selectat nu este disponibil pentru contul tău."
    if isinstance(exc, anthropic.RateLimitError):
        return "Limită de utilizare atinsă. Așteaptă puțin și încearcă din nou."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Eroare API ({exc.status_code}). Încearcă din nou."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Nu m-am putut conecta la API. Verifică conexiunea la internet."
    return f"Eroare: {exc}"
