"""
JARVIS - Google Sheets Sync (sheets.py)
ONE sheet for all clients — each client+sector gets its own tab.
Tab naming: "RE - Leads", "MFG - Stock", "ACC - Invoices", "SW - Tickets"
So all 4 sectors live in your single Jarvis_memory sheet cleanly.
"""

import os
from datetime import datetime

try:
    import gspread
    from google.oauth2.service_account import Credentials
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False

_BASE      = os.path.dirname(os.path.abspath(__file__))
CREDS_FILE = os.path.join(_BASE, "credentials.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Tab prefix per sector (short so tab names fit)
SECTOR_PREFIX = {
    "realestate":    "RE",
    "manufacturing": "MFG",
    "accounts":      "ACC",
    "software":      "SW",
}

# record_type → (tab suffix, ordered fields)
RECORD_MAP = {
    "lead":     ("Leads",    ["id","timestamp","name","phone","type","budget","location","property_type"]),
    "stock":    ("Stock",    ["id","timestamp","item_name","quantity","unit","min_qty","category","price"]),
    "invoice":  ("Invoices", ["id","timestamp","invoice_no","client_name","amount","gst_amount","status","date"]),
    "ticket":   ("Tickets",  ["id","timestamp","title","client_name","priority","status","description"]),
    "reminder": ("Reminders",["id","timestamp","message","remind_at","recur","status"]),
}

# Human-readable column headers matching field order above
HEADERS_MAP = {
    "lead":     ["ID","Timestamp","Name","Phone","Type","Budget","Location","Property Type"],
    "stock":    ["ID","Timestamp","Item Name","Quantity","Unit","Min Qty","Category","Price"],
    "invoice":  ["ID","Timestamp","Invoice No","Client Name","Amount","GST Amount","Status","Date"],
    "ticket":   ["ID","Timestamp","Title","Client Name","Priority","Status","Description"],
    "reminder": ["ID","Timestamp","Message","Remind At","Recur","Status"],
}


def _get_gc():
    if not SHEETS_AVAILABLE:
        raise RuntimeError("Run: pip install gspread google-auth")
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(
            f"credentials.json not found at {CREDS_FILE}\n"
            "Download from Google Cloud → Service Accounts → Keys → JSON"
        )
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def _tab_name(sector: str, record_type: str) -> str:
    """e.g. 'RE - Leads', 'ACC - Invoices', 'MFG - Stock'"""
    prefix = SECTOR_PREFIX.get(sector, sector.upper()[:3])
    suffix = RECORD_MAP.get(record_type, (record_type.title(), []))[0]
    return f"{prefix} - {suffix}"


def _get_or_create_tab(sheet, tab: str, headers: list):
    """Get existing worksheet or create it with headers."""
    try:
        ws = sheet.worksheet(tab)
        # Add headers if sheet is empty
        if not ws.row_values(1):
            ws.append_row(headers, value_input_option="RAW")
            _style_header(ws)
        return ws
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=tab, rows=2000, cols=len(headers))
        ws.append_row(headers, value_input_option="RAW")
        _style_header(ws)
        return ws


def _style_header(ws):
    try:
        ws.format("1:1", {
            "textFormat": {"bold": True, "foregroundColor": {"red":1,"green":1,"blue":1}},
            "backgroundColor": {"red": 0.13, "green": 0.13, "blue": 0.35}
        })
    except:
        pass  # styling is cosmetic, never crash for it


def append_record(sheet_id: str, record_type: str, record: dict,
                  sector: str = "") -> bool:
    """
    Append one record row to the correct tab.
    Called automatically every time bot saves a record.
    """
    if not sheet_id or record_type not in RECORD_MAP:
        return False

    try:
        gc       = _get_gc()
        sheet    = gc.open_by_key(sheet_id)
        tab      = _tab_name(sector, record_type)
        _, fields = RECORD_MAP[record_type]
        headers  = HEADERS_MAP[record_type]

        ws  = _get_or_create_tab(sheet, tab, headers)
        row = [str(record.get(f, "")) for f in fields]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"📊 Sheet ✓  [{tab}] ← {record.get('id','?')}")
        return True

    except Exception as e:
        # Never crash the bot — data is safe in clients.json
        print(f"⚠️  Sheet append failed (data safe locally): {e}")
        return False


def sync_all_to_sheet(sheet_id: str, sector: str, data: dict) -> bool:
    """
    Full sync — push ALL local data to sheet.
    Client sends /syncsheet to trigger this.
    """
    if not sheet_id:
        return False

    sector_records = {
        "realestate":    [("lead",    "leads")],
        "manufacturing": [("stock",   "stock")],
        "accounts":      [("invoice", "invoices")],
        "software":      [("ticket",  "tickets")],
    }

    try:
        gc    = _get_gc()
        sheet = gc.open_by_key(sheet_id)
        total = 0

        for rtype, data_key in sector_records.get(sector, []):
            records  = data.get(data_key, [])
            tab      = _tab_name(sector, rtype)
            _, fields = RECORD_MAP[rtype]
            headers  = HEADERS_MAP[rtype]

            ws = _get_or_create_tab(sheet, tab, headers)
            ws.clear()
            ws.append_row(headers, value_input_option="RAW")
            _style_header(ws)

            if records:
                rows = [[str(r.get(f, "")) for f in fields] for r in records]
                ws.append_rows(rows, value_input_option="USER_ENTERED")
                total += len(rows)

        # Also sync reminders tab
        reminders = data.get("reminders", [])
        if reminders:
            tab = _tab_name(sector, "reminder")
            _, fields = RECORD_MAP["reminder"]
            headers  = HEADERS_MAP["reminder"]
            ws = _get_or_create_tab(sheet, tab, headers)
            ws.clear()
            ws.append_row(headers, value_input_option="RAW")
            _style_header(ws)
            rows = [[str(r.get(f, "")) for f in fields] for r in reminders]
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            total += len(rows)

        print(f"✅ Full sync done: {total} records → {sector} tabs")
        return True

    except Exception as e:
        print(f"❌ Full sync error: {e}")
        return False


def setup_client_sheet(sheet_id: str, sector: str) -> bool:
    """
    One-time setup — creates all tabs for a sector.
    Not required — tabs auto-create on first record.
    But useful to call when onboarding a new client.
    """
    record_types = {
        "realestate":    ["lead", "reminder"],
        "manufacturing": ["stock", "reminder"],
        "accounts":      ["invoice", "reminder"],
        "software":      ["ticket", "reminder"],
    }
    try:
        gc    = _get_gc()
        sheet = gc.open_by_key(sheet_id)
        for rtype in record_types.get(sector, []):
            tab     = _tab_name(sector, rtype)
            headers = HEADERS_MAP[rtype]
            _get_or_create_tab(sheet, tab, headers)
            print(f"  ✓ Tab ready: {tab}")
        return True
    except Exception as e:
        print(f"❌ Setup error: {e}")
        return False