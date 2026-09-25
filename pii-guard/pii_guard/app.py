"""Interfata grafica PII Guard Chat (Tkinter).

Fluxul: scrii text cu date reale -> aplicatia detecteaza si inlocuieste PII
local -> (optional) confirmi ce se trimite -> Claude primeste doar
placeholdere -> raspunsul e rescris local cu datele reale.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import config as config_store
from .anonymizer import Anonymizer
from .claude_client import AVAILABLE_MODELS, ClaudeChat, friendly_error

APP_TITLE = "PII Guard Chat"

KIND_LABELS = {
    "CNP": "CNP",
    "IBAN": "IBAN",
    "CUI": "CUI/CIF",
    "EMAIL": "Email",
    "TELEFON": "Telefon",
    "CARD": "Card bancar",
    "SERIE_CI": "Serie CI",
    "ADRESA": "Adresă",
    "TERMEN": "Termen protejat",
}


class App:
    def __init__(self) -> None:
        self.config = config_store.load()
        self.anonymizer = Anonymizer()
        self.chat: ClaudeChat | None = None
        self.busy = False
        self.stream_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("1080x680")
        self.root.minsize(820, 520)
        self._build_ui()
        self._append_info(
            "Bun venit! Scrie mai jos sau deschide un fișier. Datele personale "
            "(CNP, IBAN, email, telefon, adrese...) sunt anonimizate automat "
            "înainte de a fi trimise la Claude și restaurate local în răspuns."
        )
        if not self.config["api_key"]:
            self.root.after(300, self.open_settings)

    # ------------------------------------------------------------------
    # Construirea interfetei
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Send.TButton", font=("Segoe UI", 10, "bold"))

        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Model:").pack(side="left")
        self.model_var = tk.StringVar(value=self.config["model"])
        model_box = ttk.Combobox(
            toolbar, textvariable=self.model_var, values=AVAILABLE_MODELS,
            state="readonly", width=22,
        )
        model_box.pack(side="left", padx=(4, 12))
        model_box.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())

        ttk.Button(toolbar, text="📄 Deschide fișier…", command=self.open_file).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🗑 Conversație nouă", command=self.new_conversation).pack(side="left", padx=2)
        ttk.Button(toolbar, text="⚙ Setări API", command=self.open_settings).pack(side="right", padx=2)

        self.confirm_var = tk.BooleanVar(value=self.config["confirm_before_send"])
        ttk.Checkbutton(
            toolbar, text="Confirmă textul anonimizat înainte de trimitere",
            variable=self.confirm_var, command=self._save_config,
        ).pack(side="right", padx=10)

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        # --- Stanga: chat + input ---
        left = ttk.Frame(main)
        main.add(left, weight=3)

        self.chat_view = scrolledtext.ScrolledText(
            left, wrap="word", state="disabled", font=("Segoe UI", 10),
            padx=10, pady=8, background="white",
        )
        self.chat_view.pack(fill="both", expand=True)
        self.chat_view.tag_configure("user", foreground="#0b5394", font=("Segoe UI", 10, "bold"))
        self.chat_view.tag_configure("assistant", foreground="#38761d", font=("Segoe UI", 10, "bold"))
        self.chat_view.tag_configure("info", foreground="#666666", font=("Segoe UI", 9, "italic"))
        self.chat_view.tag_configure("error", foreground="#cc0000")
        self.chat_view.tag_configure("body", foreground="#222222")

        input_row = ttk.Frame(left)
        input_row.pack(fill="x", pady=(6, 0))
        self.input_box = tk.Text(input_row, height=4, wrap="word", font=("Segoe UI", 10))
        self.input_box.pack(side="left", fill="both", expand=True)
        self.input_box.bind("<Control-Return>", lambda e: (self.send(), "break")[1])
        self.send_button = ttk.Button(
            input_row, text="Trimite ➤\n(Ctrl+Enter)", style="Send.TButton", command=self.send,
        )
        self.send_button.pack(side="left", fill="y", padx=(6, 0))

        # --- Dreapta: panoul de date protejate ---
        right = ttk.Frame(main)
        main.add(right, weight=1)

        ttk.Label(right, text="Date anonimizate în această sesiune",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        self.mapping_view = ttk.Treeview(
            right, columns=("tip", "placeholder", "valoare"), show="headings", height=12,
        )
        for col, title, width in (("tip", "Tip", 90), ("placeholder", "Placeholder", 100),
                                  ("valoare", "Valoare reală (rămâne local)", 180)):
            self.mapping_view.heading(col, text=title)
            self.mapping_view.column(col, width=width, anchor="w")
        self.mapping_view.pack(fill="both", expand=True)

        term_frame = ttk.LabelFrame(right, text="Protejează un termen (nume, firmă…)", padding=6)
        term_frame.pack(fill="x", pady=(8, 0))
        self.term_entry = ttk.Entry(term_frame)
        self.term_entry.pack(side="left", fill="x", expand=True)
        self.term_entry.bind("<Return>", lambda e: self.add_term())
        ttk.Button(term_frame, text="Adaugă", command=self.add_term).pack(side="left", padx=(6, 0))

        self.terms_label = ttk.Label(right, wraplength=280, foreground="#555555")
        self.terms_label.pack(anchor="w", pady=(4, 0))
        self._refresh_terms_label()

        self.status_var = tk.StringVar(value="Pregătit.")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken",
                  anchor="w", padding=(8, 3)).pack(fill="x", side="bottom")

    # ------------------------------------------------------------------
    # Actiuni
    # ------------------------------------------------------------------

    def send(self) -> None:
        if self.busy:
            return
        text = self.input_box.get("1.0", "end").strip()
        if not text:
            return
        if not self.config["api_key"]:
            messagebox.showwarning(APP_TITLE, "Setează mai întâi cheia API în Setări.")
            self.open_settings()
            return

        result = self.anonymizer.anonymize(text, self.config["custom_terms"])
        if self.confirm_var.get() and not self._confirm_dialog(result.text, len(result.matches)):
            return

        self.input_box.delete("1.0", "end")
        self._append_message("Tu", "user", text)
        self._refresh_mapping()
        self._set_busy(True, f"Claude ({self.model_var.get()}) scrie…")

        if self.chat is None:
            self.chat = ClaudeChat(self.config["api_key"], self.model_var.get())
        self.chat.model = self.model_var.get()

        threading.Thread(target=self._send_worker, args=(result.text,), daemon=True).start()
        self._begin_stream_display()

    def _send_worker(self, anonymized_text: str) -> None:
        try:
            self.chat.send(anonymized_text, on_text=lambda t: self.stream_queue.put(("text", t)))
            self.stream_queue.put(("done", None))
        except Exception as exc:  # afisat prietenos in interfata
            self.stream_queue.put(("error", friendly_error(exc)))

    def _begin_stream_display(self) -> None:
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", "Claude:\n", "assistant")
        # Ancora de la care rescriem raspunsul pe masura ce vine
        self.chat_view.mark_set("stream_anchor", "end-1c")
        self.chat_view.mark_gravity("stream_anchor", "left")
        self.chat_view.configure(state="disabled")
        self._stream_buffer = ""
        self._poll_stream()

    def _poll_stream(self) -> None:
        try:
            while True:
                event, payload = self.stream_queue.get_nowait()
                if event == "text":
                    self._stream_buffer += payload
                    self._render_stream_tail()
                elif event == "done":
                    self._finish_stream()
                    return
                elif event == "error":
                    self._append_raw("\n", "body")
                    self._append_raw(payload + "\n\n", "error")
                    self._set_busy(False, "Eroare.")
                    return
        except queue.Empty:
            pass
        self.root.after(60, self._poll_stream)

    def _render_stream_tail(self) -> None:
        # Rescriem intregul raspuns partial la fiecare fragment: un placeholder
        # poate sosi rupt in bucati, iar de-anonimizarea se aplica pe tot textul.
        display = self.anonymizer.deanonymize(self._stream_buffer)
        self.chat_view.configure(state="normal")
        self.chat_view.delete("stream_anchor", "end")
        self.chat_view.insert("end", display, "body")
        self.chat_view.see("end")
        self.chat_view.configure(state="disabled")

    def _finish_stream(self) -> None:
        display = self.anonymizer.deanonymize(self._stream_buffer)
        self.chat_view.configure(state="normal")
        self.chat_view.delete("stream_anchor", "end")
        self.chat_view.mark_unset("stream_anchor")
        self.chat_view.insert("end", display + "\n\n", "body")
        self.chat_view.see("end")
        self.chat_view.configure(state="disabled")
        self._set_busy(False, "Pregătit.")

    def _confirm_dialog(self, anonymized: str, count: int) -> bool:
        if count == 0:
            return True  # nimic sensibil - trimitem direct
        dialog = tk.Toplevel(self.root)
        dialog.title("Verifică textul trimis la Claude")
        dialog.geometry("640x420")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(
            dialog, padding=8,
            text=f"Au fost anonimizate {count} date personale. Exact acest text va fi trimis:",
        ).pack(anchor="w")
        preview = scrolledtext.ScrolledText(dialog, wrap="word", font=("Consolas", 9))
        preview.insert("1.0", anonymized)
        preview.configure(state="disabled")
        preview.pack(fill="both", expand=True, padx=8)
        answer = {"ok": False}
        buttons = ttk.Frame(dialog, padding=8)
        buttons.pack(fill="x")

        def close(ok: bool) -> None:
            answer["ok"] = ok
            dialog.destroy()

        ttk.Button(buttons, text="Trimite ➤", command=lambda: close(True)).pack(side="right")
        ttk.Button(buttons, text="Anulează", command=lambda: close(False)).pack(side="right", padx=6)
        dialog.wait_window()
        return answer["ok"]

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Alege un fișier text",
            filetypes=[("Fișiere text", "*.txt *.md *.csv *.log"), ("Toate fișierele", "*.*")],
        )
        if not path:
            return
        try:
            content = open(path, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Nu am putut citi fișierul: {exc}")
            return
        self.input_box.insert("end", content)
        self.status_var.set(f"Fișier încărcat în caseta de mesaj: {path}")

    def new_conversation(self) -> None:
        if self.busy:
            return
        if self.chat:
            self.chat.reset()
        self.anonymizer.reset()
        self._refresh_mapping()
        self.chat_view.configure(state="normal")
        self.chat_view.delete("1.0", "end")
        self.chat_view.configure(state="disabled")
        self._append_info("Conversație nouă. Istoricul și harta de anonimizare au fost golite.")

    def add_term(self) -> None:
        term = self.term_entry.get().strip()
        if len(term) < 2:
            return
        if term.lower() not in (t.lower() for t in self.config["custom_terms"]):
            self.config["custom_terms"].append(term)
            self._save_config()
            self._refresh_terms_label()
        self.term_entry.delete(0, "end")

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Setări API")
        dialog.geometry("520x220")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Cheie API Anthropic (o obții de pe platform.claude.com → API keys):").pack(anchor="w")
        key_var = tk.StringVar(value=self.config["api_key"])
        entry = ttk.Entry(frame, textvariable=key_var, show="•", width=60)
        entry.pack(fill="x", pady=(4, 8))
        show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Arată cheia", variable=show_var,
            command=lambda: entry.configure(show="" if show_var.get() else "•"),
        ).pack(anchor="w")
        ttk.Label(
            frame, foreground="#555555", wraplength=480,
            text="Cheia se salvează doar local, în ~/.pii-guard/config.json. "
                 "Termenii protejați se salvează în același fișier.",
        ).pack(anchor="w", pady=(8, 0))

        def save_settings() -> None:
            self.config["api_key"] = key_var.get().strip()
            self._save_config()
            self.chat = None  # clientul se recreeaza cu noua cheie
            dialog.destroy()
            self.status_var.set("Setări salvate.")

        ttk.Button(frame, text="Salvează", command=save_settings).pack(side="right", pady=(12, 0))

    # ------------------------------------------------------------------
    # Utilitare interfata
    # ------------------------------------------------------------------

    def _append_message(self, who: str, tag: str, body: str) -> None:
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", f"{who}:\n", tag)
        self.chat_view.insert("end", body + "\n\n", "body")
        self.chat_view.see("end")
        self.chat_view.configure(state="disabled")

    def _append_info(self, text: str) -> None:
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", text + "\n\n", "info")
        self.chat_view.see("end")
        self.chat_view.configure(state="disabled")

    def _append_raw(self, text: str, tag: str) -> None:
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", text, tag)
        self.chat_view.see("end")
        self.chat_view.configure(state="disabled")

    def _refresh_mapping(self) -> None:
        self.mapping_view.delete(*self.mapping_view.get_children())
        for placeholder, value in self.anonymizer.mapping.items():
            kind = placeholder.strip("[]").rsplit("_", 1)[0]
            self.mapping_view.insert(
                "", "end", values=(KIND_LABELS.get(kind, kind), placeholder, value),
            )

    def _refresh_terms_label(self) -> None:
        terms = self.config["custom_terms"]
        self.terms_label.configure(
            text="Termeni protejați: " + (", ".join(terms) if terms else "niciunul"),
        )

    def _set_busy(self, busy: bool, status: str) -> None:
        self.busy = busy
        self.send_button.state(["disabled"] if busy else ["!disabled"])
        self.status_var.set(status)

    def _on_model_change(self) -> None:
        self.config["model"] = self.model_var.get()
        self._save_config()

    def _save_config(self) -> None:
        self.config["confirm_before_send"] = self.confirm_var.get()
        self.config["model"] = self.model_var.get()
        config_store.save(self.config)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
