#!/usr/bin/env python3
"""VW Keystroke GUI — a small dark Tkinter window: name it, paste it, drop it.

Writes the secret to a 600 env file and (optionally) upserts it into Vaultwarden/
Bitwarden. Vault work runs on a worker thread so the UI never freezes.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from . import core

BG = "#0f1420"
CARD = "#161c28"
FIELD = "#0b0f17"
FG = "#e6edf3"
MUTED = "#8b97a7"
ACCENT = "#2fbf71"
ACCENT_HI = "#3ad684"
DANGER = "#e5534b"
BORDER = "#243044"
FONT = ("Segoe UI", 11) if tk.TkVersion else ("sans-serif", 11)
MONO = ("JetBrains Mono", 10)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VW Keystroke")
        self.configure(bg=BG)
        self.resizable(False, False)
        try:
            self.tk.call("tk", "scaling", 1.25)
        except Exception:
            pass
        self.conf = core.load_conf()
        self._busy = False
        self._build()
        self._refresh_status()

    # ---------- UI ----------
    def _label(self, parent, text):
        return tk.Label(parent, text=text, bg=CARD, fg=MUTED,
                        font=("Segoe UI", 9, "bold"), anchor="w")

    def _entry(self, parent, show=None, textvariable=None):
        e = tk.Entry(parent, bg=FIELD, fg=FG, insertbackground=ACCENT,
                     relief="flat", font=("Segoe UI", 11), show=show or "",
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, textvariable=textvariable)
        e.configure(bd=6)
        return e

    def _build(self):
        pad = dict(padx=22)
        # header
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", pady=(18, 6), **pad)
        tk.Label(head, text="🔑  VW Keystroke", bg=BG, fg=FG,
                 font=("Segoe UI", 17, "bold")).pack(side="left")
        self.status_pill = tk.Label(head, text="…", bg=BG, fg=MUTED,
                                     font=("Segoe UI", 9, "bold"))
        self.status_pill.pack(side="right", pady=(6, 0))
        tk.Label(self, text="Paste a secret → local env file + your vault.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", **pad)

        card = tk.Frame(self, bg=CARD, highlightthickness=1,
                        highlightbackground=BORDER)
        card.pack(fill="both", expand=True, padx=18, pady=14)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="both", expand=True, padx=18, pady=16)

        # env var
        self._label(inner, "ENV VARIABLE NAME").pack(fill="x")
        self.var_e = self._entry(inner)
        self.var_e.pack(fill="x", pady=(3, 12))

        # project (combobox of existing + free text)
        self._label(inner, "PROJECT  →  ~/.config/<project>.env").pack(fill="x")
        edir = core.env_dir(self.conf)
        projects = core.list_projects(edir)
        self.proj_v = tk.StringVar(value=core.default_project(self.conf))
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("VW.TCombobox", fieldbackground=FIELD, background=FIELD,
                        foreground=FG, arrowcolor=MUTED, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        self.proj_e = ttk.Combobox(inner, textvariable=self.proj_v, values=projects,
                                   style="VW.TCombobox", font=("Segoe UI", 11))
        self.proj_e.pack(fill="x", pady=(3, 12), ipady=3)

        # vault item name (optional)
        self._label(inner, "VAULT ITEM NAME  (blank = same as variable)").pack(fill="x")
        self.name_e = self._entry(inner)
        self.name_e.pack(fill="x", pady=(3, 12))

        # secret
        self._label(inner, "SECRET VALUE").pack(fill="x")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(3, 6))
        self.secret_e = self._entry(row, show="•")
        self.secret_e.pack(side="left", fill="x", expand=True)
        self.show_v = tk.IntVar(value=0)
        tk.Checkbutton(row, text="show", variable=self.show_v, command=self._toggle_show,
                       bg=CARD, fg=MUTED, selectcolor=FIELD, activebackground=CARD,
                       activeforeground=FG, font=("Segoe UI", 9), bd=0,
                       highlightthickness=0).pack(side="left", padx=(8, 0))

        # also-to-vault toggle
        self.vault_v = tk.IntVar(value=1)
        tk.Checkbutton(inner, text="Also save to Vaultwarden", variable=self.vault_v,
                       bg=CARD, fg=FG, selectcolor=FIELD, activebackground=CARD,
                       activeforeground=FG, font=("Segoe UI", 10), bd=0,
                       highlightthickness=0).pack(anchor="w", pady=(6, 10))

        # buttons
        btns = tk.Frame(inner, bg=CARD)
        btns.pack(fill="x")
        self.drop_b = tk.Button(btns, text="Drop it  ⏎", command=self.on_drop,
                                bg=ACCENT, fg="#062a17", activebackground=ACCENT_HI,
                                activeforeground="#062a17", relief="flat",
                                font=("Segoe UI", 11, "bold"), bd=0, padx=16, pady=8,
                                cursor="hand2")
        self.drop_b.pack(side="left")
        tk.Button(btns, text="Lock", command=self.on_lock, bg=CARD, fg=MUTED,
                  activebackground=CARD, activeforeground=DANGER, relief="flat",
                  font=("Segoe UI", 10), bd=0, padx=10, pady=8, cursor="hand2"
                  ).pack(side="right")

        # status line
        self.status = tk.Label(self, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10),
                               wraplength=420, justify="left", anchor="w")
        self.status.pack(fill="x", padx=22, pady=(0, 16))

        self.bind("<Return>", lambda e: self.on_drop())
        self.var_e.focus_set()

    def _toggle_show(self):
        self.secret_e.configure(show="" if self.show_v.get() else "•")

    def _set_status(self, text, color=MUTED):
        self.status.configure(text=text, fg=color)

    def _refresh_status(self):
        def work():
            try:
                st = core.session_state(self.conf)
            except Exception:
                st = "login"
            self.after(0, lambda: self._show_pill(st))
        threading.Thread(target=work, daemon=True).start()

    def _show_pill(self, st):
        m = {"ready": ("🔓 unlocked", ACCENT), "apikey": ("🔑 api-key", ACCENT),
             "locked": ("🔒 locked", MUTED), "login": ("⚠ needs login", DANGER)}
        text, color = m.get(st, ("…", MUTED))
        self.status_pill.configure(text=text, fg=color)

    # ---------- actions ----------
    def on_lock(self):
        core.lock()
        self._set_status("Vault locked; cached session cleared.", MUTED)
        self._refresh_status()

    def on_drop(self):
        if self._busy:
            return
        var = self.var_e.get().strip()
        if not core.valid_var(var):
            self._set_status("Enter a valid ENV variable name (letters, digits, _).", DANGER)
            return
        secret = self.secret_e.get()
        if not secret:
            self._set_status("Paste a secret value first.", DANGER)
            return
        project = (self.proj_v.get().strip() or core.default_project(self.conf))
        name = self.name_e.get().strip() or None
        no_vault = not self.vault_v.get()

        mp = None
        if not no_vault:
            state = core.session_state(self.conf)
            if state == "login":
                messagebox.showinfo(
                    "One-time login",
                    "Not logged in yet. Run this once in a terminal:\n\n    bw login\n\n"
                    "(email + master password + 2FA). Then come back and Drop it.")
                return
            if state == "locked":
                mp = simpledialog.askstring("Unlock vault", "Vault master password:",
                                            show="•", parent=self)
                if not mp:
                    return

        self._busy = True
        self.drop_b.configure(state="disabled", text="Working…")
        self._set_status("Working…", MUTED)

        def work():
            try:
                res = core.drop(var, secret, project=project, name=name,
                                no_vault=no_vault, master_password=mp, conf=self.conf)
                self.after(0, lambda: self._done(res))
            except core.NeedUnlock:
                self.after(0, lambda: self._fail("Wrong or missing master password."))
            except core.NeedLogin as e:
                self.after(0, lambda: self._fail(str(e)))
            except core.VwksError as e:
                self.after(0, lambda: self._fail(str(e)))
            except Exception as e:  # pragma: no cover
                self.after(0, lambda: self._fail(f"Unexpected error: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, res):
        self._busy = False
        self.drop_b.configure(state="normal", text="Drop it  ⏎")
        msg = f"✓ {res['env_action']} in {res['env_path']}"
        if res["vault"]:
            msg += f"\n✓ vault: {res['vault']} in “{res['folder']}”"
        self._set_status(msg, ACCENT)
        self.secret_e.delete(0, "end")
        self.var_e.delete(0, "end")
        self.show_v.set(0)
        self._toggle_show()
        # refresh project dropdown + pill
        self.proj_e.configure(values=core.list_projects(core.env_dir(self.conf)))
        self.var_e.focus_set()
        self._refresh_status()

    def _fail(self, text):
        self._busy = False
        self.drop_b.configure(state="normal", text="Drop it  ⏎")
        self._set_status("✗ " + text, DANGER)
        self._refresh_status()


def main():
    try:
        app = App()
    except tk.TclError as e:
        raise SystemExit(f"VW Keystroke GUI needs a display: {e}")
    app.mainloop()


if __name__ == "__main__":
    main()
