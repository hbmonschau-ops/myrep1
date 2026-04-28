"""
Bank Account Manager - Windows Desktop Application
Verwaltung von Bankzugängen, Verträgen und Versicherungen mit PDF-Export
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import os
import shutil
import subprocess
import sys
import base64
from uuid import uuid4
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


# ---------------------------------------------------------------------------
# Datenbankpfad & Verschlüsselung
# ---------------------------------------------------------------------------
# Portable-Modus: wenn neben der .py/.pyw-Datei ein "profiles"-Ordner existiert
# (oder der übergeordnete Ordner beschreibbar ist), liegen Daten dort.
_SCRIPT_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent

# Portable-Modus: wenn neben der .pyw-Datei ein "profiles"-Ordner existiert,
# werden alle Daten dort gespeichert (z. B. für USB-Stick-Nutzung).
if (_SCRIPT_DIR / "profiles").exists():
    APP_DIR = _SCRIPT_DIR
else:
    APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "BankAccountManager"

PROFILES_DIR  = APP_DIR / "profiles"
PROFILES_FILE = APP_DIR / "profiles.json"
APP_DIR.mkdir(parents=True, exist_ok=True)
PROFILES_DIR.mkdir(exist_ok=True)

# Werden durch activate_profile() gesetzt:
DB_PATH         = None
DOCS_DIR        = None
KEY_FILE        = None
FERNET          = None
CURRENT_PROFILE = None


def _get_or_create_key() -> bytes:
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    salt = os.urandom(16)
    machine_id = (os.getenv("COMPUTERNAME", "default") + os.getenv("USERNAME", "user")).encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key = base64.urlsafe_b64encode(kdf.derive(machine_id))
    KEY_FILE.write_bytes(salt + key)
    return salt + key


def encrypt(plaintext: str) -> str:
    return FERNET.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return FERNET.decrypt(token.encode()).decode()
    except Exception:
        return "*** Fehler ***"


# ---------------------------------------------------------------------------
# Profil-Verwaltung
# ---------------------------------------------------------------------------
def get_profiles() -> list:
    if not PROFILES_FILE.exists():
        return []
    try:
        return json.loads(PROFILES_FILE.read_text(encoding="utf-8")).get("profiles", [])
    except Exception:
        return []


def _save_profiles(profiles: list, last_profile: str = None):
    data = {"profiles": profiles}
    if last_profile:
        data["last_profile"] = last_profile
    PROFILES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def create_profile(name: str):
    profiles = get_profiles()
    if any(p["name"] == name for p in profiles):
        raise ValueError(f"Profil '{name}' existiert bereits.")
    profiles.append({"name": name, "created_at": datetime.now().isoformat()})
    pdir = PROFILES_DIR / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "documents").mkdir(exist_ok=True)
    _save_profiles(profiles)


def delete_profile(name: str):
    profiles = [p for p in get_profiles() if p["name"] != name]
    pdir = PROFILES_DIR / name
    if pdir.exists():
        shutil.rmtree(pdir)
    _save_profiles(profiles)


def rename_profile(old_name: str, new_name: str):
    profiles = get_profiles()
    for p in profiles:
        if p["name"] == old_name:
            p["name"] = new_name
    old_dir = PROFILES_DIR / old_name
    new_dir = PROFILES_DIR / new_name
    if old_dir.exists():
        old_dir.rename(new_dir)
    _save_profiles(profiles)


def activate_profile(name: str):
    global DB_PATH, DOCS_DIR, KEY_FILE, FERNET, CURRENT_PROFILE
    CURRENT_PROFILE = name
    pdir = PROFILES_DIR / name
    pdir.mkdir(parents=True, exist_ok=True)
    DB_PATH  = pdir / "bankaccounts.db"
    DOCS_DIR = pdir / "documents"
    KEY_FILE = pdir / "key.bin"
    DOCS_DIR.mkdir(exist_ok=True)
    FERNET = Fernet(_get_or_create_key()[16:])
    profiles = get_profiles()
    for p in profiles:
        if p["name"] == name:
            p["last_used"] = datetime.now().isoformat()
    _save_profiles(profiles, name)
    init_db()


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)

    # --- Bankkonten ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bank_name       TEXT NOT NULL,
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
    for col in ("account_number",):
        try:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass

    # --- Verträge & Versicherungen ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            category        TEXT,
            name            TEXT NOT NULL,
            provider        TEXT,
            contract_number TEXT,
            login_url       TEXT,
            username        TEXT,
            password        TEXT,
            amount          REAL,
            interval        TEXT,
            start_date      TEXT,
            end_date        TEXT,
            notice_period   TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # --- Dokumente ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type   TEXT NOT NULL,
            entity_id     INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name   TEXT NOT NULL,
            file_size     INTEGER,
            description   TEXT,
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    try:
        conn.execute("ALTER TABLE documents ADD COLUMN text_content TEXT")
    except sqlite3.OperationalError:
        pass

    # --- Tags-Verwaltung ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#1a3c5e'
        )
    """)

    # --- Verknüpfung Account ↔ Tags ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_tags (
            account_id  INTEGER NOT NULL,
            tag_id      INTEGER NOT NULL,
            PRIMARY KEY (account_id, tag_id),
            FOREIGN KEY (account_id) REFERENCES accounts(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        )
    """)

    # --- Verknüpfung Contract ↔ Tags ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contract_tags (
            contract_id INTEGER NOT NULL,
            tag_id      INTEGER NOT NULL,
            PRIMARY KEY (contract_id, tag_id),
            FOREIGN KEY (contract_id) REFERENCES contracts(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        )
    """)

    conn.commit()
    conn.close()


# --- Bankkonten CRUD ---
def get_all_accounts():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, bank_name, account_number, login_url, username, "
        "password, balance, balance_date, notes FROM accounts ORDER BY bank_name"
    ).fetchall()
    conn.close()
    return rows


def insert_account(bank_name, account_number, login_url, username,
                   password, balance, balance_date, notes):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO accounts (bank_name,account_number,login_url,username,"
        "password,balance,balance_date,notes) VALUES (?,?,?,?,?,?,?,?)",
        (bank_name, account_number, login_url, username,
         encrypt(password) if password else "",
         balance, balance_date, notes)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_account(aid, bank_name, account_number, login_url, username,
                   password, balance, balance_date, notes):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE accounts SET bank_name=?,account_number=?,login_url=?,username=?,"
        "password=?,balance=?,balance_date=?,notes=? WHERE id=?",
        (bank_name, account_number, login_url, username,
         encrypt(password) if password else "",
         balance, balance_date, notes, aid)
    )
    conn.commit()
    conn.close()


def delete_account(aid):
    delete_entity_documents("account", aid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
    conn.commit()
    conn.close()


# --- Verträge CRUD ---
def get_all_contracts():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id,category,name,provider,contract_number,login_url,username,"
        "password,amount,interval,start_date,end_date,notice_period,notes "
        "FROM contracts ORDER BY category,name"
    ).fetchall()
    conn.close()
    return rows


def insert_contract(category, name, provider, contract_number, login_url,
                    username, password, amount, interval, start_date,
                    end_date, notice_period, notes):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO contracts (category,name,provider,contract_number,login_url,"
        "username,password,amount,interval,start_date,end_date,notice_period,notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (category, name, provider, contract_number, login_url, username,
         encrypt(password) if password else "",
         amount, interval, start_date, end_date, notice_period, notes)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_contract(cid, category, name, provider, contract_number, login_url,
                    username, password, amount, interval, start_date,
                    end_date, notice_period, notes):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE contracts SET category=?,name=?,provider=?,contract_number=?,"
        "login_url=?,username=?,password=?,amount=?,interval=?,start_date=?,"
        "end_date=?,notice_period=?,notes=? WHERE id=?",
        (category, name, provider, contract_number, login_url, username,
         encrypt(password) if password else "",
         amount, interval, start_date, end_date, notice_period, notes, cid)
    )
    conn.commit()
    conn.close()


def delete_contract(cid):
    delete_entity_documents("contract", cid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM contracts WHERE id=?", (cid,))
    conn.commit()
    conn.close()


# --- Dokumente CRUD ---
def get_documents(entity_type: str, entity_id: int):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, original_name, stored_name, file_size, description, created_at "
        "FROM documents WHERE entity_type=? AND entity_id=? ORDER BY created_at",
        (entity_type, entity_id)
    ).fetchall()
    conn.close()
    return rows


def add_document(entity_type: str, entity_id: int, src_path: str, description: str = "") -> bool:
    src = Path(src_path)
    if not src.exists():
        return False
    stored_name = f"{uuid4().hex}{src.suffix.lower()}"
    dest = DOCS_DIR / stored_name
    shutil.copy2(src, dest)
    text_content, _ = extract_text_from_file(dest)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO documents (entity_type,entity_id,original_name,stored_name,file_size,description,text_content) "
        "VALUES (?,?,?,?,?,?,?)",
        (entity_type, entity_id, src.name, stored_name, dest.stat().st_size, description, text_content)
    )
    conn.commit()
    conn.close()
    return True


def delete_document(doc_id: int):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT stored_name FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row:
        f = DOCS_DIR / row[0]
        if f.exists():
            f.unlink()
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    conn.commit()
    conn.close()


def delete_entity_documents(entity_type: str, entity_id: int):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT stored_name FROM documents WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id)
    ).fetchall()
    for (sn,) in rows:
        f = DOCS_DIR / sn
        if f.exists():
            f.unlink()
    conn.execute("DELETE FROM documents WHERE entity_type=? AND entity_id=?",
                 (entity_type, entity_id))
    conn.commit()
    conn.close()


def reindex_all_documents() -> tuple[int, list[str]]:
    """Returns (success_count, list_of_error_messages)."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, stored_name, original_name FROM documents").fetchall()
    success = 0
    errors = []
    for did, stored_name, orig_name in rows:
        path = DOCS_DIR / stored_name
        text, err = extract_text_from_file(path)
        conn.execute("UPDATE documents SET text_content=? WHERE id=?", (text, did))
        if err:
            errors.append(f"{orig_name}: {err}")
        else:
            success += 1
    conn.commit()
    conn.close()
    return success, errors


# --- Tags CRUD ---
def get_all_tags():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, name, color FROM tags ORDER BY name").fetchall()
    conn.close()
    return rows

def insert_tag(name: str, color: str = "#1a3c5e") -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("INSERT INTO tags (name, color) VALUES (?,?)", (name, color))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def update_tag(tag_id: int, name: str, color: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE tags SET name=?, color=? WHERE id=?", (name, color, tag_id))
    conn.commit()
    conn.close()

def delete_tag(tag_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM account_tags WHERE tag_id=?", (tag_id,))
    conn.execute("DELETE FROM contract_tags WHERE tag_id=?", (tag_id,))
    conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    conn.commit()
    conn.close()

def get_entry_tags(entity_type: str, entity_id: int) -> list:
    table = "account_tags" if entity_type == "account" else "contract_tags"
    id_col = "account_id" if entity_type == "account" else "contract_id"
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"SELECT t.id, t.name, t.color FROM tags t "
        f"JOIN {table} et ON t.id = et.tag_id "
        f"WHERE et.{id_col}=? ORDER BY t.name",
        (entity_id,)
    ).fetchall()
    conn.close()
    return rows

def set_entry_tags(entity_type: str, entity_id: int, tag_ids: list):
    table = "account_tags" if entity_type == "account" else "contract_tags"
    id_col = "account_id" if entity_type == "account" else "contract_id"
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f"DELETE FROM {table} WHERE {id_col}=?", (entity_id,))
    for tid in tag_ids:
        conn.execute(f"INSERT OR IGNORE INTO {table} ({id_col}, tag_id) VALUES (?,?)",
                     (entity_id, tid))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def format_amount(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return ""


def parse_amount(text: str):
    text = text.strip().replace("€", "").replace(" ", "").replace(".", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_size(size) -> str:
    if size is None:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1_048_576:.1f} MB"


def open_file(path: Path):
    if not path.exists():
        messagebox.showerror("Fehler", f"Datei nicht gefunden:\n{path}")
        return
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


def extract_text_from_file(path: Path) -> tuple[str, str]:
    """Returns (extracted_text, error_message). error_message is "" on success."""
    if not path.exists():
        return "", f"Datei nicht gefunden: {path.name}"
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            try:
                import pdfplumber
            except ImportError:
                return "", "pdfplumber nicht installiert (pip install pdfplumber)"
            with pdfplumber.open(path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            if not text.strip():
                return "", "PDF enthält keinen extrahierbaren Text (evtl. nur Bilder)"
            return text, ""
        elif suffix == ".docx":
            try:
                from docx import Document as DocxDoc
            except ImportError:
                return "", "python-docx nicht installiert (pip install python-docx)"
            text = "\n".join(p.text for p in DocxDoc(path).paragraphs)
            return text, ""
        elif suffix in (".xlsx", ".xls"):
            try:
                import openpyxl
            except ImportError:
                return "", "openpyxl nicht installiert (pip install openpyxl)"
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if cell.value is not None:
                            parts.append(str(cell.value))
            return " ".join(parts), ""
        elif suffix in (".txt", ".csv", ".md", ".json", ".xml", ".html", ".htm"):
            return path.read_text(encoding="utf-8", errors="ignore"), ""
        else:
            return "", f"Format {suffix} wird nicht unterstützt"
    except Exception as e:
        return "", str(e)


# ---------------------------------------------------------------------------
# PDF-Export Bankkonten
# ---------------------------------------------------------------------------
def export_accounts_pdf(filepath: str, accounts: list, show_passwords: bool):
    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2.5*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("t", parent=styles["Heading1"], fontSize=16,
                             spaceAfter=4, alignment=TA_CENTER,
                             textColor=colors.HexColor("#1a3c5e"))
    sub_s   = ParagraphStyle("s", parent=styles["Normal"], fontSize=9,
                             spaceAfter=14, alignment=TA_CENTER,
                             textColor=colors.grey)
    cell_s  = ParagraphStyle("c", parent=styles["Normal"], fontSize=8, leading=11)

    elements = [
        Paragraph("Bank Account Manager – Bankkonten", title_s),
        Paragraph(f"Erstellt am {datetime.now().strftime('%d.%m.%Y  %H:%M')} Uhr  |  "
                  f"{len(accounts)} Konto/Konten", sub_s),
    ]
    headers   = ["Bank", "Kontonummer", "Login-URL", "Benutzername",
                 "Passwort", "Kontostand", "Stand-Datum"]
    col_widths = [4.0*cm, 3.5*cm, 5.2*cm, 4.0*cm, 3.5*cm, 2.8*cm, 2.7*cm]
    data = [headers]
    for row in accounts:
        _, bank_name, account_number, login_url, username, pw_enc, balance, balance_date, _ = row
        pw = decrypt(pw_enc) if show_passwords and pw_enc else ("●"*8 if pw_enc else "")
        bal = (f"{balance:,.2f} €".replace(",","X").replace(".",",").replace("X",".")
               if balance is not None else "")
        data.append([Paragraph(v or "", cell_s) for v in
                     [bank_name, account_number, login_url, username, pw, bal, balance_date]])
    _build_pdf(doc, elements, data, col_widths, show_passwords)


# ---------------------------------------------------------------------------
# PDF-Export Verträge
# ---------------------------------------------------------------------------
def export_contracts_pdf(filepath: str, contracts: list, show_passwords: bool):
    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2.5*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("t", parent=styles["Heading1"], fontSize=16,
                             spaceAfter=4, alignment=TA_CENTER,
                             textColor=colors.HexColor("#1a3c5e"))
    sub_s   = ParagraphStyle("s", parent=styles["Normal"], fontSize=9,
                             spaceAfter=14, alignment=TA_CENTER,
                             textColor=colors.grey)
    cell_s  = ParagraphStyle("c", parent=styles["Normal"], fontSize=8, leading=11)

    elements = [
        Paragraph("Bank Account Manager – Verträge & Versicherungen", title_s),
        Paragraph(f"Erstellt am {datetime.now().strftime('%d.%m.%Y  %H:%M')} Uhr  |  "
                  f"{len(contracts)} Einträge", sub_s),
    ]
    headers   = ["Kategorie", "Bezeichnung", "Anbieter", "Vertragsnr.",
                 "Betrag", "Rhythmus", "Beginn", "Ende", "Kündigung"]
    col_widths = [2.8*cm, 4.0*cm, 3.5*cm, 3.0*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.4*cm]
    data = [headers]
    for row in contracts:
        _, category, name, provider, contract_number, _, _, _, amount, interval, \
            start_date, end_date, notice_period, _ = row
        amt = (f"{amount:,.2f} €".replace(",","X").replace(".",",").replace("X",".")
               if amount is not None else "")
        data.append([Paragraph(v or "", cell_s) for v in
                     [category, name, provider, contract_number,
                      amt, interval, start_date, end_date, notice_period]])
    _build_pdf(doc, elements, data, col_widths, show_passwords)


def _build_pdf(doc, elements, data, col_widths, show_passwords):
    styles = getSampleStyleSheet()
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR",     (0,0),(-1,0), colors.white),
        ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,0), 9),
        ("TOPPADDING",    (0,0),(-1,0), 7),
        ("BOTTOMPADDING", (0,0),(-1,0), 7),
        ("GRID",          (0,0),(-1,-1), 0.4, colors.HexColor("#aabbcc")),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.white, colors.HexColor("#eef3f8")]),
        ("FONTSIZE",      (0,1),(-1,-1), 8),
    ]))
    elements.append(t)
    if not show_passwords:
        elements.append(Spacer(1, 0.5*cm))
        elements.append(Paragraph(
            "Passwörter wurden aus Sicherheitsgründen nicht im Klartext exportiert.",
            ParagraphStyle("h", parent=styles["Normal"], fontSize=7, textColor=colors.grey)
        ))
    doc.build(elements)


# ---------------------------------------------------------------------------
# Tag-Selector widget
# ---------------------------------------------------------------------------
class TagSelector(ttk.Frame):
    """Combobox + chip display for selecting multiple tags."""
    def __init__(self, parent, all_tags: list, preselected_ids: list):
        super().__init__(parent)
        # all_tags: list of (id, name, color)
        self._all_tags_map: dict[int, str] = {tid: tname for tid, tname, _ in all_tags}
        self._selected: dict[int, str] = {}
        for tid in preselected_ids:
            if tid in self._all_tags_map:
                self._selected[tid] = self._all_tags_map[tid]

        cb_row = ttk.Frame(self)
        cb_row.pack(fill=tk.X)
        self._combo_var = tk.StringVar()
        self._combo = ttk.Combobox(cb_row, textvariable=self._combo_var,
                                   width=22, state="readonly")
        self._combo.pack(side=tk.LEFT)
        ttk.Button(cb_row, text="Hinzufügen", width=12,
                   command=self._add).pack(side=tk.LEFT, padx=4)
        self._chips = ttk.Frame(self)
        self._chips.pack(fill=tk.X, pady=(4, 0))
        self._refresh()

    def _refresh(self):
        available = [tname for tid, tname in self._all_tags_map.items()
                     if tid not in self._selected]
        self._combo["values"] = available
        self._combo_var.set("")
        for w in self._chips.winfo_children():
            w.destroy()
        for tid, tname in self._selected.items():
            chip = ttk.Frame(self._chips, relief="solid", padding=(3, 1))
            chip.pack(side=tk.LEFT, padx=2, pady=2)
            ttk.Label(chip, text=tname).pack(side=tk.LEFT)
            ttk.Button(chip, text="×", width=2,
                       command=lambda t=tid: self._remove(t)).pack(side=tk.LEFT)

    def _add(self):
        tname = self._combo_var.get().strip()
        if not tname:
            return
        for tid, tn in self._all_tags_map.items():
            if tn == tname and tid not in self._selected:
                self._selected[tid] = tn
                self._refresh()
                break

    def _remove(self, tid: int):
        self._selected.pop(tid, None)
        self._refresh()

    def get_selected_ids(self) -> list:
        return list(self._selected.keys())


# ---------------------------------------------------------------------------
# Dialog-Basisklasse
# ---------------------------------------------------------------------------
class BaseDialog(tk.Toplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.result = None

    def _center(self, parent):
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _add_field(self, frame, row, label, key, is_pw=False, width=34):
        pad = {"padx": 10, "pady": 3}
        ttk.Label(frame, text=label, width=28, anchor="w").grid(
            row=row, column=0, sticky="w", **pad)
        var = tk.StringVar(value=self._data.get(key, ""))
        self._vars[key] = var
        e = ttk.Entry(frame, textvariable=var, width=width,
                      show="●" if is_pw else "")
        e.grid(row=row, column=1, sticky="ew", **pad)
        return e

    def _add_combo(self, frame, row, label, key, values, width=34):
        pad = {"padx": 10, "pady": 3}
        ttk.Label(frame, text=label, width=28, anchor="w").grid(
            row=row, column=0, sticky="w", **pad)
        var = tk.StringVar(value=self._data.get(key, ""))
        self._vars[key] = var
        cb = ttk.Combobox(frame, textvariable=var, values=values, width=width-2, state="normal")
        cb.grid(row=row, column=1, sticky="ew", **pad)
        return cb


# ---------------------------------------------------------------------------
# Dialog: Bankkonto
# ---------------------------------------------------------------------------
class AccountDialog(BaseDialog):
    def __init__(self, parent, title: str, data: dict = None):
        super().__init__(parent, title)
        self._data = data or {}
        self._vars = {}
        self._build_ui()
        self._center(parent)

    def _build_ui(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        first = self._add_field(frame, 0, "Bankname *",               "bank_name")
        self._add_field(frame, 1, "Kontonummer",                  "account_number")
        self._add_field(frame, 2, "Login-URL",                    "login_url")
        self._add_field(frame, 3, "Benutzername",                 "username")
        self._add_field(frame, 4, "Passwort",                     "password", is_pw=True)
        self._add_field(frame, 5, "Kontostand (€)",               "balance")
        self._add_field(frame, 6, "Stand-Datum (TT.MM.JJJJ)",    "balance_date")
        ttk.Label(frame, text="Notizen", anchor="w").grid(row=7, column=0, sticky="nw", padx=10, pady=3)
        self._notes = tk.Text(frame, width=34, height=3, font=("Segoe UI", 9))
        self._notes.grid(row=7, column=1, sticky="ew", padx=10, pady=3)
        self._notes.insert("1.0", self._data.get("notes", ""))
        # Tags
        ttk.Label(frame, text="Tags", anchor="w").grid(row=8, column=0, sticky="nw", padx=10, pady=3)
        self._tag_selector = TagSelector(frame, get_all_tags(), self._data.get("tag_ids", []))
        self._tag_selector.grid(row=8, column=1, sticky="ew", padx=10, pady=3)
        btn = ttk.Frame(frame)
        btn.grid(row=9, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn, text="Speichern",  command=self._save,   width=14).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Abbrechen",  command=self.destroy, width=14).pack(side=tk.LEFT, padx=6)
        first.focus()

    def _save(self):
        bank_name = self._vars["bank_name"].get().strip()
        if not bank_name:
            messagebox.showwarning("Pflichtfeld", "Bitte Banknamen eingeben.", parent=self)
            return
        bal_text = self._vars["balance"].get().strip()
        balance  = parse_amount(bal_text) if bal_text else None
        if bal_text and balance is None:
            messagebox.showwarning("Ungültig", "Ungültiger Kontostand.", parent=self)
            return
        self.result = {
            "bank_name":      bank_name,
            "account_number": self._vars["account_number"].get().strip(),
            "login_url":      self._vars["login_url"].get().strip(),
            "username":       self._vars["username"].get().strip(),
            "password":       self._vars["password"].get(),
            "balance":        balance,
            "balance_date":   self._vars["balance_date"].get().strip(),
            "notes":          self._notes.get("1.0", "end-1c").strip(),
            "tag_ids":        self._tag_selector.get_selected_ids(),
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Dialog: Vertrag / Versicherung
# ---------------------------------------------------------------------------
CATEGORIES   = ["Versicherung", "Vertrag", "Abonnement", "Mobilfunk",
                 "Internet", "Strom/Gas", "Sonstiges"]
INTERVALS    = ["monatlich", "vierteljährlich", "halbjährlich", "jährlich", "einmalig"]


class ContractDialog(BaseDialog):
    def __init__(self, parent, title: str, data: dict = None):
        super().__init__(parent, title)
        self._data = data or {}
        self._vars = {}
        self._build_ui()
        self._center(parent)

    def _build_ui(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        self._add_combo(frame, 0, "Kategorie",                  "category",      CATEGORIES)
        first = self._add_field(frame, 1, "Bezeichnung *",      "name")
        self._add_field(frame, 2, "Anbieter",                   "provider")
        self._add_field(frame, 3, "Vertragsnummer",             "contract_number")
        self._add_field(frame, 4, "Login-URL",                  "login_url")
        self._add_field(frame, 5, "Benutzername",               "username")
        self._add_field(frame, 6, "Passwort",                   "password",      is_pw=True)
        self._add_field(frame, 7, "Betrag (€)",                 "amount")
        self._add_combo(frame, 8, "Zahlungsrhythmus",           "interval",      INTERVALS)
        self._add_field(frame, 9, "Vertragsbeginn (TT.MM.JJJJ)","start_date")
        self._add_field(frame,10, "Vertragsende  (TT.MM.JJJJ)", "end_date")
        self._add_field(frame,11, "Kündigungsfrist",            "notice_period")
        ttk.Label(frame, text="Notizen", anchor="w").grid(row=12, column=0, sticky="nw", padx=10, pady=3)
        self._notes = tk.Text(frame, width=34, height=3, font=("Segoe UI", 9))
        self._notes.grid(row=12, column=1, sticky="ew", padx=10, pady=3)
        self._notes.insert("1.0", self._data.get("notes", ""))
        # Tags
        ttk.Label(frame, text="Tags", anchor="w").grid(row=13, column=0, sticky="nw", padx=10, pady=3)
        self._tag_selector = TagSelector(frame, get_all_tags(), self._data.get("tag_ids", []))
        self._tag_selector.grid(row=13, column=1, sticky="ew", padx=10, pady=3)
        btn = ttk.Frame(frame)
        btn.grid(row=14, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn, text="Speichern",  command=self._save,   width=14).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Abbrechen",  command=self.destroy, width=14).pack(side=tk.LEFT, padx=6)
        first.focus()

    def _save(self):
        name = self._vars["name"].get().strip()
        if not name:
            messagebox.showwarning("Pflichtfeld", "Bitte Bezeichnung eingeben.", parent=self)
            return
        amt_text = self._vars["amount"].get().strip()
        amount   = parse_amount(amt_text) if amt_text else None
        if amt_text and amount is None:
            messagebox.showwarning("Ungültig", "Ungültiger Betrag.", parent=self)
            return
        self.result = {
            "category":       self._vars["category"].get().strip(),
            "name":           name,
            "provider":       self._vars["provider"].get().strip(),
            "contract_number":self._vars["contract_number"].get().strip(),
            "login_url":      self._vars["login_url"].get().strip(),
            "username":       self._vars["username"].get().strip(),
            "password":       self._vars["password"].get(),
            "amount":         amount,
            "interval":       self._vars["interval"].get().strip(),
            "start_date":     self._vars["start_date"].get().strip(),
            "end_date":       self._vars["end_date"].get().strip(),
            "notice_period":  self._vars["notice_period"].get().strip(),
            "notes":          self._notes.get("1.0", "end-1c").strip(),
            "tag_ids":        self._tag_selector.get_selected_ids(),
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Profil-Auswahl-Dialog
# ---------------------------------------------------------------------------
class ProfileSelectionDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Bank Account Manager – Profil auswählen")
        self.resizable(False, False)
        self.grab_set()
        self.selected_profile = None
        self._profiles: list = []
        self._build_ui()
        self._load()
        self.update_idletasks()
        w, h = 400, 340
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        ttk.Label(self, text="Benutzerprofil auswählen",
                  font=("Segoe UI", 12, "bold"), padding=(16, 12, 16, 4)).pack()
        ttk.Label(self, text="Doppelklick oder 'Öffnen' zum Starten.",
                  foreground="#666", padding=(16, 0, 16, 8)).pack()
        lf = ttk.Frame(self, padding=(16, 0))
        lf.pack(fill=tk.BOTH, expand=True)
        self._lb = tk.Listbox(lf, font=("Segoe UI", 11), selectmode="single",
                              height=8, relief="solid", bd=1)
        self._lb.pack(fill=tk.BOTH, expand=True)
        self._lb.bind("<Double-1>", lambda _: self._open())
        btn = ttk.Frame(self, padding=(16, 10))
        btn.pack(fill=tk.X)
        ttk.Button(btn, text="Öffnen",     command=self._open,   width=11).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn, text="Neu",        command=self._new,    width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn, text="Umbenennen", command=self._rename, width=11).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn, text="Löschen",    command=self._delete, width=9).pack(side=tk.LEFT, padx=2)

    def _load(self):
        self._lb.delete(0, tk.END)
        self._profiles = get_profiles()
        for p in self._profiles:
            lu = p.get("last_used", "")
            label = p["name"] + (f"  (zuletzt: {lu[:10]})" if lu else "")
            self._lb.insert(tk.END, label)
        if self._profiles:
            self._lb.selection_set(0)

    def _sel_idx(self):
        s = self._lb.curselection()
        return s[0] if s else None

    def _sel_name(self):
        idx = self._sel_idx()
        return self._profiles[idx]["name"] if idx is not None else None

    def _open(self):
        name = self._sel_name()
        if not name:
            messagebox.showwarning("Hinweis", "Bitte ein Profil auswählen.", parent=self)
            return
        self.selected_profile = name
        self.destroy()

    def _new(self):
        name = simpledialog.askstring("Neues Profil", "Profilname:", parent=self)
        if not name or not name.strip():
            return
        try:
            create_profile(name.strip())
            self._load()
        except ValueError as e:
            messagebox.showerror("Fehler", str(e), parent=self)

    def _rename(self):
        old = self._sel_name()
        if not old:
            return
        new = simpledialog.askstring("Umbenennen", f"Neuer Name für '{old}':",
                                     initialvalue=old, parent=self)
        if not new or not new.strip() or new.strip() == old:
            return
        rename_profile(old, new.strip())
        self._load()

    def _delete(self):
        name = self._sel_name()
        if not name:
            return
        if len(self._profiles) <= 1:
            messagebox.showwarning("Hinweis", "Mindestens ein Profil muss vorhanden sein.",
                                   parent=self)
            return
        if messagebox.askyesno("Löschen",
                f"Profil '{name}' und alle zugehörigen Daten wirklich löschen?",
                icon="warning", parent=self):
            delete_profile(name)
            self._load()

    def _on_close(self):
        if messagebox.askyesno("Beenden", "Anwendung beenden?", parent=self):
            self.selected_profile = None
            self.destroy()


# ---------------------------------------------------------------------------
# Dialog: optionale Beschreibung beim Datei-Upload
# ---------------------------------------------------------------------------
class _DescriptionDialog(tk.Toplevel):
    def __init__(self, parent, filename: str):
        super().__init__(parent)
        self.title("Beschreibung")
        self.resizable(False, False)
        self.grab_set()
        self.result = ""
        ttk.Label(self, text=f"Beschreibung (optional):\n{filename}",
                  padding=(12, 8, 12, 4), justify="left").pack()
        self._var = tk.StringVar()
        e = ttk.Entry(self, textvariable=self._var, width=36)
        e.pack(padx=12, pady=4)
        e.focus()
        e.bind("<Return>", lambda _: self._ok())
        btn = ttk.Frame(self, padding=(12, 6))
        btn.pack()
        ttk.Button(btn, text="OK",           command=self._ok,     width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="Überspringen", command=self.destroy, width=12).pack(side=tk.LEFT, padx=4)
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _ok(self):
        self.result = self._var.get().strip()
        self.destroy()


# ---------------------------------------------------------------------------
# DocumentsPanel
# ---------------------------------------------------------------------------
class DocumentsPanel(ttk.LabelFrame):
    def __init__(self, parent, entity_type: str):
        super().__init__(parent, text=" Dokumente ", padding=(6, 4))
        self._entity_type = entity_type
        self._entity_id   = None
        self._docs: list  = []
        self._build_ui()

    def _build_ui(self):
        tb = tk.Frame(self, bg="#f0f4f8")
        tb.pack(fill=tk.X, pady=(0, 4))
        mkbtn = lambda text, cmd: tk.Button(
            tb, text=text, command=cmd,
            bg="#f0f4f8", fg="#1a3c5e", activebackground="#d0dce8",
            font=("Segoe UI", 9, "bold"), relief="flat", padx=8, pady=3, cursor="hand2")
        self._btn_add  = mkbtn("＋ Hinzufügen",   self._add)
        self._btn_open = mkbtn("↗ Öffnen",        self._open)
        self._btn_save = mkbtn("⬇ Speichern als", self._save_as)
        self._btn_del  = mkbtn("✕ Entfernen",     self._remove)
        for b in (self._btn_add, self._btn_open, self._btn_save, self._btn_del):
            b.pack(side=tk.LEFT, padx=(0, 3))
        self._lbl = tk.Label(tb, text="(kein Eintrag ausgewählt)",
                             fg="#888", font=("Segoe UI", 8, "italic"), bg="#f0f4f8")
        self._lbl.pack(side=tk.LEFT, padx=10)

        cols = ("original_name", "description", "file_size", "created_at")
        self._tree = ttk.Treeview(self, columns=cols, show="headings",
                                  selectmode="browse", height=4)
        self._tree.heading("original_name", text="Dateiname")
        self._tree.heading("description",   text="Beschreibung")
        self._tree.heading("file_size",     text="Größe")
        self._tree.heading("created_at",    text="Hinzugefügt")
        self._tree.column("original_name", width=220, minwidth=120)
        self._tree.column("description",   width=200, minwidth=80)
        self._tree.column("file_size",     width=70,  minwidth=50, anchor="e")
        self._tree.column("created_at",    width=130, minwidth=100)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", lambda _: self._open())
        self._set_state("disabled")

    def set_entity(self, entity_id, label: str = ""):
        self._entity_id = entity_id
        if entity_id is None:
            self._lbl.config(text="(kein Eintrag ausgewählt)")
            self._set_state("disabled")
            self._tree.delete(*self._tree.get_children())
            return
        self._lbl.config(text=f"→  {label}")
        self._set_state("normal")
        self._refresh()

    def _refresh(self):
        self._tree.delete(*self._tree.get_children())
        if self._entity_id is None:
            return
        self._docs = get_documents(self._entity_type, self._entity_id)
        for d in self._docs:
            did, orig, stored, fsize, desc, created = d
            self._tree.insert("", "end", iid=str(did),
                              values=(orig, desc or "", format_size(fsize), created))

    def _set_state(self, state: str):
        for b in (self._btn_add, self._btn_open, self._btn_save, self._btn_del):
            b.config(state=state)

    def _sel_id(self):
        s = self._tree.selection()
        return int(s[0]) if s else None

    def _doc_row(self, doc_id):
        return next((d for d in self._docs if d[0] == doc_id), None)

    def _add(self):
        if self._entity_id is None:
            return
        paths = filedialog.askopenfilenames(
            title="Dokument(e) hinzufügen",
            filetypes=[
                ("Alle Dateien", "*.*"),
                ("PDF",          "*.pdf"),
                ("Bilder",       "*.png *.jpg *.jpeg *.tif *.tiff"),
                ("Word",         "*.docx *.doc"),
                ("Excel",        "*.xlsx *.xls"),
            ]
        )
        if not paths:
            return
        desc = ""
        if len(paths) == 1:
            dlg = _DescriptionDialog(self.winfo_toplevel(), Path(paths[0]).name)
            self.wait_window(dlg)
            desc = dlg.result or ""
        for p in paths:
            add_document(self._entity_type, self._entity_id, p, desc)
        self._refresh()

    def _open(self):
        did = self._sel_id()
        if did is None:
            messagebox.showinfo("Hinweis", "Bitte eine Datei auswählen.")
            return
        row = self._doc_row(did)
        if row:
            open_file(DOCS_DIR / row[2])

    def _save_as(self):
        did = self._sel_id()
        if did is None:
            messagebox.showinfo("Hinweis", "Bitte eine Datei auswählen.")
            return
        row = self._doc_row(did)
        if not row:
            return
        dest = filedialog.asksaveasfilename(
            title="Datei exportieren",
            defaultextension=Path(row[1]).suffix,
            initialfile=row[1],
            filetypes=[("Alle Dateien", "*.*")]
        )
        if dest:
            shutil.copy2(DOCS_DIR / row[2], dest)
            messagebox.showinfo("Gespeichert", f"Datei gespeichert:\n{dest}")

    def _remove(self):
        did = self._sel_id()
        if did is None:
            messagebox.showinfo("Hinweis", "Bitte eine Datei auswählen.")
            return
        row = self._doc_row(did)
        if row and messagebox.askyesno("Entfernen",
                f'Dokument „{row[1]}" wirklich entfernen?\nDie Datei wird dauerhaft gelöscht.',
                icon="warning"):
            delete_document(did)
            self._refresh()


# ---------------------------------------------------------------------------
# Gemeinsame Farben
# ---------------------------------------------------------------------------
TB_BG      = "#1a3c5e"
BTN_BG     = "#f0f4f8"
BTN_FG     = "#1a3c5e"
BTN_ACTIVE = "#d0dce8"


def toolbar_btn(parent, text, command):
    return tk.Button(parent, text=text, command=command,
                     bg=BTN_BG, fg=BTN_FG,
                     activebackground=BTN_ACTIVE, activeforeground=BTN_FG,
                     font=("Segoe UI", 9, "bold"), relief="flat", bd=0,
                     padx=12, pady=5, cursor="hand2")


# ---------------------------------------------------------------------------
# Tab: Bankkonten
# ---------------------------------------------------------------------------
class AccountsTab(ttk.Frame):
    COLUMNS    = ("bank_name","account_number","login_url","username","balance","balance_date","tags","notes")
    COL_LABELS = {"bank_name":"Bank","account_number":"Kontonummer","login_url":"Login-URL",
                  "username":"Benutzername","balance":"Kontostand","balance_date":"Stand-Datum",
                  "tags":"Tags","notes":"Notizen"}
    COL_WIDTHS = {"bank_name":150,"account_number":120,"login_url":190,
                  "username":130,"balance":100,"balance_date":90,"tags":140,"notes":180}
    DB_IDX     = {"bank_name":1,"account_number":2,"login_url":3,
                  "username":4,"balance":6,"balance_date":7}

    def __init__(self, parent):
        super().__init__(parent)
        self._rows: list = []
        self._sort_col, self._sort_asc = "bank_name", True
        self._build_ui()
        self.load()

    def _build_ui(self):
        # Toolbar
        tb = tk.Frame(self, bg=TB_BG, height=40)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)
        toolbar_btn(tb, "＋  Neu",        self._add).pack(side=tk.LEFT, padx=(8,2), pady=5)
        toolbar_btn(tb, "✎  Bearbeiten",  self._edit).pack(side=tk.LEFT, padx=2, pady=5)
        toolbar_btn(tb, "✕  Löschen",     self._delete).pack(side=tk.LEFT, padx=2, pady=5)
        tk.Frame(tb, bg="#3a6a94", width=1).pack(side=tk.LEFT, fill=tk.Y, pady=6, padx=8)
        toolbar_btn(tb, "PDF exportieren", self._export_pdf).pack(side=tk.LEFT, padx=2, pady=5)

        # Suche
        sf = ttk.Frame(self, padding=(8,5,8,0))
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="Suche:").pack(side=tk.LEFT)
        self._search = tk.StringVar()
        self._search.trace_add("write", lambda *_: self._filter())
        ttk.Entry(sf, textvariable=self._search, width=28).pack(side=tk.LEFT, padx=6)
        ttk.Button(sf, text="✕", width=3, command=lambda: self._search.set("")).pack(side=tk.LEFT)
        tk.Frame(sf, width=1, bg="#ccc").pack(side=tk.LEFT, fill=tk.Y, pady=2, padx=8)
        ttk.Label(sf, text="Tag:").pack(side=tk.LEFT)
        self._tag_filter = tk.StringVar(value="(Alle)")
        self._tag_cb = ttk.Combobox(sf, textvariable=self._tag_filter, width=16,
                                    state="readonly")
        self._tag_cb.pack(side=tk.LEFT, padx=4)
        self._tag_cb.bind("<<ComboboxSelected>>", lambda _: self._filter())

        self._status = tk.StringVar()
        ttk.Label(self, textvariable=self._status, anchor="w",
                  padding=(10, 3)).pack(fill=tk.X, side=tk.BOTTOM)

        # PanedWindow: Eintrags-Tabelle oben, Dokumente unten
        pw = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0))

        tf = ttk.Frame(pw)
        vsb = ttk.Scrollbar(tf, orient="vertical")
        hsb = ttk.Scrollbar(tf, orient="horizontal")
        self._tree = ttk.Treeview(tf, columns=self.COLUMNS, show="headings",
                                  selectmode="extended",
                                  yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)
        for c in self.COLUMNS:
            self._tree.heading(c, text=self.COL_LABELS[c], command=lambda x=c: self._sort(x))
            self._tree.column(c, width=self.COL_WIDTHS[c], minwidth=50, stretch=False)
        vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>",         lambda _: self._edit())
        self._tree.bind("<Delete>",           lambda _: self._delete())
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        pw.add(tf, weight=3)

        self._docs_panel = DocumentsPanel(pw, entity_type="account")
        pw.add(self._docs_panel, weight=1)

    def load(self):
        self._rows = get_all_accounts()
        # Tag-Combobox aktualisieren
        all_tags = get_all_tags()
        self._tag_cb["values"] = ["(Alle)"] + [t[1] for t in all_tags]
        self._all_tags_list = all_tags  # [(id, name, color), ...]
        self._filter()

    def _filter(self):
        q      = self._search.get().lower()
        sel_tag = self._tag_filter.get()
        # Lade Tag-Zuordnungen für alle sichtbaren Rows
        conn = sqlite3.connect(DB_PATH)
        tag_map = {}
        for row_data in conn.execute(
            "SELECT at.account_id, t.name FROM account_tags at JOIN tags t ON t.id=at.tag_id"
        ).fetchall():
            tag_map.setdefault(row_data[0], []).append(row_data[1])
        conn.close()

        shown = self._rows
        if q:
            shown = [r for r in shown if any(q in str(v).lower() for v in r[1:])]
        if sel_tag != "(Alle)":
            shown = [r for r in shown if sel_tag in tag_map.get(r[0], [])]

        self._tree.delete(*self._tree.get_children())
        for r in shown:
            _, bn, an, lu, un, _, bal, bd, notes = r
            tags_str = ", ".join(tag_map.get(r[0], []))
            self._tree.insert("", "end", iid=str(r[0]),
                              values=(bn, an, lu, un, format_amount(bal), bd, tags_str, notes or ""))
        n, tot = len(shown), len(self._rows)
        self._status.set(f"{n} Einträge" + (f"  (von {tot})" if n != tot else ""))
        self._docs_panel.set_entity(None)

    def _on_select(self, _event):
        rid = self._sel_id()
        if rid is None:
            self._docs_panel.set_entity(None)
            return
        r = self._row(rid)
        self._docs_panel.set_entity(rid, r[1] if r else "")

    def _sort(self, col):
        if col not in self.DB_IDX:
            return
        self._sort_asc = not self._sort_asc if self._sort_col == col else True
        self._sort_col = col
        idx = self.DB_IDX[col]
        self._rows.sort(key=lambda r: (r[idx] is None, r[idx] or ""), reverse=not self._sort_asc)
        self._filter()

    def _sel_id(self):
        s = self._tree.selection()
        return int(s[0]) if s else None

    def _row(self, rid):
        return next((r for r in self._rows if r[0] == rid), None)

    def _add(self):
        dlg = AccountDialog(self.winfo_toplevel(), "Neues Bankkonto anlegen")
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            new_id = insert_account(d["bank_name"], d["account_number"], d["login_url"],
                                    d["username"], d["password"], d["balance"],
                                    d["balance_date"], d["notes"])
            set_entry_tags("account", new_id, d.get("tag_ids", []))
            self.load()

    def _edit(self):
        rid = self._sel_id()
        if rid is None:
            messagebox.showinfo("Hinweis", "Bitte einen Eintrag auswählen.")
            return
        r = self._row(rid)
        _, bn, an, lu, un, pw_enc, bal, bd, notes = r
        dlg = AccountDialog(self.winfo_toplevel(), f"Bankkonto bearbeiten – {bn}", {
            "bank_name": bn or "", "account_number": an or "",
            "login_url": lu or "", "username": un or "",
            "password":  decrypt(pw_enc) if pw_enc else "",
            "balance":   format_amount(bal), "balance_date": bd or "", "notes": notes or "",
            "tag_ids":   [t[0] for t in get_entry_tags("account", rid)],
        })
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            update_account(rid, d["bank_name"], d["account_number"], d["login_url"],
                           d["username"], d["password"], d["balance"],
                           d["balance_date"], d["notes"])
            set_entry_tags("account", rid, d.get("tag_ids", []))
            self.load()

    def _delete(self):
        rid = self._sel_id()
        if rid is None:
            messagebox.showinfo("Hinweis", "Bitte einen Eintrag auswählen.")
            return
        r = self._row(rid)
        if messagebox.askyesno("Löschen", f'Konto „{r[1]}" wirklich löschen?', icon="warning"):
            delete_account(rid)
            self.load()

    def _export_pdf(self):
        sel = self._tree.selection()
        if sel:
            export_rows = [r for r in self._rows if str(r[0]) in sel]
            label = f"{len(export_rows)} ausgewählte Einträge"
        else:
            export_rows = self._rows
            label = "alle Einträge"
        if not export_rows:
            messagebox.showinfo("Keine Daten", "Keine Bankkonten vorhanden.")
            return
        show_pw = messagebox.askyesno("PDF-Export",
            f"PDF für {label} erstellen?\nPasswörter im Klartext exportieren?",
            icon="warning")
        fp = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"Bankkonten_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            title="PDF speichern …")
        if not fp:
            return
        try:
            export_accounts_pdf(fp, export_rows, show_pw)
            if messagebox.askyesno("Gespeichert", f"PDF gespeichert:\n{fp}\n\nJetzt öffnen?"):
                os.startfile(fp)
        except Exception as e:
            messagebox.showerror("Fehler", str(e))


# ---------------------------------------------------------------------------
# Tab: Verträge & Versicherungen
# ---------------------------------------------------------------------------
class ContractsTab(ttk.Frame):
    COLUMNS    = ("category","name","provider","contract_number","amount","interval",
                  "start_date","end_date","notice_period","tags","notes")
    COL_LABELS = {"category":"Kategorie","name":"Bezeichnung","provider":"Anbieter",
                  "contract_number":"Vertragsnr.","amount":"Betrag","interval":"Rhythmus",
                  "start_date":"Beginn","end_date":"Ende","notice_period":"Kündigung",
                  "tags":"Tags","notes":"Notizen"}
    COL_WIDTHS = {"category":100,"name":160,"provider":130,"contract_number":100,
                  "amount":90,"interval":90,"start_date":90,"end_date":90,"notice_period":90,
                  "tags":140,"notes":180}
    DB_IDX     = {"category":1,"name":2,"provider":3,"contract_number":4,
                  "amount":8,"interval":9,"start_date":10,"end_date":11,"notice_period":12}

    def __init__(self, parent):
        super().__init__(parent)
        self._rows: list = []
        self._sort_col, self._sort_asc = "category", True
        self._build_ui()
        self.load()

    def _build_ui(self):
        tb = tk.Frame(self, bg=TB_BG, height=40)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)
        toolbar_btn(tb, "＋  Neu",        self._add).pack(side=tk.LEFT, padx=(8,2), pady=5)
        toolbar_btn(tb, "✎  Bearbeiten",  self._edit).pack(side=tk.LEFT, padx=2, pady=5)
        toolbar_btn(tb, "✕  Löschen",     self._delete).pack(side=tk.LEFT, padx=2, pady=5)
        tk.Frame(tb, bg="#3a6a94", width=1).pack(side=tk.LEFT, fill=tk.Y, pady=6, padx=8)
        toolbar_btn(tb, "PDF exportieren", self._export_pdf).pack(side=tk.LEFT, padx=2, pady=5)

        sf = ttk.Frame(self, padding=(8,5,8,0))
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="Suche:").pack(side=tk.LEFT)
        self._search = tk.StringVar()
        self._search.trace_add("write", lambda *_: self._filter())
        ttk.Entry(sf, textvariable=self._search, width=28).pack(side=tk.LEFT, padx=6)
        ttk.Button(sf, text="✕", width=3, command=lambda: self._search.set("")).pack(side=tk.LEFT)
        tk.Frame(sf, width=1, bg="#ccc").pack(side=tk.LEFT, fill=tk.Y, pady=2, padx=8)
        ttk.Label(sf, text="Tag:").pack(side=tk.LEFT)
        self._tag_filter = tk.StringVar(value="(Alle)")
        self._tag_cb = ttk.Combobox(sf, textvariable=self._tag_filter, width=16,
                                    state="readonly")
        self._tag_cb.pack(side=tk.LEFT, padx=4)
        self._tag_cb.bind("<<ComboboxSelected>>", lambda _: self._filter())

        self._status = tk.StringVar()
        ttk.Label(self, textvariable=self._status, anchor="w",
                  padding=(10, 3)).pack(fill=tk.X, side=tk.BOTTOM)

        pw = ttk.PanedWindow(self, orient=tk.VERTICAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0))

        tf = ttk.Frame(pw)
        vsb = ttk.Scrollbar(tf, orient="vertical")
        hsb = ttk.Scrollbar(tf, orient="horizontal")
        self._tree = ttk.Treeview(tf, columns=self.COLUMNS, show="headings",
                                  selectmode="extended",
                                  yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)
        for c in self.COLUMNS:
            self._tree.heading(c, text=self.COL_LABELS[c], command=lambda x=c: self._sort(x))
            self._tree.column(c, width=self.COL_WIDTHS[c], minwidth=50, stretch=False)
        vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>",         lambda _: self._edit())
        self._tree.bind("<Delete>",           lambda _: self._delete())
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        pw.add(tf, weight=3)

        self._docs_panel = DocumentsPanel(pw, entity_type="contract")
        pw.add(self._docs_panel, weight=1)

    def load(self):
        self._rows = get_all_contracts()
        # Tag-Combobox aktualisieren
        all_tags = get_all_tags()
        self._tag_cb["values"] = ["(Alle)"] + [t[1] for t in all_tags]
        self._all_tags_list = all_tags  # [(id, name, color), ...]
        self._filter()

    def _filter(self):
        q      = self._search.get().lower()
        sel_tag = self._tag_filter.get()
        # Lade Tag-Zuordnungen für alle sichtbaren Rows
        conn = sqlite3.connect(DB_PATH)
        tag_map = {}
        for row_data in conn.execute(
            "SELECT ct.contract_id, t.name FROM contract_tags ct JOIN tags t ON t.id=ct.tag_id"
        ).fetchall():
            tag_map.setdefault(row_data[0], []).append(row_data[1])
        conn.close()

        shown = self._rows
        if q:
            shown = [r for r in shown if any(q in str(v).lower() for v in r[1:])]
        if sel_tag != "(Alle)":
            shown = [r for r in shown if sel_tag in tag_map.get(r[0], [])]

        self._tree.delete(*self._tree.get_children())
        for r in shown:
            _, cat, name, prov, cnum, _, _, _, amt, intv, sd, ed, np_, notes = r
            tags_str = ", ".join(tag_map.get(r[0], []))
            self._tree.insert("", "end", iid=str(r[0]),
                              values=(cat, name, prov, cnum,
                                      format_amount(amt), intv, sd, ed, np_, tags_str, notes or ""))
        n, tot = len(shown), len(self._rows)
        self._status.set(f"{n} Einträge" + (f"  (von {tot})" if n != tot else ""))
        self._docs_panel.set_entity(None)

    def _on_select(self, _event):
        rid = self._sel_id()
        if rid is None:
            self._docs_panel.set_entity(None)
            return
        r = self._row(rid)
        self._docs_panel.set_entity(rid, r[2] if r else "")

    def _sort(self, col):
        if col not in self.DB_IDX:
            return
        self._sort_asc = not self._sort_asc if self._sort_col == col else True
        self._sort_col = col
        idx = self.DB_IDX[col]
        self._rows.sort(key=lambda r: (r[idx] is None, r[idx] or ""), reverse=not self._sort_asc)
        self._filter()

    def _sel_id(self):
        s = self._tree.selection()
        return int(s[0]) if s else None

    def _row(self, rid):
        return next((r for r in self._rows if r[0] == rid), None)

    def _add(self):
        dlg = ContractDialog(self.winfo_toplevel(), "Neuen Vertrag / Versicherung anlegen")
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            new_id = insert_contract(d["category"], d["name"], d["provider"], d["contract_number"],
                                     d["login_url"], d["username"], d["password"], d["amount"],
                                     d["interval"], d["start_date"], d["end_date"],
                                     d["notice_period"], d["notes"])
            set_entry_tags("contract", new_id, d.get("tag_ids", []))
            self.load()

    def _edit(self):
        rid = self._sel_id()
        if rid is None:
            messagebox.showinfo("Hinweis", "Bitte einen Eintrag auswählen.")
            return
        r = self._row(rid)
        _, cat, name, prov, cnum, lu, un, pw_enc, amt, intv, sd, ed, np_, notes = r
        dlg = ContractDialog(self.winfo_toplevel(), f"Bearbeiten – {name}", {
            "category": cat or "", "name": name or "", "provider": prov or "",
            "contract_number": cnum or "", "login_url": lu or "",
            "username": un or "", "password": decrypt(pw_enc) if pw_enc else "",
            "amount": format_amount(amt), "interval": intv or "",
            "start_date": sd or "", "end_date": ed or "",
            "notice_period": np_ or "", "notes": notes or "",
            "tag_ids": [t[0] for t in get_entry_tags("contract", rid)],
        })
        self.wait_window(dlg)
        if dlg.result:
            d = dlg.result
            update_contract(rid, d["category"], d["name"], d["provider"],
                            d["contract_number"], d["login_url"], d["username"],
                            d["password"], d["amount"], d["interval"],
                            d["start_date"], d["end_date"], d["notice_period"], d["notes"])
            set_entry_tags("contract", rid, d.get("tag_ids", []))
            self.load()

    def _delete(self):
        rid = self._sel_id()
        if rid is None:
            messagebox.showinfo("Hinweis", "Bitte einen Eintrag auswählen.")
            return
        r = self._row(rid)
        if messagebox.askyesno("Löschen", f'Eintrag „{r[2]}" wirklich löschen?', icon="warning"):
            delete_contract(rid)
            self.load()

    def _export_pdf(self):
        sel = self._tree.selection()
        if sel:
            export_rows = [r for r in self._rows if str(r[0]) in sel]
            label = f"{len(export_rows)} ausgewählte Einträge"
        else:
            export_rows = self._rows
            label = "alle Einträge"
        if not export_rows:
            messagebox.showinfo("Keine Daten", "Keine Verträge vorhanden.")
            return
        show_pw = messagebox.askyesno("PDF-Export",
            f"PDF für {label} erstellen?\nPasswörter im Klartext exportieren?",
            icon="warning")
        fp = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"Vertraege_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            title="PDF speichern …")
        if not fp:
            return
        try:
            export_contracts_pdf(fp, export_rows, show_pw)
            if messagebox.askyesno("Gespeichert", f"PDF gespeichert:\n{fp}\n\nJetzt öffnen?"):
                os.startfile(fp)
        except Exception as e:
            messagebox.showerror("Fehler", str(e))


class _TagDialog(BaseDialog):
    def __init__(self, parent, title: str, data: dict = None):
        super().__init__(parent, title)
        self._data = data or {}
        self._vars = {}
        self._build_ui()
        self._center(parent)

    def _build_ui(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Tag-Name *", width=16, anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=6)
        self._vars["name"] = tk.StringVar(value=self._data.get("name", ""))
        e = ttk.Entry(frame, textvariable=self._vars["name"], width=28)
        e.grid(row=0, column=1, sticky="ew", padx=10, pady=6)
        e.focus()
        btn = ttk.Frame(frame)
        btn.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn, text="Speichern", command=self._save,   width=12).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Abbrechen", command=self.destroy, width=12).pack(side=tk.LEFT, padx=6)
        e.bind("<Return>", lambda _: self._save())

    def _save(self):
        name = self._vars["name"].get().strip()
        if not name:
            messagebox.showwarning("Pflichtfeld", "Bitte Tag-Namen eingeben.", parent=self)
            return
        self.result = {"name": name, "color": self._data.get("color", "#1a3c5e")}
        self.destroy()


# ---------------------------------------------------------------------------
# Tab: Einstellungen
# ---------------------------------------------------------------------------
class SettingsTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._tags: list = []
        self._build_ui()
        self.load()

    def _build_ui(self):
        tb = tk.Frame(self, bg=TB_BG, height=40)
        tb.pack(fill=tk.X)
        tb.pack_propagate(False)
        toolbar_btn(tb, "＋  Neu",       self._add).pack(side=tk.LEFT, padx=(8,2), pady=5)
        toolbar_btn(tb, "✎  Bearbeiten", self._edit).pack(side=tk.LEFT, padx=2, pady=5)
        toolbar_btn(tb, "✕  Löschen",   self._delete).pack(side=tk.LEFT, padx=2, pady=5)

        hdr = ttk.Frame(self, padding=(16, 12, 0, 4))
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Tag-Verwaltung", font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        tf = ttk.Frame(self, padding=(16, 0, 16, 0))
        tf.pack(fill=tk.BOTH, expand=True)
        self._tree = ttk.Treeview(tf, columns=("name", "color"), show="headings",
                                  selectmode="browse", height=20)
        self._tree.heading("name",  text="Tag-Name")
        self._tree.heading("color", text="Farbe")
        self._tree.column("name",  width=250, minwidth=120)
        self._tree.column("color", width=120, minwidth=80)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", lambda _: self._edit())
        self._tree.bind("<Delete>",   lambda _: self._delete())

        self._status = tk.StringVar()
        ttk.Label(self, textvariable=self._status, anchor="w",
                  padding=(16, 4)).pack(fill=tk.X, side=tk.BOTTOM)

    def load(self):
        self._tags = get_all_tags()
        self._tree.delete(*self._tree.get_children())
        for t in self._tags:
            self._tree.insert("", "end", iid=str(t[0]), values=(t[1], t[2]))
        self._status.set(f"{len(self._tags)} Tags")

    def _sel_id(self):
        s = self._tree.selection()
        return int(s[0]) if s else None

    def _tag_row(self, tid):
        return next((t for t in self._tags if t[0] == tid), None)

    def _add(self):
        dlg = _TagDialog(self.winfo_toplevel(), "Neuen Tag anlegen")
        self.wait_window(dlg)
        if dlg.result:
            insert_tag(dlg.result["name"], dlg.result["color"])
            self.load()

    def _edit(self):
        tid = self._sel_id()
        if tid is None:
            messagebox.showinfo("Hinweis", "Bitte einen Tag auswählen.")
            return
        row = self._tag_row(tid)
        dlg = _TagDialog(self.winfo_toplevel(), f"Tag bearbeiten – {row[1]}",
                         {"name": row[1], "color": row[2]})
        self.wait_window(dlg)
        if dlg.result:
            update_tag(tid, dlg.result["name"], dlg.result["color"])
            self.load()

    def _delete(self):
        tid = self._sel_id()
        if tid is None:
            messagebox.showinfo("Hinweis", "Bitte einen Tag auswählen.")
            return
        row = self._tag_row(tid)
        if messagebox.askyesno("Löschen",
                f'Tag „{row[1]}" wirklich löschen?\n'
                "Er wird von allen Einträgen entfernt.", icon="warning"):
            delete_tag(tid)
            self.load()


# ---------------------------------------------------------------------------
# Tab: Volltextsuche
# ---------------------------------------------------------------------------
class SearchTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._results: list = []
        self._build_ui()

    def _build_ui(self):
        # Suchleiste
        sf = ttk.Frame(self, padding=(12, 10))
        sf.pack(fill=tk.X)
        ttk.Label(sf, text="Volltextsuche:",
                  font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self._query = tk.StringVar()
        e = ttk.Entry(sf, textvariable=self._query, width=42, font=("Segoe UI", 10))
        e.pack(side=tk.LEFT, padx=8)
        e.bind("<Return>", lambda _: self._search())
        ttk.Button(sf, text="Suchen",    command=self._search, width=10).pack(side=tk.LEFT)
        ttk.Button(sf, text="✕", width=3,
                   command=self._clear).pack(side=tk.LEFT, padx=4)
        tk.Frame(sf, width=1, bg="#ccc").pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
        ttk.Button(sf, text="Alle neu indizieren",
                   command=self._reindex, width=18).pack(side=tk.LEFT)

        self._info = tk.StringVar(value="Suchbegriff eingeben und Enter drücken.")
        ttk.Label(self, textvariable=self._info, padding=(12, 2),
                  foreground="#555").pack(anchor="w")

        # Ergebnis-Treeview
        tf = ttk.Frame(self, padding=(12, 0, 12, 0))
        tf.pack(fill=tk.BOTH, expand=True)
        cols = ("original_name", "entity_label", "rubrik", "description", "preview")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                  selectmode="browse")
        self._tree.heading("original_name", text="Dateiname")
        self._tree.heading("entity_label",  text="Eintrag")
        self._tree.heading("rubrik",         text="Rubrik")
        self._tree.heading("description",   text="Beschreibung")
        self._tree.heading("preview",       text="Fundstelle")
        self._tree.column("original_name", width=180, minwidth=100, stretch=False)
        self._tree.column("entity_label",  width=160, minwidth=80,  stretch=False)
        self._tree.column("rubrik",         width=120, minwidth=60,  stretch=False)
        self._tree.column("description",   width=140, minwidth=80,  stretch=False)
        self._tree.column("preview",       width=420, minwidth=120, stretch=False)
        vsb = ttk.Scrollbar(tf, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", self._open_doc)

        self._status = tk.StringVar()
        ttk.Label(self, textvariable=self._status, anchor="w",
                  padding=(12, 4)).pack(fill=tk.X, side=tk.BOTTOM)

    def _search(self):
        q = self._query.get().strip()
        if len(q) < 2:
            messagebox.showinfo("Hinweis", "Bitte mindestens 2 Zeichen eingeben.", parent=self)
            return
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT d.id, d.original_name, d.stored_name, d.entity_type, d.entity_id, "
            "d.description, d.text_content FROM documents d "
            "WHERE d.text_content LIKE ? COLLATE NOCASE",
            (f"%{q}%",)
        ).fetchall()
        account_map  = {r[0]: r[1] for r in conn.execute("SELECT id, bank_name FROM accounts")}
        contract_map = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM contracts")}
        conn.close()

        self._results = rows
        self._tree.delete(*self._tree.get_children())
        for row in rows:
            did, orig, stored, etype, eid, desc, text = row
            label  = (account_map if etype == "account" else contract_map).get(eid, f"#{eid}")
            rubrik = "Bankkonten" if etype == "account" else "Verträge & Vers."
            preview = ""
            if text:
                idx = text.lower().find(q.lower())
                if idx >= 0:
                    start = max(0, idx - 40)
                    end   = min(len(text), idx + len(q) + 40)
                    snip  = text[start:end].replace("\n", " ").replace("\r", "")
                    preview = ("…" if start > 0 else "") + snip + ("…" if end < len(text) else "")
            self._tree.insert("", "end", iid=str(did),
                              values=(orig, label, rubrik, desc or "", preview))
        n = len(rows)
        self._info.set(f"{n} Dokument{'e' if n != 1 else ''} gefunden für: '{q}'")
        if n == 0:
            conn2 = sqlite3.connect(DB_PATH)
            unindexed = conn2.execute(
                "SELECT COUNT(*) FROM documents WHERE text_content IS NULL OR text_content = ''"
            ).fetchone()[0]
            conn2.close()
            hint = ""
            if unindexed:
                hint = f"  ·  {unindexed} Dokument(e) noch nicht indiziert → 'Alle neu indizieren' klicken"
            self._status.set(f"Keine Treffer.{hint}")
        else:
            self._status.set(f"Suche abgeschlossen  –  {n} Treffer")

    def _clear(self):
        self._query.set("")
        self._tree.delete(*self._tree.get_children())
        self._results = []
        self._status.set("")
        self._info.set("Suchbegriff eingeben und Enter drücken.")

    def _open_doc(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        did = int(sel[0])
        row = next((r for r in self._results if r[0] == did), None)
        if row:
            open_file(DOCS_DIR / row[2])

    def _reindex(self):
        if not messagebox.askyesno("Neu indizieren",
                "Alle vorhandenen Dokumente neu indizieren?\n"
                "Das kann bei vielen Dateien etwas dauern."):
            return
        success, errors = reindex_all_documents()
        msg = f"{success} Dokument(e) erfolgreich indiziert."
        if errors:
            msg += f"\n\n{len(errors)} Fehler:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n… und {len(errors) - 10} weitere."
            messagebox.showwarning("Fertig (mit Fehlern)", msg)
        else:
            messagebox.showinfo("Fertig", msg)


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------
class BankManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Bank Account Manager  –  Profil: {CURRENT_PROFILE}")
        self.geometry("1100x720")
        self.minsize(860, 520)
        self._configure_style()
        self._build_ui()

    def _configure_style(self):
        style = ttk.Style(self)
        for theme in ("vista", "clam", "default"):
            try:
                style.theme_use(theme)
                break
            except tk.TclError:
                continue
        style.configure("TNotebook.Tab", padding=(16, 6), font=("Segoe UI", 10))

    def _build_ui(self):
        topbar = tk.Frame(self, bg="#1a3c5e", height=28)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)
        tk.Label(topbar, text=f"Profil: {CURRENT_PROFILE}",
                 bg="#1a3c5e", fg="white",
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=10)
        tk.Button(topbar, text="Profil wechseln",
                  command=self._switch_profile,
                  bg="#2a5c8e", fg="white", relief="flat",
                  font=("Segoe UI", 8), padx=8, cursor="hand2"
                  ).pack(side=tk.RIGHT, padx=8, pady=3)

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self._accounts_tab  = AccountsTab(nb)
        self._contracts_tab = ContractsTab(nb)

        nb.add(self._accounts_tab,  text="  Bankkonten  ")
        nb.add(self._contracts_tab, text="  Verträge & Versicherungen  ")
        self._settings_tab = SettingsTab(nb)
        nb.add(self._settings_tab, text="  Einstellungen  ")
        self._search_tab = SearchTab(nb)
        nb.add(self._search_tab, text="  Suche  ")

    def _switch_profile(self):
        self.destroy()
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    root = tk.Tk()
    root.withdraw()

    # Beim ersten Start: Standard-Profil anlegen
    if not get_profiles():
        name = simpledialog.askstring(
            "Willkommen", "Erstes Profil anlegen – bitte Namen eingeben:",
            parent=root) or "Standard"
        create_profile(name.strip() or "Standard")

    dlg = ProfileSelectionDialog(root)
    root.wait_window(dlg)
    root.destroy()

    if not dlg.selected_profile:
        sys.exit(0)

    activate_profile(dlg.selected_profile)

    app = BankManagerApp()
    app.mainloop()
