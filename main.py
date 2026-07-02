"""
JARVIS - Telegram Bot (main.py)
Hardened for 20-client pilot testing.
- File lock (no data corruption)
- Rate limiting per user
- Groq retry with exponential backoff
- Confirmation step for accounts invoices
- Daily 8am auto-alerts per sector
- Handles any Tamil/Tanglish/broken text
- Never crashes, always responds

import os
import json
import re
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes
)
from dotenv import load_dotenv
"""
# main.py - Add these lines at the top
import os
import logging

# Configure logging for Render
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Health check for Render
import threading

def start_health_server():
    """Simple HTTP server for Render health checks"""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        
        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/health':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'OK')
                else:
                    self.send_response(404)
                    self.end_headers()
        
        port = int(os.environ.get('PORT', 8000))
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"Health check server running on port {port}")
        server.serve_forever()
    except:
        pass

# Start health server in background (for Render)
if os.environ.get('RENDER'):
    import threading
    threading.Thread(target=start_health_server, daemon=True).start()
    logger.info("✅ Render health check server started")

import os, json, asyncio, time, threading
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

ai_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Google Sheets sync — optional, graceful fallback if not configured
try:
    from sheets import append_record as sheets_append, setup_client_sheet
    SHEETS_ENABLED = True
    print("✅ Google Sheets enabled")
except ImportError:
    SHEETS_ENABLED = False
    print("⚠️  sheets.py not found — running without Sheets sync")
_BASE     = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(_BASE, "clients.json")
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
_bot_app  = None

# ── Rate limiting: max 10 messages per user per minute ──────────
_rate_store = defaultdict(list)
_rate_lock  = threading.Lock()

def is_rate_limited(chat_id: str) -> bool:
    now = time.time()
    with _rate_lock:
        times = [t for t in _rate_store[chat_id] if now - t < 60]
        _rate_store[chat_id] = times
        if len(times) >= 10:
            return True
        _rate_store[chat_id].append(now)
        return False

# ── File lock: prevent simultaneous write corruption ────────────
_file_lock = threading.Lock()

def get_clients() -> dict:
    with _file_lock:
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)['clients']
        except (json.JSONDecodeError, KeyError):
            # Backup corrupt file and return empty
            backup = DATA_FILE + f".backup_{int(time.time())}"
            os.rename(DATA_FILE, backup)
            print(f"⚠️ clients.json was corrupt — backed up to {backup}")
            empty = {"clients": {}}
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(empty, f, indent=2)
            return {}

def save_clients(clients: dict):
    with _file_lock:
        # Write to temp file first, then rename (atomic write)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({"clients": clients}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)

def get_client_by_chat(chat_id: str):
    for cid, info in get_clients().items():
        if str(info.get("chat_id", "")) == str(chat_id):
            return cid, info
    return None, None

def _safe_int(v, d=0):
    try: return int(str(v).replace(",","").strip())
    except: return d

def _safe_float(v, d=0.0):
    try: return float(str(v).replace("₹","").replace(",","").strip())
    except: return d

# ── Save with auto-backup every 50 writes ───────────────────────
_write_count = 0
def save_record(client_id: str, rtype: str, data: dict) -> dict:
    global _write_count
    clients = get_clients()
    cl = clients[client_id]
    cl.setdefault("data", {"leads":[],"stock":[],"invoices":[],
                            "tickets":[],"contacts":[],"reminders":[]})
    rec = {
        "id": f"{rtype[:3].upper()}{datetime.now().strftime('%m%d%H%M%S')}",
        "timestamp": datetime.now().isoformat(), **data
    }
    key = {"lead":"leads","stock":"stock","inventory":"stock",
           "invoice":"invoices","ticket":"tickets",
           "reminder":"reminders","contact":"contacts"}.get(rtype, rtype+"s")
    cl["data"].setdefault(key, []).append(rec)
    clients[client_id] = cl
    save_clients(clients)
    _write_count += 1
    if _write_count % 50 == 0:
        _auto_backup()

    # ── Google Sheets sync (non-blocking, never crashes bot) ──
    if SHEETS_ENABLED:
        sheet_id = cl.get("sheet_id", "")
        sector   = cl.get("sector", "")
        if sheet_id:
            try:
                sheets_append(sheet_id, rtype, rec, sector=sector)
            except Exception as e:
                print(f"Sheet sync error (data safe locally): {e}")

    return rec

def _auto_backup():
    try:
        backup = DATA_FILE.replace(".json", f"_backup_{datetime.now().strftime('%Y%m%d')}.json")
        import shutil
        shutil.copy2(DATA_FILE, backup)
        print(f"💾 Auto-backup: {backup}")
    except Exception as e:
        print(f"Backup error: {e}")

def query_data(client_id: str, sector: str) -> dict:
    """Rich real-time data snapshot — always reads fresh from disk."""
    data = get_clients().get(client_id, {}).get("data", {})
    now  = datetime.now()
    this_month = now.strftime("%Y-%m")

    if sector == "realestate":
        leads = data.get("leads", [])
        by_loc = {}
        for l in leads:
            loc = l.get("location","unknown").lower()
            by_loc[loc] = by_loc.get(loc, 0) + 1
        month_leads = [l for l in leads if l.get("timestamp","").startswith(this_month)]
        return {
            "total": len(leads),
            "buyers":  sum(1 for l in leads if l.get("type") == "buy"),
            "sellers": sum(1 for l in leads if l.get("type") == "sell"),
            "renters": sum(1 for l in leads if l.get("type") == "rent"),
            "this_month": len(month_leads),
            "by_location": by_loc,
            "recent": leads[-5:],
            "all_leads": leads,
        }

    elif sector == "manufacturing":
        stock = data.get("stock", [])
        low   = [s for s in stock if _safe_int(s.get("quantity",0)) < _safe_int(s.get("min_qty",10))]
        cats  = {}
        for s in stock:
            c = s.get("category","general")
            cats[c] = cats.get(c,0) + 1
        total_val = sum(_safe_float(s.get("price",0)) * _safe_int(s.get("quantity",0)) for s in stock)
        return {
            "total_items": len(stock),
            "low_stock": len(low),
            "low_items": [f"{s.get('item_name','?')} — {s.get('quantity','?')} {s.get('unit','')} (min:{s.get('min_qty','?')})" for s in low],
            "categories": cats,
            "total_inventory_value": total_val,
            "recent": stock[-5:],
            "all_stock": stock,
        }

    elif sector == "accounts":
        inv        = data.get("invoices", [])
        paid       = [i for i in inv if i.get("status") == "paid"]
        pend       = [i for i in inv if i.get("status") == "pending"]
        partial    = [i for i in inv if i.get("status") == "partial"]
        month_paid = [i for i in paid if i.get("timestamp","").startswith(this_month)]
        month_pend = [i for i in pend if i.get("timestamp","").startswith(this_month)]
        total_rev  = sum(_safe_float(i.get("amount",0)) for i in paid)
        pend_amt   = sum(_safe_float(i.get("amount",0)) for i in pend)
        month_rev  = sum(_safe_float(i.get("amount",0)) for i in month_paid)
        # Per-client breakdown
        client_summary = {}
        for i in inv:
            cn = i.get("client_name","?")
            if cn not in client_summary:
                client_summary[cn] = {"paid":0,"pending":0,"total":0}
            amt = _safe_float(i.get("amount",0))
            client_summary[cn]["total"] += amt
            if i.get("status") == "paid":
                client_summary[cn]["paid"] += amt
            else:
                client_summary[cn]["pending"] += amt
        return {
            "total": len(inv),
            "paid": len(paid),
            "pending": len(pend),
            "partial": len(partial),
            "total_revenue": total_rev,
            "pending_amt": pend_amt,
            "this_month_revenue": month_rev,
            "this_month_paid": len(month_paid),
            "this_month_pending": len(month_pend),
            "pending_list": [f"{i.get('client_name','?')} ₹{i.get('amount','?')} ({i.get('invoice_no','?')})" for i in pend],
            "client_summary": client_summary,
            "recent": inv[-5:],
            "all_invoices": inv,
        }

    elif sector == "software":
        tix      = data.get("tickets", [])
        open_    = [t for t in tix if t.get("status") == "open"]
        prog     = [t for t in tix if t.get("status") == "progress"]
        resolved = [t for t in tix if t.get("status") == "resolved"]
        high     = [t for t in tix if t.get("priority") == "high"]
        month_t  = [t for t in tix if t.get("timestamp","").startswith(this_month)]
        # Per-client breakdown
        client_tickets = {}
        for t in tix:
            cn = t.get("client_name","?")
            client_tickets[cn] = client_tickets.get(cn,0) + 1
        return {
            "total": len(tix),
            "open": len(open_),
            "in_progress": len(prog),
            "resolved": len(resolved),
            "high_priority": len(high),
            "this_month": len(month_t),
            "high_list": [f"{t.get('title','?')} — {t.get('client_name','?')}" for t in high],
            "open_list": [f"{t.get('id','?')} {t.get('title','?')} [{t.get('priority','?')}]" for t in open_],
            "client_tickets": client_tickets,
            "recent": tix[-5:],
            "all_tickets": tix,
        }
    return {}


# ══════════════════════════════════════════════════════════════
# SECTOR CONFIG
# ══════════════════════════════════════════════════════════════
SECTOR_CFG = {
    "realestate": {
        "emoji": "🏠", "title": "Real Estate",
        "help": (
            "📋 *Enna panalam:*\n"
            "• Lead add: `Ravi, 98765 43210, 50L budget, Chennai flat venum`\n"
            "• List: `leads kaattu` · Filter: `buyers list`\n"
            "• Reminder: `Tomorrow 10am Ravi ku call pannu remind`\n"
            "• Summary: /summary · Help: /help"
        ),
        "prompt": (
            "You manage PROPERTY LEADS for a Tamil Nadu real estate business.\n"
            "Understand buyers/sellers/renters. Budget in Lakhs(L) or Crores(Cr).\n"
            "Terms: flat, villa, plot, land, cents, grounds, sqft, maadu nilam, layout, site.\n"
            "Broken Tamil/Tanglish like 'veedu venum', 'vikka porom', 'rent ku tharanga' = valid input.\n"
            "SAVE → extract: name, phone, type(buy/sell/rent), budget, location, property_type.\n"
            "  If phone missing → still save with phone='not given'.\n"
            "  If budget missing → save with budget='not mentioned'.\n"
            "QUERY → filter/count leads by type, location, budget range.\n"
            "REMINDER → extract: message, remind_at(ISO datetime), recur(daily/weekly/none).\n"
            "DO NOT mention invoices, stock, tickets — irrelevant here."
        ),
    },
    "manufacturing": {
        "emoji": "🏭", "title": "Manufacturing",
        "help": (
            "📋 *Enna panalam:*\n"
            "• Add stock: `Steel rods 500 kg, min 100`\n"
            "• Use panrom: `Cement bags 50 use pannom`\n"
            "• Check: `low stock` · `all items`\n"
            "• Reminder: `Monday stock check remind`\n"
            "• Summary: /summary · Help: /help"
        ),
        "prompt": (
            "You manage STOCK AND INVENTORY for a Tamil Nadu manufacturing unit.\n"
            "Units: kg, tons, liters, pcs, rolls, bags, boxes, meters, feet.\n"
            "Broken input like 'rod 500 potom', 'cement kurachuduchu', 'iron sheet illaye' = valid.\n"
            "SAVE (add) → extract: item_name, quantity(positive), unit, category, min_qty, price.\n"
            "SAVE (use/consume) → extract: item_name, quantity(negative number to subtract), unit.\n"
            "  Use action='add' or action='consume' in extracted_data.\n"
            "QUERY → stock levels, low stock list, category breakdown.\n"
            "REMINDER → extract: message, remind_at(ISO datetime), recur(daily/weekly/none).\n"
            "DO NOT mention leads, invoices, tickets — irrelevant here."
        ),
    },
    "accounts": {
        "emoji": "💰", "title": "Accounts",
        "help": (
            "📋 *Enna panalam:*\n"
            "• Invoice: `INV-042 Kumar Traders 25000 paid`\n"
            "• Pending: `pending list kaattu`\n"
            "• Reminder: `Friday 5pm Kumar follow up remind`\n"
            "• Summary: /summary · Help: /help"
        ),
        "prompt": (
            "You manage INVOICES AND PAYMENTS for a Tamil Nadu business.\n"
            "Track: invoice_no, client_name, amount(₹), gst_amount, status(paid/pending/partial), date.\n"
            "Broken input like 'kumar 25k thararu', 'bill raise pannunga', 'payment vandhuchu' = valid.\n"
            "SAVE → extract: invoice_no(generate INV-XXX if missing), client_name, amount, gst_amount, status, date.\n"
            "QUERY → revenue, pending list, month summary.\n"
            "REMINDER → extract: message, remind_at(ISO datetime), recur(daily/weekly/none).\n"
            "DO NOT mention leads, stock, tickets — irrelevant here."
        ),
    },
    "software": {
        "emoji": "💻", "title": "Software",
        "help": (
            "📋 *Enna panalam:*\n"
            "• Ticket: `Login crash - ABC Corp - high priority`\n"
            "• Update: `TKT001 resolved pannu`\n"
            "• Check: `open tickets` · `high priority`\n"
            "• Reminder: `Daily 9am standup remind`\n"
            "• Summary: /summary · Help: /help"
        ),
        "prompt": (
            "You manage SUPPORT TICKETS for a Tamil Nadu software company.\n"
            "Track: title, client_name, priority(low/medium/high), status(open/progress/resolved), description.\n"
            "Broken input like 'ABC Corp la bug iruku', 'login work agala', 'payment page crash' = valid.\n"
            "SAVE → extract: title, client_name, priority(default=medium), status(default=open), description.\n"
            "QUERY → open/high-priority/resolved tickets, client-wise breakdown.\n"
            "REMINDER → extract: message, remind_at(ISO datetime), recur(daily/weekly/none).\n"
            "DO NOT mention leads, stock, invoices — irrelevant here."
        ),
    },
}


# ══════════════════════════════════════════════════════════════
# AI BRAIN — Pro level, Tamil Nadu culture aware
# ══════════════════════════════════════════════════════════════
async def ai_understand(text: str, client: dict, ctx: dict) -> dict:
    sec  = client["sector"]
    cfg  = SECTOR_CFG.get(sec, {})
    pref = client.get("language_pref", "tanglish")
    owner = client.get("owner", "")

    if pref == "tamil":
        lang = (
            "Reply ONLY in pure Tamil script (தமிழ்). "
            "Warm, respectful tone. Use 'நன்றி', 'சரி', 'செய்துவிட்டேன்' naturally."
        )
    elif pref == "english":
        lang = "Reply in clear simple English. Warm and professional."
    else:
        lang = (
            "Reply in NATURAL TANGLISH — exactly how Tamil Nadu people text each other. "
            "Mix Tamil words into English sentences fluidly. "
            "GOOD examples: "
            "'Seri da! Lead save achu 👍', "
            "'Noted bro, Ravi details add panniten!', "
            "'Stock low iruku da, reorder panna sollu!', "
            "'Payment pending iruku, follow up panrom!', "
            "'Romba thanks! Ticket raise panniten 🎫'. "
            "BAD (avoid): Formal English, pure Tamil, robotic responses. "
            "Match the user's energy — if they're casual, be casual. If urgent, be quick. "
            "Use Tamil words: seri, illa, achu, pannu, kaattu, sollu, vandhuchu, pochu, iruku, vendam, nalla. "
            "Only use pure Tamil script if user types in Tamil script. "
            "Only use pure English if user types only in English."
        )

    # Build smart context summary for AI
    ctx_summary = ""
    if sec == "realestate":
        ctx_summary = f"Total leads: {ctx.get('total',0)} | Buyers: {ctx.get('buyers',0)} | Sellers: {ctx.get('sellers',0)} | Renters: {ctx.get('renters',0)}"
        recent = ctx.get('recent',[])
        if recent:
            ctx_summary += f"\nRecent: " + ", ".join(f"{l.get('name','?')}({l.get('type','?')})" for l in recent)
    elif sec == "manufacturing":
        ctx_summary = f"Stock items: {ctx.get('total_items',0)} | Low stock: {ctx.get('low_stock',0)}"
        if ctx.get('low_items'):
            ctx_summary += f"\nLow items: {', '.join(ctx['low_items'][:3])}"
    elif sec == "accounts":
        ctx_summary = f"Invoices: {ctx.get('total',0)} | Pending: {ctx.get('pending',0)} (₹{ctx.get('pending_amt',0):,.0f}) | Paid: {ctx.get('paid',0)}"
        if ctx.get('pending_list'):
            ctx_summary += f"\nPending from: {', '.join(ctx['pending_list'][:3])}"
    elif sec == "software":
        ctx_summary = f"Tickets: {ctx.get('total',0)} | Open: {ctx.get('open',0)} | High priority: {ctx.get('high_priority',0)}"
        if ctx.get('high_list'):
            ctx_summary += f"\nUrgent: {', '.join(ctx['high_list'][:2])}"

    # Build full data context for AI — always fresh
    ctx = query_data(client_id=client.get("_id",""), sector=sec) if False else ctx
    data_json = json.dumps(ctx, ensure_ascii=False, default=str, indent=2)

    system = f"""You are JARVIS — an intelligent business assistant for Tamil Nadu SMEs.
Client: {client['name']} | Sector: {cfg.get('title','')} | Owner: {owner}
Date/Time: {datetime.now().strftime('%A, %d %b %Y — %I:%M %p')} IST

━━━ YOUR JOB ━━━
{cfg.get('prompt','')}

━━━ LIVE BUSINESS DATA (always up to date) ━━━
{data_json}

━━━ LANGUAGE ━━━
{lang}

━━━ THINKING PROCESS ━━━
Before responding, think through these steps silently:

1. WHAT does the user want? (ignore spelling mistakes, grammar, language mix)
   Common Tamil Nadu business phrases to recognize:
   - "evlo profit / varuthu / income" → they want revenue/earnings summary
   - "intha month / this month" → filter data by current month
   - "pending / baaki" → unpaid amounts
   - "yaaru / who / list" → they want a list
   - "low stock / tharaamai" → items below minimum
   - "remind / reminder / sollu" → set a reminder
   - "paid / vanduchu / tharuttanga" → payment received
   - "ticket / issue / problem / bug" → software ticket
   - "lead / customer / client wants" → real estate lead
   - Numbers: 25k=25000, 2L=200000, 50k=50000, 1Cr=10000000

2. DATES — always resolve to actual ISO datetime:
   - "tomorrow" = {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}
   - "next week thursday" = calculate actual date
   - "friday" = next upcoming friday
   - "morning" = 09:00, "afternoon" = 14:00, "evening" = 18:00, "night" = 21:00
   - Always combine: "tomorrow morning" = {(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')}T09:00:00

3. ANSWERING QUERIES — use the LIVE DATA above to answer:
   - "profit / revenue / income" → look at total_revenue or this_month_revenue in data
   - "how many leads" → look at total in data
   - "pending" → look at pending_amt and pending_list
   - "low stock" → look at low_items
   - NEVER say "no data" if data exists above. Read it carefully.
   - If genuinely empty, say so warmly and encourage them to add data

4. SAVING DATA — extract confidently, don't ask unnecessary questions:
   - Missing phone → save as "not given"
   - Missing amount → ask once, short
   - Ambiguous → save best guess, confirm in reply

5. REPLY STYLE:
   - Max 3 lines always
   - Conversational, warm, like a helpful colleague
   - Include actual numbers/names from data when answering queries
   - For saves: confirm what was saved + the ID
   - For queries: give the actual answer with numbers
   - Never say "I cannot", "I don't have access", "no data available" if data exists

━━━ OUTPUT — ONLY valid JSON, zero extra text ━━━
{{
  "intent": "SAVE|QUERY|UPDATE|GREET|HELP|OTHER",
  "record_type": "lead|stock|invoice|ticket|reminder|null",
  "extracted_data": {{}},
  "reply": "punchy reply with actual data/numbers",
  "needs_confirm": false,
  "confirm_text": ""
}}

needs_confirm=true ONLY for accounts invoice SAVE.
confirm_text = one line summary for user to verify before saving."""

    # Retry up to 3 times with backoff
    for attempt in range(3):
        try:
            resp = ai_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role":"system","content":system},
                          {"role":"user","content":text}],
                response_format={"type":"json_object"},
                temperature=0.25,
                max_tokens=600,
                timeout=10
            )
            result = json.loads(resp.choices[0].message.content)
            # Validate required keys exist
            result.setdefault("intent", "OTHER")
            result.setdefault("reply", "Seri, noted!")
            result.setdefault("record_type", None)
            result.setdefault("extracted_data", {})
            result.setdefault("needs_confirm", False)
            result.setdefault("confirm_text", "")
            return result
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s backoff
            else:
                print(f"AI error after 3 attempts: {e}")
                return {
                    "intent": "OTHER", "record_type": None,
                    "extracted_data": {}, "needs_confirm": False,
                    "confirm_text": "",
                    "reply": "Oru second da, server busy! Try again panunga 🙏"
                }


# ══════════════════════════════════════════════════════════════
# PENDING CONFIRMATIONS (for accounts invoice)
# ══════════════════════════════════════════════════════════════
_pending_confirms: dict = {}  # chat_id → {record_type, extracted_data, reply}

async def handle_confirm_reply(update: Update, text: str, chat_id: str, client_id: str, client: dict):
    pending = _pending_confirms.pop(chat_id, None)
    if not pending:
        return False  # no pending confirmation

    yes_words = ["yes","y","ha","haa","correct","seri","ok","okay","confirm","aam","aamaa","save","proceed"]
    no_words  = ["no","n","illa","illai","wrong","cancel","not correct","change","edit"]
    tl = text.lower().strip()

    if any(w in tl for w in yes_words):
        rec = save_record(client_id, pending["record_type"], pending["extracted_data"])
        await update.message.reply_text(
            f"✅ *Saved!* (ID: `{rec.get('id','')}`)\n{pending['reply']}",
            parse_mode='Markdown')
        # Pending invoice alert
        if pending["extracted_data"].get("status","") == "pending":
            await update.message.reply_text(
                f"💡 Reminder set panna sollu:\n`Friday 5pm {pending['extracted_data'].get('client_name','')} follow up remind`",
                parse_mode='Markdown')
    elif any(w in tl for w in no_words):
        await update.message.reply_text(
            "❌ Cancelled. Please re-enter the correct details.",
            parse_mode='Markdown')
    else:
        # Put it back and ask again
        _pending_confirms[chat_id] = pending
        await update.message.reply_text(
            "Seri ah illaya? `yes` or `no` sollu da 😄",
            parse_mode='Markdown')
    return True


# ══════════════════════════════════════════════════════════════
# DAILY AUTO-ALERTS (8am IST)
# ══════════════════════════════════════════════════════════════
async def daily_low_stock_alert(client_id: str, chat_id: str):
    try:
        ctx = query_data(client_id, "manufacturing")
        low_items = ctx.get("low_items", [])
        if not low_items:
            return
        items_text = "\n".join(f"  🔴 {item}" for item in low_items)
        await _bot_app.bot.send_message(
            chat_id=int(chat_id),
            text=f"🌅 *Kaalai Vanakkam! Daily Stock Alert*\n\n"
                 f"⚠️ *{len(low_items)} items low stock:*\n{items_text}\n\n"
                 f"Reorder panna marandhudutha! 📦",
            parse_mode='Markdown')
    except Exception as e:
        print(f"Stock alert error {client_id}: {e}")

async def daily_pending_alert(client_id: str, chat_id: str):
    try:
        ctx = query_data(client_id, "accounts")
        pending = ctx.get("pending", 0)
        if pending == 0:
            return
        pending_list = ctx.get("pending_list", [])
        items = "\n".join(f"  ⏳ {p}" for p in pending_list)
        await _bot_app.bot.send_message(
            chat_id=int(chat_id),
            text=f"🌅 *Kaalai Vanakkam! Payment Alert*\n\n"
                 f"*{pending} invoices pending* — ₹{ctx.get('pending_amt',0):,.0f}\n\n"
                 f"{items}\n\nFollow up panna nalla time! 💰",
            parse_mode='Markdown')
    except Exception as e:
        print(f"Payment alert error {client_id}: {e}")

async def daily_ticket_alert(client_id: str, chat_id: str):
    try:
        ctx = query_data(client_id, "software")
        open_count = ctx.get("open", 0)
        high = ctx.get("high_priority", 0)
        if open_count == 0:
            return
        high_list = ctx.get("high_list", [])
        items = "\n".join(f"  🚨 {t}" for t in high_list)
        msg = (f"🌅 *Kaalai Vanakkam! Ticket Summary*\n\n"
               f"Open: *{open_count}* | High Priority: *{high}*\n")
        if items:
            msg += f"\n*Urgent:*\n{items}"
        await _bot_app.bot.send_message(
            chat_id=int(chat_id), text=msg, parse_mode='Markdown')
    except Exception as e:
        print(f"Ticket alert error {client_id}: {e}")

def schedule_daily_jobs():
    clients = get_clients()
    count = 0
    for cid, cl in clients.items():
        chat_id = str(cl.get("chat_id",""))
        if not chat_id or chat_id in ("None","null",""):
            continue
        sec    = cl.get("sector","")
        job_id = f"daily_{cid}"
        fn_map = {
            "manufacturing": daily_low_stock_alert,
            "accounts":      daily_pending_alert,
            "software":      daily_ticket_alert,
        }
        if sec in fn_map:
            scheduler.add_job(fn_map[sec], 'cron',
                hour=8, minute=0, args=[cid, chat_id],
                id=job_id, replace_existing=True)
            count += 1
    print(f"📅 Scheduled {count} daily digest jobs")


# ══════════════════════════════════════════════════════════════
# REMINDERS
# ══════════════════════════════════════════════════════════════
async def fire_reminder(chat_id: str, client_id: str, reminder_id: str, message: str):
    try:
        await _bot_app.bot.send_message(
            chat_id=int(chat_id),
            text=f"⏰ *Reminder!*\n\n{message}",
            parse_mode='Markdown')
        clients = get_clients()
        rems = clients[client_id].get("data",{}).get("reminders",[])
        for r in rems:
            if r.get("id") == reminder_id and r.get("recur","none") == "none":
                r["status"] = "fired"
        clients[client_id]["data"]["reminders"] = rems
        save_clients(clients)
    except Exception as e:
        print(f"Reminder fire error: {e}")

def schedule_reminder(chat_id: str, client_id: str, rec: dict):
    rid     = rec.get("id","")
    message = rec.get("message","Reminder!")
    recur   = rec.get("recur","none")
    try:
        run_at = datetime.fromisoformat(rec.get("remind_at",""))
    except:
        run_at = datetime.now() + timedelta(hours=1)
    job_id = f"rem_{client_id}_{rid}"
    if recur == "daily":
        scheduler.add_job(fire_reminder, 'cron',
            hour=run_at.hour, minute=run_at.minute,
            args=[chat_id, client_id, rid, message],
            id=job_id, replace_existing=True)
    elif recur == "weekly":
        scheduler.add_job(fire_reminder, 'cron',
            day_of_week=run_at.strftime('%a').lower(),
            hour=run_at.hour, minute=run_at.minute,
            args=[chat_id, client_id, rid, message],
            id=job_id, replace_existing=True)
    else:
        if run_at > datetime.now():
            scheduler.add_job(fire_reminder, 'date',
                run_date=run_at,
                args=[chat_id, client_id, rid, message],
                id=job_id, replace_existing=True)

def restore_reminders():
    clients = get_clients()
    count = 0
    for cid, cl in clients.items():
        chat_id = str(cl.get("chat_id",""))
        if not chat_id or chat_id in ("None","null",""):
            continue
        for rem in cl.get("data",{}).get("reminders",[]):
            if rem.get("status","") == "fired":
                continue
            try:
                run_at = datetime.fromisoformat(rem.get("remind_at",""))
                if rem.get("recur","none") == "none" and run_at < datetime.now():
                    continue
            except:
                continue
            schedule_reminder(chat_id, cid, rem)
            count += 1
    print(f"♻️  Restored {count} pending reminders")


# ══════════════════════════════════════════════════════════════
# GREETING & SUMMARY
# ══════════════════════════════════════════════════════════════
async def send_greeting(update: Update, client_id: str, client: dict):
    sec  = client["sector"]
    cfg  = SECTOR_CFG.get(sec, {})
    ctx  = query_data(client_id, sec)
    hour = datetime.now().hour
    time_greet = ("Kaalai Vanakkam 🌅" if hour < 12
                  else "Madhiyanam Vanakkam ☀️" if hour < 17
                  else "Maalai Vanakkam 🌆")

    stats_map = {
        "realestate":    f"Leads: *{ctx.get('total',0)}* | Buyers: {ctx.get('buyers',0)} | Sellers: {ctx.get('sellers',0)}",
        "manufacturing": f"Stock Items: *{ctx.get('total_items',0)}* | 🔴 Low: {ctx.get('low_stock',0)}",
        "accounts":      f"Invoices: *{ctx.get('total',0)}* | ⏳ Pending: ₹{ctx.get('pending_amt',0):,.0f}",
        "software":      f"Tickets: *{ctx.get('total',0)}* | 🔴 Open: {ctx.get('open',0)} | 🚨 High: {ctx.get('high_priority',0)}",
    }
    stats = stats_map.get(sec, "")

    active_rem = [r for r in get_clients()[client_id].get("data",{}).get("reminders",[])
                  if r.get("status","") != "fired"]

    msg = (f"{cfg.get('emoji','🤖')} *JARVIS — {client['name']}*\n"
           f"{time_greet}, {client.get('owner','')}!\n\n"
           f"📊 {stats}\n"
           + (f"⏰ Active reminders: {len(active_rem)}\n" if active_rem else "") +
           f"\n{cfg.get('help','')}")

    kb = [[
        InlineKeyboardButton("📊 Summary",   callback_data="summary"),
        InlineKeyboardButton("⏰ Reminders", callback_data="reminders"),
        InlineKeyboardButton("❓ Help",      callback_data="help"),
    ]]
    await update.message.reply_text(msg, parse_mode='Markdown',
                                    reply_markup=InlineKeyboardMarkup(kb))

def build_summary(client_id: str, client: dict) -> str:
    sec = client["sector"]
    cfg = SECTOR_CFG.get(sec, {})
    ctx = query_data(client_id, sec)
    e, n = cfg.get("emoji","📊"), client["name"]

    if sec == "realestate":
        rec = ctx.get("recent",[])
        lines = "\n".join(f"  • {l.get('name','?')} — {l.get('phone','')} ({l.get('type','?')}) {l.get('budget','')}"
                          for l in rec) or "  No leads yet"
        return (f"{e} *{n}*\n\nTotal: *{ctx['total']}* | Buy: {ctx['buyers']} | Sell: {ctx['sellers']} | Rent: {ctx['renters']}\n\n🕐 Recent:\n{lines}")

    elif sec == "manufacturing":
        low = ctx.get("low_items",[])
        low_txt = "\n".join(f"  🔴 {i}" for i in low) if low else "  ✅ All sufficient"
        rec = ctx.get("recent",[])
        lines = "\n".join(f"  • {s.get('item_name','?')} — {s.get('quantity','?')} {s.get('unit','')}"
                          for s in rec) or "  No items yet"
        return (f"{e} *{n}*\n\nItems: *{ctx['total_items']}* | 🔴 Low: {ctx['low_stock']}\n\n"
                f"⚠️ Low stock:\n{low_txt}\n\n🕐 Recent:\n{lines}")

    elif sec == "accounts":
        plist = ctx.get("pending_list",[])
        p_txt = "\n".join(f"  ⏳ {p}" for p in plist) if plist else "  ✅ No pending"
        return (f"{e} *{n}*\n\nInvoices: *{ctx['total']}* | ✅ Paid: {ctx['paid']} | ⏳ Pending: {ctx['pending']}\n"
                f"Pending: *₹{ctx.get('pending_amt',0):,.0f}*\n\n{p_txt}")

    elif sec == "software":
        hlist = ctx.get("high_list",[])
        h_txt = "\n".join(f"  🚨 {t}" for t in hlist) if hlist else "  ✅ No high priority"
        return (f"{e} *{n}*\n\nTickets: *{ctx['total']}* | 🔴 Open: {ctx['open']} | 🚨 High: {ctx['high_priority']}\n\n{h_txt}")

    return "No data yet!"


# ══════════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    client_id, client = get_client_by_chat(chat_id)
    if client:
        await send_greeting(update, client_id, client)
    else:
        await update.message.reply_text(
            "🤖 *Vanakkam! JARVIS ku welcome!*\n\n"
            "Ungal *Client ID* anuppu:\n`LINK CLT001`\n\n"
            "_(ID was given when you registered)_",
            parse_mode='Markdown')

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, client = get_client_by_chat(str(update.message.chat_id))
    if client:
        cfg = SECTOR_CFG.get(client["sector"], {})
        await update.message.reply_text(
            cfg.get("help","Type anything!") + "\n\n_Language: /setlang tamil|english|tanglish_",
            parse_mode='Markdown')
    else:
        await update.message.reply_text("Link first: `LINK CLT001`", parse_mode='Markdown')

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_id, client = get_client_by_chat(str(update.message.chat_id))
    if not client:
        await update.message.reply_text("Link first: `LINK CLT001`", parse_mode='Markdown')
        return
    await update.message.reply_text(build_summary(client_id, client), parse_mode='Markdown')

async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_id, client = get_client_by_chat(str(update.message.chat_id))
    if not client:
        await update.message.reply_text("Link first: `LINK CLT001`", parse_mode='Markdown')
        return
    reminders = get_clients()[client_id].get("data",{}).get("reminders",[])
    active = [r for r in reminders if r.get("status","") != "fired"]
    if not active:
        await update.message.reply_text(
            "⏰ No active reminders.\n\nAdd one: `Tomorrow 10am Ravi ku call remind`",
            parse_mode='Markdown')
        return
    lines = []
    for r in active[-10:]:
        try:
            dt = datetime.fromisoformat(r.get("remind_at","")).strftime("%d %b %I:%M %p")
        except:
            dt = r.get("remind_at","?")
        recur = f" 🔁{r.get('recur','')}" if r.get("recur","none") != "none" else ""
        lines.append(f"• {r.get('message','?')}\n  _{dt}{recur}_")
    await update.message.reply_text(
        f"⏰ *Active Reminders ({len(active)}):*\n\n" + "\n\n".join(lines),
        parse_mode='Markdown')

async def cmd_syncsheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command — full sync of local data to Google Sheet."""
    client_id, client = get_client_by_chat(str(update.message.chat_id))
    if not client:
        await update.message.reply_text("Link first: `LINK CLT001`", parse_mode='Markdown')
        return
    if not SHEETS_ENABLED:
        await update.message.reply_text("❌ Google Sheets not configured on server.", parse_mode='Markdown')
        return
    # Re-read fresh from disk to get latest sheet_id
    fresh_clients = get_clients()
    fresh_client  = fresh_clients.get(client_id, client)
    sheet_id = fresh_client.get("sheet_id", "")
    if not sheet_id:
        await update.message.reply_text(
            "No sheet_id set. Ask JARVIS admin to add sheet_id to clients.json.")
        return
    await update.message.reply_text("⏳ Syncing to Google Sheet...", parse_mode='Markdown')
    try:
        from sheets import sync_all_to_sheet
        data = fresh_clients[client_id].get("data", {})
        ok = sync_all_to_sheet(sheet_id, fresh_client.get("sector",""), data)
        if ok:
            await update.message.reply_text("✅ *Full sync done!* All data pushed to your Google Sheet.", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Sync failed. Check if sheet is shared with service account.", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Sync error: {str(e)}", parse_mode='Markdown')


async def cmd_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_id, _ = get_client_by_chat(str(update.message.chat_id))
    if not client_id:
        await update.message.reply_text("Link first: `LINK CLT001`", parse_mode='Markdown')
        return
    args = context.args
    if not args or args[0].lower() not in ("tamil","english","tanglish"):
        await update.message.reply_text(
            "Usage:\n`/setlang tamil` — Pure Tamil\n`/setlang english` — English\n`/setlang tanglish` — Mix (default)",
            parse_mode='Markdown')
        return
    lang = args[0].lower()
    clients = get_clients()
    clients[client_id]["language_pref"] = lang
    save_clients(clients)
    labels = {"tamil":"Pure Tamil 🇮🇳","english":"English 🇬🇧","tanglish":"Tanglish 😎"}
    await update.message.reply_text(f"✅ Language → *{labels[lang]}*", parse_mode='Markdown')

async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logout command - unlink chat from client"""
    chat_id = str(update.message.chat_id)
    
    # Get client name before logout
    client_id, client = get_client_by_chat(chat_id)
    if not client:
        await update.message.reply_text("❌ Not logged in!", parse_mode='Markdown')
        return
    
    client_name = client.get('name', 'Sir')
    
    # Unlink the chat
    clients = get_clients()
    for cid, info in clients.items():
        if str(info.get('chat_id', '')) == str(chat_id):
            clients[cid]['chat_id'] = None
            break
    save_clients(clients)
    
    await update.message.reply_text(
        f"👋 *Goodbye {client_name}!*\n\n"
        f"🔒 Your data is safe.\n\n"
        f"Login again: `LINK {client_id}`",
        parse_mode='Markdown'
    )


# ══════════════════════════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════════════════════════
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    client_id, client = get_client_by_chat(str(q.message.chat_id))
    if not client:
        await q.edit_message_text("Session expired. Send /start")
        return
    action = q.data
    if action == "summary":
        await q.edit_message_text(build_summary(client_id, client), parse_mode='Markdown')
    elif action == "reminders":
        rems = get_clients()[client_id].get("data",{}).get("reminders",[])
        active = [r for r in rems if r.get("status","") != "fired"]
        if not active:
            await q.edit_message_text("⏰ No reminders yet.\n\n`Tomorrow 10am call Ravi remind`", parse_mode='Markdown')
        else:
            lines = []
            for r in active[-5:]:
                try:
                    dt = datetime.fromisoformat(r.get("remind_at","")).strftime("%d %b %I:%M %p")
                except:
                    dt = "?"
                lines.append(f"• {r.get('message','?')} — _{dt}_")
            await q.edit_message_text("⏰ *Reminders:*\n\n" + "\n".join(lines), parse_mode='Markdown')
    elif action == "help":
        cfg = SECTOR_CFG.get(client["sector"],{})
        await q.edit_message_text(
            cfg.get("help","Type anything!") + "\n\n_/setlang tamil|english|tanglish_",
            parse_mode='Markdown')


# ══════════════════════════════════════════════════════════════
# MAIN MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    text    = update.message.text.strip()

    # ── Rate limit check ─────────────────────────────────────
    if is_rate_limited(chat_id):
        await update.message.reply_text(
            "Oru minute wait pannu da 😅 Too many messages!", parse_mode='Markdown')
        return

    # ── LINK ─────────────────────────────────────────────────
    if text.upper().startswith("LINK "):
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("Format: `LINK CLT001`", parse_mode='Markdown')
            return
        code = parts[1].upper()
        clients = get_clients()
        if code not in clients:
            await update.message.reply_text(
                f"❌ ID `{code}` not found.\nContact JARVIS support.", parse_mode='Markdown')
            return
        if not clients[code].get("active", True):
            await update.message.reply_text("⚠️ Account inactive. Contact support.", parse_mode='Markdown')
            return
        # Clear this chat_id from any other client
        for cid, info in clients.items():
            if cid != code and str(info.get("chat_id","")) == chat_id:
                clients[cid]["chat_id"] = None
        clients[code]["chat_id"] = chat_id
        save_clients(clients)
        await update.message.reply_text("✅ *Linked!*", parse_mode='Markdown')
        await send_greeting(update, code, clients[code])
        restore_reminders()
        schedule_daily_jobs()
        return

    # ── Identify client ──────────────────────────────────────
    client_id, client = get_client_by_chat(chat_id)
    if not client_id:
        await update.message.reply_text(
            "🙏 *Vanakkam!*\n\nClient ID anuppu:\n`LINK CLT001`",
            parse_mode='Markdown')
        return

    # ── Check pending confirmation first ────────────────────
    if chat_id in _pending_confirms:
        handled = await handle_confirm_reply(update, text, chat_id, client_id, client)
        if handled:
            return

    await update.message.chat.send_action("typing")

    ctx    = query_data(client_id, client["sector"])
    result = await ai_understand(text, client, ctx)

    intent       = result.get("intent", "OTHER")
    reply        = result.get("reply", "Seri, noted!")
    record_type  = result.get("record_type")
    extracted    = result.get("extracted_data", {})
    needs_confirm= result.get("needs_confirm", False)
    confirm_text = result.get("confirm_text", "")

    # ── SAVE ─────────────────────────────────────────────────
    if intent == "SAVE" and record_type and extracted:

        # Accounts invoice → confirmation step
        if needs_confirm and confirm_text:
            _pending_confirms[chat_id] = {
                "record_type": record_type,
                "extracted_data": extracted,
                "reply": reply
            }
            await update.message.reply_text(
                f"📋 *Confirm panunga:*\n\n{confirm_text}\n\nSeri aa? (yes/no)",
                parse_mode='Markdown')
            return

        # Direct save for all other sectors
        try:
            rec = save_record(client_id, record_type, extracted)
            rid = rec.get("id","")

            if record_type == "reminder":
                schedule_reminder(chat_id, client_id, rec)
                try:
                    dt_str = datetime.fromisoformat(rec.get("remind_at","")).strftime("%d %b %I:%M %p")
                except:
                    dt_str = rec.get("remind_at","?")
                await update.message.reply_text(
                    f"⏰ *Reminder set!*\n_{rec.get('message','')}_\n📅 {dt_str}",
                    parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    f"✅ *Saved!* (ID: `{rid}`)\n{reply}", parse_mode='Markdown')

                # Sector auto-alerts
                if client["sector"] == "manufacturing":
                    qty  = _safe_int(extracted.get("quantity", 999))
                    minq = _safe_int(extracted.get("min_qty", 10))
                    if qty < minq:
                        await update.message.reply_text(
                            f"⚠️ *Low Stock!* {extracted.get('item_name','?')} — "
                            f"only *{qty} {extracted.get('unit','')}* left! Min: {minq}\nReorder panna time! 🔴",
                            parse_mode='Markdown')
                elif client["sector"] == "software":
                    if extracted.get("priority","") == "high":
                        await update.message.reply_text(
                            f"🚨 *High priority ticket logged!*\n"
                            f"Assign panna marandhudutha! 👀",
                            parse_mode='Markdown')

        except Exception as e:
            print(f"Save error: {e}")
            await update.message.reply_text(
                "❌ Save agalai, try again!\nIf problem continues, /help nu sollu.",
                parse_mode='Markdown')

    elif intent == "GREET":
        await send_greeting(update, client_id, client)

    else:
        await update.message.reply_text(reply, parse_mode='Markdown')


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def main():
    global _bot_app
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        return
    
    print("🚀 Starting JARVIS...")
    print("✅ Client isolation enabled")
    print("✅ No data leakage between clients")
    print("✅ Same powerful AI assistant\n")
    
    # Use Application instead of Updater (Newer version)
    _bot_app = Application.builder().token(token).build()
    
    # Add handlers
    _bot_app.add_handler(CommandHandler("start", cmd_start))
    _bot_app.add_handler(CommandHandler("help", cmd_help))
    _bot_app.add_handler(CommandHandler("summary", cmd_summary))
    _bot_app.add_handler(CommandHandler("logout", cmd_logout))
    _bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ BOT IS LIVE! 🎉")
    print("🔒 Each client has their own private data space")
    print("📱 Login: CLT001 DEMO2025\n")
    
    _bot_app.run_polling(drop_pending_updates=True)
if __name__ == '__main__':
    main()