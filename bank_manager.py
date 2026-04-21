"""
Bank Account Manager - Windows Desktop Application
Verwaltung von Bankzugängen mit PDF-Export
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sqlite3
import os
import base64
from datetime import datetime
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER


# --- Datenbankpfad ---
APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "BankAccountManager"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "bankaccounts.db"
KEY_FILE = APP_DIR / "key.bin"


# --- Verschlüsselung ---
def _get_or_create_key() -> bytes:
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    salt = os.urandom(16)
    machine_id = (os.getenv("COMPUTERNAME", "default") + os.getenv("USERNAME", "user")).encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = base64.urlsafe_b64encode(kdf.derive(machine_id))
    KEY_FILE.write_bytes(salt + key)
    return salt + key


def _load_fernet() -> Fernet:
    data = _get_or_create_key()
    return Fernet(data[16:])


FERNET = _load_fernet()


def encrypt(plaintext: str) -> str:
    return FERNET.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return FERNET.decrypt(token.encode()).decode()
    except Exception:
        return "*** Fehler beim Entschlüsseln ***"


# --- Datenbank ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_name       TEXT    NOT NULL,
            account_number  TEXT,
            login_url       TEXT,
            username        TEXT,
            password        TEXT,
            balance         REAL,
            balance_date    TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # Migration: Kontonummer zu bestehender Datenbank hinzufügen
    try:
        conn.execute("ALTER TABLE accounts ADD COLUMN account_number TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def get_all_accounts():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, bank_name, account_number, login_url, username, "
        "password, balance, balance_date, notes "
        "FROM accounts ORDER BY bank_name"
    ).fetchall()
    conn.close()
    return rows


def insert_account(bank_name, account_number, login_url, username, password,
                   balance, balance_date, notes):
    enc_password = encrypt(password) if password else ""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO accounts "
        "(bank_name, account_number, login_url, username, password, balance, balance_date, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (bank_name, account_number, login_url, username, enc_password, balance, balance_date, notes)
    )
    conn.commit()
    conn.close()


def update_account(account_id, bank_name, account_number, login_url, username,
                   password, balance, balance_date, notes):
    enc_password = encrypt(password) if password else ""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE accounts SET bank_name=?, account_number=?, login_url=?, username=?, "
        "password=?, balance=?, balance_date=?, notes=? WHERE id=?",
        (bank_name, account_number, login_url, username, enc_password,
         balance, balance_date, notes, account_id)
    )
    conn.commit()
    conn.close()


def delete_account(account_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn.commit()
    conn.close()


# --- PDF-Export ---
def export_pdf(filepath: str, accounts: list, show_passwords: bool):
    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(A4),
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2.5 * cm, bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Heading1"],
        fontSize=18, spaceAfter=6, alignment=TA_CENTER,
        textColor=colors.HexColor("#1a3c5e")
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"],
        fontSize=9, spaceAfter=16, alignment=TA_CENTER, textColor=colors.grey
    )
    cell_style = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=11)

    elements = []
    elements.append(Paragraph("Bank Account Manager", title_style))
    elements.append(Paragraph(
        f"Erstellt am {datetime.now().strftime('%d.%m.%Y  %H:%M')} Uhr  |  "
        f"{len(accounts)} Konto/Konten",
        subtitle_style
    ))

    headers = ["Bank", "Kontonummer", "Login-URL", "Benutzername",
               "Passwort", "Kontostand", "Stand-Datum"]
    # Gesamtbreite A4 quer: 25.7 cm nutzbar
    col_widths = [4.0*cm, 3.5*cm, 5.2*cm, 4.0*cm, 3.5*cm, 2.8*cm, 2.7*cm]

    table_data = [headers]
    for row in accounts:
        _, bank_name, account_number, login_url, username, pw_enc, balance, balance_date, _ = row
        pw = decrypt(pw_enc) if show_passwords and pw_enc else ("●" * 8 if pw_enc else "")
        bal_str = (
            f"{balance:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
            if balance is not None else ""
        )
        table_data.append([
            Paragraph(bank_name or "", cell_style),
            Paragraph(account_number or "", cell_style),
            Paragraph(login_url or "", cell_style),
            Paragraph(username or "", cell_style),
            Paragraph(pw, cell_style),
            Paragraph(bal_str, cell_style),
            Paragraph(balance_date or "", cell_style),
        ])

    header_bg = colors.HexColor("#1a3c5e")
    row_alt   = colors.HexColor("#eef3f8")

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 9),
        ("TOPPADDING",    (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#aabbcc")),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, row_alt]),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
    ]))
    elements.append(t)

    if not show_passwords:
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(Paragraph(
            "Hinweis: Passwörter wurden aus Sicherheitsgründen nicht im Klartext exportiert.",
            ParagraphStyle("hint", parent=styles["Normal"], fontSize=7, textColor=colors.grey)
        ))

    doc.build(elements)


# --- Hilfsfunktionen ---
def format_balance(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return ""


def parse_balance(text: str):
    text = text.strip().replace("€", "").replace(" ", "").replace(".", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# --- Dialog: Konto hinzufügen / bearbeiten ---
class AccountDialog(tk.Toplevel):
    def __init__(self, parent, title: str, data: dict = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.result = None
        self._build_ui(data or {})
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self, data: dict):
        pad = {"padx": 10, "pady": 4}
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        fields = [
            ("Bankname *",                "bank_name",      False),
            ("Kontonummer",               "account_number", False),
            ("Login-URL",                 "login_url",      False),
            ("Benutzername",              "username",       False),
            ("Passwort",                  "password",       True),
            ("Kontostand (€)",            "balance",        False),
            ("Stand-Datum (TT.MM.JJJJ)", "balance_date",   False),
        ]

        self._vars = {}
        for row_idx, (label, key, is_pw) in enumerate(fields):
            ttk.Label(frame, text=label, width=26, anchor="w").grid(
                row=row_idx, column=0, sticky="w", **pad
            )
            var = tk.StringVar(value=data.get(key, ""))
            self._vars[key] = var
            entry = ttk.Entry(frame, textvariable=var, width=36,
                              show="●" if is_pw else "")
            entry.grid(row=row_idx, column=1, sticky="ew", **pad)
            if row_idx == 0:
                entry.focus()

        ttk.Label(frame, text="Notizen", anchor="w").grid(
            row=len(fields), column=0, sticky="nw", **pad
        )
        self._notes_text = tk.Text(frame, width=36, height=3, font=("Segoe UI", 9))
        self._notes_text.grid(row=len(fields), column=1, sticky="ew", **pad)
        self._notes_text.insert("1.0", data.get("notes", ""))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=len(fields) + 1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Speichern",  command=self._on_save,  width=14).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Abbrechen",  command=self.destroy,   width=14).pack(side=tk.LEFT, padx=6)

    def _on_save(self):
        bank_name = self._vars["bank_name"].get().strip()
        if not bank_name:
            messagebox.showwarning("Pflichtfeld", "Bitte einen Banknamen eingeben.", parent=self)
            return

        balance_text = self._vars["balance"].get().strip()
        balance = parse_balance(balance_text) if balance_text else None
        if balance_text and balance is None:
            messagebox.showwarning("Ungültig", "Der Kontostand enthält ungültige Zeichen.", parent=self)
            return

        self.result = {
            "bank_name":      bank_name,
            "account_number": self._vars["account_number"].get().strip(),
            "login_url":      self._vars["login_url"].get().strip(),
            "username":       self._vars["username"].get().strip(),
            "password":       self._vars["password"].get(),
            "balance":        balance,
            "balance_date":   self._vars["balance_date"].get().strip(),
            "notes":          self._notes_text.get("1.0", "end-1c").strip(),
        }
        self.destroy()


# --- Hauptfenster ---
class BankManagerApp(tk.Tk):
    COLUMNS = ("bank_name", "account_number", "login_url", "username", "balance", "balance_date")
    COL_LABELS = {
        "bank_name":      "Bank",
        "account_number": "Kontonummer",
        "login_url":      "Login-URL",
        "username":       "Benutzername",
        "balance":        "Kontostand",
        "balance_date":   "Stand-Datum",
    }
    COL_WIDTHS = {
        "bank_name":      150,
        "account_number": 130,
        "login_url":      200,
        "username":       130,
        "balance":        100,
        "balance_date":    95,
    }

    # Toolbar-Farben (tk.Button respektiert diese, ttk.Button ignoriert sie auf Windows)
    TB_BG        = "#1a3c5e"   # Toolbar-Hintergrund
    BTN_BG       = "#f0f4f8"   # Button-Hintergrund (helles Grau-Blau)
    BTN_FG       = "#1a3c5e"   # Button-Text (dunkles Blau)
    BTN_ACTIVE   = "#d0dce8"   # Button hover

    def __init__(self):
        super().__init__()
        self.title("Bank Account Manager")
        self.geometry("980x560")
        self.minsize(780, 420)
        self._configure_style()
        self._build_ui()
        self._load_accounts()

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

    def _toolbar_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command,
            bg=self.BTN_BG, fg=self.BTN_FG,
            activebackground=self.BTN_ACTIVE, activeforeground=self.BTN_FG,
            font=("Segoe UI", 9, "bold"),
            relief="flat", bd=0,
            padx=12, pady=5,
            cursor="hand2",
        )

    def _build_ui(self):
        # Toolbar
        toolbar = tk.Frame(self, bg=self.TB_BG, height=44)
        toolbar.pack(fill=tk.X, side=tk.TOP)
        toolbar.pack_propagate(False)

        self._toolbar_button(toolbar, "＋  Neu",          self._add_account).pack(side=tk.LEFT, padx=(8, 2), pady=6)
        self._toolbar_button(toolbar, "✎  Bearbeiten",    self._edit_account).pack(side=tk.LEFT, padx=2, pady=6)
        self._toolbar_button(toolbar, "✕  Löschen",       self._delete_account).pack(side=tk.LEFT, padx=2, pady=6)
        tk.Frame(toolbar, bg="#3a6a94", width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=8)
        self._toolbar_button(toolbar, "PDF exportieren",  self._export_pdf).pack(side=tk.LEFT, padx=2, pady=6)

        # Suchleiste
        search_frame = ttk.Frame(self, padding=(8, 6, 8, 0))
        search_frame.pack(fill=tk.X)
        ttk.Label(search_frame, text="Suche:").pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter())
        ttk.Entry(search_frame, textvariable=self._search_var, width=30).pack(side=tk.LEFT, padx=6)
        ttk.Button(search_frame, text="✕", width=3,
                   command=lambda: self._search_var.set("")).pack(side=tk.LEFT)

        # Tabelle
        tree_frame = ttk.Frame(self, padding=(8, 4, 8, 0))
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(
            tree_frame, columns=self.COLUMNS, show="headings", selectmode="browse"
        )
        for col in self.COLUMNS:
            self._tree.heading(col, text=self.COL_LABELS[col],
                               command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=self.COL_WIDTHS[col], minwidth=60)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", lambda _e: self._edit_account())
        self._tree.bind("<Delete>",   lambda _e: self._delete_account())

        # Statuszeile
        self._status_var = tk.StringVar()
        ttk.Label(self, textvariable=self._status_var, anchor="w",
                  padding=(10, 4)).pack(fill=tk.X, side=tk.BOTTOM)

        self._all_rows: list = []
        self._sort_col = "bank_name"
        self._sort_asc = True

    # --- Datenzugriff ---
    def _load_accounts(self):
        self._all_rows = get_all_accounts()
        self._refresh_tree(self._all_rows)

    def _refresh_tree(self, rows: list):
        self._tree.delete(*self._tree.get_children())
        for row in rows:
            _, bank_name, account_number, login_url, username, _pw, balance, balance_date, _ = row
            self._tree.insert("", "end", iid=str(row[0]),
                               values=(bank_name, account_number, login_url,
                                       username, format_balance(balance), balance_date))
        n     = len(rows)
        total = len(self._all_rows)
        self._status_var.set(
            f"{n} Konto/Konten angezeigt" + (f"  (von {total} gesamt)" if n != total else "")
        )

    def _filter(self):
        q = self._search_var.get().lower()
        if not q:
            self._refresh_tree(self._all_rows)
            return
        self._refresh_tree([r for r in self._all_rows
                            if any(q in str(v).lower() for v in r[1:])])

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col, self._sort_asc = col, True
        db_col_map = {
            "bank_name": 1, "account_number": 2, "login_url": 3,
            "username": 4, "balance": 6, "balance_date": 7,
        }
        db_idx = db_col_map[col]
        self._all_rows.sort(
            key=lambda r: (r[db_idx] is None, r[db_idx] if r[db_idx] is not None else ""),
            reverse=not self._sort_asc,
        )
        self._filter()

    def _selected_id(self):
        sel = self._tree.selection()
        return int(sel[0]) if sel else None

    def _row_by_id(self, account_id: int):
        return next((r for r in self._all_rows if r[0] == account_id), None)

    # --- Aktionen ---
    def _add_account(self):
        dlg = AccountDialog(self, "Neuen Bankzugang anlegen")
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            insert_account(d["bank_name"], d["account_number"], d["login_url"],
                           d["username"], d["password"], d["balance"],
                           d["balance_date"], d["notes"])
            self._load_accounts()

    def _edit_account(self):
        account_id = self._selected_id()
        if account_id is None:
            messagebox.showinfo("Hinweis", "Bitte zuerst einen Eintrag auswählen.")
            return
        row = self._row_by_id(account_id)
        if row is None:
            return
        _, bank_name, account_number, login_url, username, pw_enc, balance, balance_date, notes = row
        data = {
            "bank_name":      bank_name      or "",
            "account_number": account_number or "",
            "login_url":      login_url      or "",
            "username":       username       or "",
            "password":       decrypt(pw_enc) if pw_enc else "",
            "balance":        format_balance(balance),
            "balance_date":   balance_date   or "",
            "notes":          notes          or "",
        }
        dlg = AccountDialog(self, f"Bankzugang bearbeiten – {bank_name}", data)
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            update_account(account_id, d["bank_name"], d["account_number"], d["login_url"],
                           d["username"], d["password"], d["balance"],
                           d["balance_date"], d["notes"])
            self._load_accounts()

    def _delete_account(self):
        account_id = self._selected_id()
        if account_id is None:
            messagebox.showinfo("Hinweis", "Bitte zuerst einen Eintrag auswählen.")
            return
        row = self._row_by_id(account_id)
        bank_name = row[1] if row else str(account_id)
        if messagebox.askyesno("Löschen bestätigen",
                               f'Bankzugang „{bank_name}" wirklich löschen?',
                               icon="warning"):
            delete_account(account_id)
            self._load_accounts()

    def _export_pdf(self):
        if not self._all_rows:
            messagebox.showinfo("Keine Daten", "Es sind keine Bankzugänge vorhanden.")
            return

        show_pw = messagebox.askyesno(
            "PDF-Export",
            "Sollen Passwörter im Klartext in der PDF erscheinen?\n\n"
            "Bewahren Sie das Dokument dann sicher auf!",
            icon="warning",
        )
        default_name = f"Bankzugaenge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF-Dokument", "*.pdf")],
            initialfile=default_name,
            title="PDF speichern unter …",
        )
        if not filepath:
            return
        try:
            export_pdf(filepath, self._all_rows, show_pw)
            if messagebox.askyesno("Erfolg",
                                   f"PDF wurde gespeichert:\n{filepath}\n\nJetzt öffnen?"):
                os.startfile(filepath)
        except Exception as exc:
            messagebox.showerror("Fehler beim PDF-Export", str(exc))


# --- Einstiegspunkt ---
if __name__ == "__main__":
    init_db()
    app = BankManagerApp()
    app.mainloop()
