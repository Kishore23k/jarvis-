"""
JARVIS - Streamlit Dashboard (app.py)
Run from the project folder: streamlit run dashboard/app.py
OR from inside dashboard folder: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime

# ═══════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════
st.set_page_config(page_title="JARVIS Dashboard", page_icon="🤖", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] { background: #0d0d1a; }
[data-testid="stSidebar"] * { color: #d0d0ff !important; }
.block-container { padding: 0 !important; }
#MainMenu, footer { visibility: hidden; }

.m-card {
    background: #111128; border: 1px solid #222250;
    border-radius: 10px; padding: 1rem 1.2rem;
    text-align: center; margin-bottom: 0;
}
.m-label { font-size: 0.72rem; color: #666699; text-transform: uppercase; letter-spacing: 1px; }
.m-value { font-size: 1.9rem; font-weight: 700; line-height: 1.2; }
.m-sub   { font-size: 0.78rem; color: #44446a; margin-top: 2px; }
.c-blue  .m-value { color: #4fc3f7; }
.c-green .m-value { color: #81c784; }
.c-amber .m-value { color: #ffb74d; }
.c-red   .m-value { color: #ef5350; }
.c-purple .m-value { color: #ce93d8; }

.sec-header {
    padding: 1.4rem 2rem 0.8rem;
    border-bottom: 1px solid #1a1a3a;
    margin-bottom: 1.2rem;
}
.sec-header h1 { margin: 0; font-size: 1.7rem; }
.sec-header p  { margin: 3px 0 0; color: #666699; font-size: 0.85rem; }

.stTextInput > div > div > input,
.stSelectbox > div > div > div {
    background: #111128 !important;
    color: #fff !important;
    border: 1px solid #222250 !important;
    border-radius: 7px !important;
}
.stButton > button {
    background: #1a1a3a !important; color: #d0d0ff !important;
    border: 1px solid #333366 !important; border-radius: 7px !important;
}
.stButton > button:hover { background: #2a2a5a !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════
# PATH — find clients.json from any working dir
# ═══════════════════════════════════════════
def _find_data_file():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "clients.json"),           # same folder
        os.path.join(here, "..", "clients.json"),      # parent folder (Jarvis_Core/)
        os.path.join(here, "..", "..", "clients.json"),# grandparent
        "/Users/apple/Documents/projects/Jarvis_Core/clients.json",  # absolute
    ]
    for p in candidates:
        if os.path.exists(p):
            return os.path.abspath(p)
    return None

DATA_PATH = _find_data_file()

def load_all():
    """Always reads fresh from disk — no caching."""
    if not DATA_PATH:
        return {"clients": {}}
    try:
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"clients": {}}

def save_all(data: dict):
    if not DATA_PATH:
        return
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def client_data(client_id: str) -> dict:
    """Returns data dict, always with all keys present."""
    all_d = load_all()
    cl = all_d['clients'].get(client_id, {})
    data = cl.get("data", {})
    # Ensure all keys exist regardless of sector
    data.setdefault("leads", [])
    data.setdefault("stock", [])
    data.setdefault("invoices", [])
    data.setdefault("tickets", [])
    data.setdefault("reminders", [])
    data.setdefault("contacts", [])
    return data

def add_record(client_id: str, rtype: str, fields: dict):
    all_d = load_all()
    cl = all_d['clients'][client_id]
    if "data" not in cl:
        cl["data"] = {"leads": [], "stock": [], "invoices": [], "tickets": []}
    key = {"lead":"leads","stock":"stock","invoice":"invoices","ticket":"tickets"}.get(rtype, rtype+"s")
    rec = {"id": f"{rtype[:3].upper()}{datetime.now().strftime('%m%d%H%M%S')}",
           "timestamp": datetime.now().isoformat(), **fields}
    cl["data"].setdefault(key, []).append(rec)
    all_d['clients'][client_id] = cl
    save_all(all_d)


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════
def mcard(label, value, sub="", color=""):
    return (f'<div class="m-card {color}">'
            f'<div class="m-label">{label}</div>'
            f'<div class="m-value">{value}</div>'
            + (f'<div class="m-sub">{sub}</div>' if sub else '') +
            '</div>')

def show_df(rows, cols_order=None):
    if not rows:
        st.info("📭 No records yet. Add via Telegram bot or the form below.")
        return
    df = pd.DataFrame(rows)
    if cols_order:
        existing = [c for c in cols_order if c in df.columns]
        df = df[existing]
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%d %b %H:%M")
    st.dataframe(df, use_container_width=True, hide_index=True)

def safe_int(v, d=0):
    try: return int(str(v).replace(",","").strip())
    except: return d

def safe_float(v, d=0.0):
    try: return float(str(v).replace("₹","").replace(",","").strip())
    except: return d


# ═══════════════════════════════════════════
# LOGIN
# ═══════════════════════════════════════════
def show_login():
    _, col, _ = st.columns([1, 1.4, 1])
    with col:
        st.markdown("""
        <div style='text-align:center;padding:3rem 0 1.5rem'>
            <div style='font-size:3rem'>🤖</div>
            <h1 style='font-size:2.2rem;letter-spacing:4px;color:#4fc3f7;margin:0'>JARVIS</h1>
            <p style='color:#556;margin-top:4px;font-size:0.9rem'>Business Automation · Tamil Nadu</p>
        </div>""", unsafe_allow_html=True)

        if DATA_PATH is None:
            st.error("❌ clients.json not found! Place it in the same folder as app.py.")
            st.code("Jarvis_Core/\n  ├── app.py\n  ├── main.py\n  └── clients.json")
            return

        with st.form("login"):
            cid = st.text_input("Client ID", placeholder="CLT001")
            pw  = st.text_input("Password", type="password", placeholder="Password")
            c1, c2 = st.columns(2)
            login = c1.form_submit_button("🚀 Login", use_container_width=True)
            demo  = c2.form_submit_button("👀 Demo", use_container_width=True)

            if demo:
                cid, pw, login = "CLT001", "DEMO2025", True

            if login:
                all_d = load_all()
                uid = cid.strip().upper()
                if uid in all_d.get('clients', {}):
                    cl = all_d['clients'][uid]
                    if cl.get('password','').upper() == pw.strip().upper():
                        if cl.get('active', True):
                            st.session_state.update(logged_in=True, client_id=uid)
                            st.rerun()
                        else:
                            st.error("Account inactive. Contact JARVIS support.")
                    else:
                        st.error("❌ Wrong password!")
                else:
                    st.error(f"❌ ID '{cid}' not found!")

        st.markdown("<div style='text-align:center;color:#444;font-size:0.8rem;margin-top:2rem'>"
                    "Need help? Contact your JARVIS representative</div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════
def show_sidebar(cl: dict):
    emojis = {"realestate":"🏠","manufacturing":"🏭","accounts":"💰","software":"💻"}
    sec = cl.get('sector','')
    with st.sidebar:
        st.markdown(f"""
        <div style='padding:.8rem 0 1rem;border-bottom:1px solid #1e1e3a;margin-bottom:.8rem'>
            <div style='font-size:1.6rem'>{emojis.get(sec,'🤖')}</div>
            <div style='font-size:1rem;font-weight:700;margin-top:4px'>{cl['name']}</div>
            <div style='font-size:0.78rem;opacity:.5'>{cl['owner']}</div>
        </div>""", unsafe_allow_html=True)

        plan = cl.get('plan','trial').upper()
        pc = "#4fc3f7" if plan=="PRO" else "#ffb74d"
        st.markdown(f"<div style='background:#0d0d2a;border-radius:7px;padding:7px 12px;"
                    f"margin-bottom:.8rem;font-size:.8rem;display:flex;justify-content:space-between'>"
                    f"<span>Plan</span><span style='color:{pc};font-weight:700'>{plan}</span></div>",
                    unsafe_allow_html=True)

        st.markdown(f"<div style='font-size:.75rem;color:#446;padding:4px 4px 12px'>"
                    f"Sector: {sec.upper()}</div>", unsafe_allow_html=True)

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()
        if st.button("🚪 Logout", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.markdown("---")
        st.markdown(
            f"<div style='font-size:.72rem;color:#445;padding:4px'>"
            f"🕐 <b style='color:#667'>Last loaded:</b><br>"
            f"{datetime.now().strftime('%I:%M:%S %p')}</div>",
            unsafe_allow_html=True)
        st.markdown("<div style='font-size:.72rem;color:#445;padding:4px;margin-top:6px'>"
                    "📱 <b style='color:#667'>Telegram bot:</b><br>"
                    "Type naturally in Tamil or English!</div>", unsafe_allow_html=True)

        trial = cl.get('trial_end','')
        if trial and plan == 'TRIAL':
            try:
                d = (datetime.strptime(trial,'%Y-%m-%d') - datetime.now()).days
                c = "#ef5350" if d < 7 else "#ffb74d"
                st.markdown(f"<div style='color:{c};font-size:.78rem;margin-top:.8rem;"
                            f"padding:5px 10px;background:#1a0d0d;border-radius:6px'>"
                            f"⏳ {d} days trial left</div>", unsafe_allow_html=True)
            except:
                pass


# ═══════════════════════════════════════════
# SECTOR DASHBOARDS
# ═══════════════════════════════════════════

# ── Real Estate ────────────────────────────
def dash_realestate(cid: str, cl: dict):
    data  = client_data(cid)
    leads = data.get("leads", [])
    buyers  = [l for l in leads if l.get("type") == "buy"]
    sellers = [l for l in leads if l.get("type") == "sell"]
    renters = [l for l in leads if l.get("type") == "rent"]

    st.markdown('<div class="sec-header">'
                '<h1 style="color:#4fc3f7">🏠 Real Estate Dashboard</h1>'
                '<p>Property Lead Management</p></div>', unsafe_allow_html=True)

    with st.container():
        c1,c2,c3,c4 = st.columns(4)
        c1.markdown(mcard("Total Leads", len(leads), "all time", "c-blue"), unsafe_allow_html=True)
        c2.markdown(mcard("Buyers", len(buyers), "want to buy", "c-green"), unsafe_allow_html=True)
        c3.markdown(mcard("Sellers", len(sellers), "listing property", "c-amber"), unsafe_allow_html=True)
        c4.markdown(mcard("Renters", len(renters), "looking to rent"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    t1,t2,t3,t4 = st.tabs(["🗂️ All","🛒 Buyers","💰 Sellers","🔑 Renters"])
    cols = ["id","name","phone","type","budget","location","property_type","timestamp"]
    with t1: show_df(leads, cols)
    with t2: show_df(buyers, cols)
    with t3: show_df(sellers, cols)
    with t4: show_df(renters, cols)

    st.markdown("---")
    st.markdown("#### ➕ Quick Add Lead")
    with st.form("f_lead"):
        a,b,c = st.columns(3)
        name  = a.text_input("Name")
        phone = a.text_input("Phone")
        ltype = b.selectbox("Type", ["buy","sell","rent"])
        budget= b.text_input("Budget (e.g. 45L)")
        loc   = c.text_input("Location")
        ptype = c.text_input("Property Type")
        if st.form_submit_button("💾 Save Lead", use_container_width=True):
            if name and phone:
                add_record(cid, "lead", {"name":name,"phone":phone,"type":ltype,
                                          "budget":budget,"location":loc,"property_type":ptype})
                st.success("✅ Lead saved!"); st.rerun()
            else:
                st.warning("Name and Phone are required.")


# ── Manufacturing ──────────────────────────
def dash_manufacturing(cid: str, cl: dict):
    data  = client_data(cid)
    stock = data.get("stock", [])
    low   = [s for s in stock if safe_int(s.get("quantity",0)) < safe_int(s.get("min_qty",10))]
    ok    = [s for s in stock if safe_int(s.get("quantity",999)) >= safe_int(s.get("min_qty",10))]
    cats  = len(set(s.get("category","—") for s in stock))

    st.markdown('<div class="sec-header">'
                '<h1 style="color:#81c784">🏭 Manufacturing Dashboard</h1>'
                '<p>Stock & Inventory Management</p></div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(mcard("Total Items", len(stock), "in inventory", "c-blue"), unsafe_allow_html=True)
    c2.markdown(mcard("Low Stock",   len(low),   "need reorder", "c-red"),  unsafe_allow_html=True)
    c3.markdown(mcard("OK Items",    len(ok),    "sufficient",   "c-green"),unsafe_allow_html=True)
    c4.markdown(mcard("Categories",  cats,       "product types"),          unsafe_allow_html=True)

    if low:
        st.error(f"🚨 **{len(low)} items below minimum stock!**")

    st.markdown("<br>", unsafe_allow_html=True)
    t1,t2 = st.tabs(["📦 All Stock","⚠️ Low Stock"])
    scols = ["id","item_name","quantity","unit","min_qty","category","price","timestamp"]
    with t1: show_df(stock, scols)
    with t2: show_df(low,   scols)

    st.markdown("---")
    st.markdown("#### ➕ Add Stock Item")
    with st.form("f_stock"):
        a,b,c = st.columns(3)
        iname = a.text_input("Item Name")
        qty   = a.number_input("Quantity", min_value=0, step=1)
        unit  = b.text_input("Unit (kg/pcs/liters)", value="pcs")
        minq  = b.number_input("Min Qty (reorder level)", min_value=0, step=1)
        cat   = c.text_input("Category")
        price = c.text_input("Unit Price (₹)")
        if st.form_submit_button("💾 Save Item", use_container_width=True):
            if iname:
                add_record(cid, "stock", {"item_name":iname,"quantity":qty,"unit":unit,
                                           "min_qty":minq,"category":cat,"price":price})
                st.success("✅ Item saved!"); st.rerun()
            else:
                st.warning("Item name is required.")


# ── Accounts ───────────────────────────────
def dash_accounts(cid: str, cl: dict):
    data = client_data(cid)
    inv  = data.get("invoices", [])
    paid    = [i for i in inv if i.get("status") == "paid"]
    pending = [i for i in inv if i.get("status") != "paid"]
    revenue = sum(safe_float(i.get("amount",0)) for i in paid)
    pendamt = sum(safe_float(i.get("amount",0)) for i in pending)

    st.markdown('<div class="sec-header">'
                '<h1 style="color:#ffb74d">💰 Accounts Dashboard</h1>'
                '<p>Invoice & Payment Management</p></div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(mcard("Invoices",   len(inv),             "total",     "c-blue"),  unsafe_allow_html=True)
    c2.markdown(mcard("Revenue",    f"₹{revenue:,.0f}",   "collected", "c-green"), unsafe_allow_html=True)
    c3.markdown(mcard("Pending",    f"₹{pendamt:,.0f}",   f"{len(pending)} inv.", "c-amber"), unsafe_allow_html=True)
    c4.markdown(mcard("Paid",       len(paid),             "cleared",  "c-green"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    t1,t2,t3 = st.tabs(["🧾 All","⏳ Pending","✅ Paid"])
    icols = ["id","invoice_no","client_name","amount","gst_amount","status","date","timestamp"]
    with t1: show_df(inv,     icols)
    with t2: show_df(pending, icols)
    with t3: show_df(paid,    icols)

    st.markdown("---")
    st.markdown("#### ➕ New Invoice")
    with st.form("f_inv"):
        a,b,c = st.columns(3)
        invno  = a.text_input("Invoice No", placeholder="INV-001")
        cname  = a.text_input("Client Name")
        amount = b.text_input("Amount (₹)")
        gst    = b.text_input("GST (₹)")
        status = c.selectbox("Status", ["pending","paid","partial"])
        idate  = c.date_input("Date", value=datetime.today())
        if st.form_submit_button("💾 Save Invoice", use_container_width=True):
            if invno and cname:
                add_record(cid, "invoice", {"invoice_no":invno,"client_name":cname,
                                             "amount":amount,"gst_amount":gst,
                                             "status":status,"date":str(idate)})
                st.success("✅ Invoice saved!"); st.rerun()
            else:
                st.warning("Invoice No and Client Name are required.")


# ── Software / Tickets ─────────────────────
def dash_software(cid: str, cl: dict):
    data    = client_data(cid)
    tickets = data.get("tickets", [])
    open_t  = [t for t in tickets if t.get("status") == "open"]
    prog    = [t for t in tickets if t.get("status") == "progress"]
    done    = [t for t in tickets if t.get("status") == "resolved"]
    high    = [t for t in tickets if t.get("priority") == "high"]

    st.markdown('<div class="sec-header">'
                '<h1 style="color:#ce93d8">💻 Software Dashboard</h1>'
                '<p>Support Ticket Management</p></div>', unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.markdown(mcard("Total",        len(tickets), "all time",    "c-blue"),   unsafe_allow_html=True)
    c2.markdown(mcard("Open",         len(open_t),  "unresolved",  "c-red"),    unsafe_allow_html=True)
    c3.markdown(mcard("High Priority",len(high),    "urgent",      "c-amber"),  unsafe_allow_html=True)
    c4.markdown(mcard("Resolved",     len(done),    "closed",      "c-green"),  unsafe_allow_html=True)

    if high:
        st.error(f"🚨 **{len(high)} high priority tickets need attention!**")

    st.markdown("<br>", unsafe_allow_html=True)
    t1,t2,t3,t4 = st.tabs(["🎫 All","🔴 Open","🔧 In Progress","✅ Resolved"])
    tcols = ["id","title","client_name","priority","status","description","timestamp"]
    with t1: show_df(tickets, tcols)
    with t2: show_df(open_t,  tcols)
    with t3: show_df(prog,    tcols)
    with t4: show_df(done,    tcols)

    st.markdown("---")
    st.markdown("#### ➕ New Ticket")
    with st.form("f_ticket"):
        a,b = st.columns(2)
        title = a.text_input("Issue Title")
        cname = a.text_input("Client Name")
        prio  = b.selectbox("Priority", ["low","medium","high"])
        stat  = b.selectbox("Status",   ["open","progress","resolved"])
        desc  = st.text_area("Description", height=70)
        if st.form_submit_button("💾 Save Ticket", use_container_width=True):
            if title:
                add_record(cid, "ticket", {"title":title,"client_name":cname,
                                            "priority":prio,"status":stat,"description":desc})
                st.success("✅ Ticket saved!"); st.rerun()
            else:
                st.warning("Title is required.")


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
def main():
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        show_login()
        return

    cid = st.session_state.client_id
    all_d = load_all()  # always fresh from disk
    cl = all_d['clients'].get(cid, {})
    if not cl:
        st.error("Client data not found. Please login again.")
        st.session_state.logged_in = False
        st.rerun()

    show_sidebar(cl)

    sec = cl.get('sector','')
    if   sec == "realestate":    dash_realestate(cid, cl)
    elif sec == "manufacturing": dash_manufacturing(cid, cl)
    elif sec == "accounts":      dash_accounts(cid, cl)
    elif sec == "software":      dash_software(cid, cl)
    else:
        st.error(f"Unknown sector '{sec}'. Check clients.json.")

if __name__ == "__main__":
    main()