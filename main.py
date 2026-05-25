import os
import re
from datetime import datetime
from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# ---------------- CONFIGURATION ----------------
load_dotenv()
GROQ_KEY = os.getenv("GROQ_API_KEY")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_ID = int(os.getenv("YOUR_CHAT_ID", "0"))

SECTORS = {
    "realestate": {"sheet": "RealEstate", "prompt": "prompts/real_estate.txt"},
    "manufacturing": {"sheet": "Manufacturing", "prompt": "prompts/manufacturing.txt"},
    "accounts": {"sheet": "Accounts", "prompt": "prompts/accounts.txt"},
    "software": {"sheet": "Software", "prompt": "prompts/software.txt"},
}

DEFAULT_SECTOR = "realestate"

client = Groq(api_key=GROQ_KEY)

# ---------------- DATABASE HANDLER ----------------
def get_sheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
    return gspread.authorize(creds)

def save_to_sheet(sector_key, data_row):
    try:
        gc = get_sheet_client()
        sheet_name = SECTORS[sector_key]["sheet"]
        try:
            worksheet = gc.open("Jarvis_Memory").worksheet(sheet_name)
        except:
            worksheet = gc.open("Jarvis_Memory").add_worksheet(title=sheet_name, rows=100, cols=10)
        
        worksheet.append_row(data_row)
        return True
    except Exception as e:
        print(f"Sheet Error: {e}")
        return False

def save_log(user, text, response):
    try:
        gc = get_sheet_client()
        worksheet = gc.open("Jarvis_Memory").worksheet("Logs")
        worksheet.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, text, response])
    except:
        pass

# ---------------- AI LOGIC ----------------
def get_prompt(sector_key):
    try:
        with open(SECTORS[sector_key]["prompt"], "r") as f:
            return f.read()
    except:
        return "You are a helpful assistant."

def process_with_ai(sector_key, user_text):
    system_prompt = get_prompt(sector_key)
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI Error: {str(e)}"

# ---------------- DATA EXTRACTOR (PYTHON, NOT AI) ----------------
def extract_data(sector_key, user_text):
    """Extract data using Python regex - MORE RELIABLE THAN AI"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    if sector_key == "realestate":
        # Extract: Name, Phone, Budget, Location
        name = re.search(r'(?:name|lead)[:\s]+([a-zA-Z\s]+)', user_text, re.I)
        phone = re.search(r'(\d{10})', user_text)
        budget = re.search(r'(\d+[LMK]|\d+L|\d+Cr)', user_text, re.I)
        location = re.search(r'(?:location|place|area)[:\s]+([a-zA-Z\s]+)', user_text, re.I)
        
        return [
            today,
            name.group(1).strip() if name else "Unknown",
            phone.group(1) if phone else "Unknown",
            budget.group(1) if budget else "Unknown",
            location.group(1).strip() if location else "Unknown",
            "New Lead"
        ]
    
    elif sector_key == "manufacturing":
        # Extract: Item, Qty, Threshold
        item = re.search(r'(?:item|stock|material)[:\s]+([a-zA-Z\s]+)', user_text, re.I)
        qty = re.search(r'(?:qty|quantity)[:\s]+(\d+)', user_text, re.I)
        threshold = re.search(r'(?:threshold|min)[:\s]+(\d+)', user_text, re.I)
        
        qty_val = int(qty.group(1)) if qty else 0
        thresh_val = int(threshold.group(1)) if threshold else 100
        status = "LOW STOCK ALERT" if qty_val < thresh_val else "OK"
        
        return [
            today,
            item.group(1).strip() if item else "Unknown",
            str(qty_val),
            str(thresh_val),
            status
        ]
    
    elif sector_key == "accounts":
        # Extract: Client, InvID, Amount
        client = re.search(r'(?:client|company)[:\s]+([a-zA-Z\s]+)', user_text, re.I)
        inv_id = re.search(r'(?:inv|invoice)[:\s]*([a-zA-Z0-9]+)', user_text, re.I)
        amount = re.search(r'(\d+)', user_text)
        
        amt = int(amount.group(1)) if amount else 0
        gst = int(amt * 0.18)
        total = amt + gst
        
        return [
            today,
            client.group(1).strip() if client else "Unknown",
            inv_id.group(1) if inv_id else "INV001",
            str(amt),
            str(gst),
            str(total),
            "Pending"
        ]
    
    elif sector_key == "software":
        # Extract: Client, Bug, Priority
        client = re.search(r'(?:client|company)[:\s]+([a-zA-Z\s]+)', user_text, re.I)
        bug = re.search(r'(?:bug|issue|problem)[:\s]+([a-zA-Z\s]+)', user_text, re.I)
        priority = re.search(r'(high|medium|low)', user_text, re.I)
        ticket_id = f"#TKT{datetime.now().strftime('%H%M%S')}"
        
        return [
            today,
            ticket_id,
            client.group(1).strip() if client else "Unknown",
            bug.group(1).strip() if bug else "General Issue",
            priority.group(1).upper() if priority else "MEDIUM",
            "Open"
        ]
    
    return []

# ---------------- TELEGRAM HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Jarvis Multi-Agent Online.\n"
        f"Current Mode: {context.user_data.get('sector', DEFAULT_SECTOR).upper()}\n"
        "Commands:\n"
        "/sector [name] - Switch mode\n"
        "/task [text] - Save task"
    )

async def set_sector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sector = context.args[0].lower() if context.args else DEFAULT_SECTOR
    if sector in SECTORS:
        context.user_data['sector'] = sector
        await update.message.reply_text(f"✅ Switched to {sector.upper()} Agent Mode.")
    else:
        await update.message.reply_text(f"❌ Invalid sector. Choose: {', '.join(SECTORS.keys())}")

async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_text = " ".join(context.args)
    if not task_text:
        await update.message.reply_text("Usage: /task [your task]")
        return
    try:
        gc = get_sheet_client()
        ws = gc.open("Jarvis_Memory").worksheet("Tasks")
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_text, "Pending"])
        await update.message.reply_text(f"✅ Task Saved: {task_text}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_id = update.message.chat_id
    
    if user_id != MY_ID:
        return

    await update.message.chat.send_action(action="typing")
    
    sector = context.user_data.get('sector', DEFAULT_SECTOR)
    
    # Get AI Response (for conversation)
    ai_response = process_with_ai(sector, user_text)
    
    # Save to Logs (always)
    save_log(user_id, user_text, ai_response)
    
    # Extract Data Using Python (RELIABLE)
    data_row = extract_data(sector, user_text)
    
    # Save to Sector Sheet
    if data_row:
        save_success = save_to_sheet(sector, data_row)
        if save_success:
            await update.message.reply_text(f"✅ {sector.upper()} DATA SAVED TO SHEET!\n\n📝 AI: {ai_response}")
        else:
            await update.message.reply_text(f"⚠️ AI: {ai_response}\n(Sheet save failed)")
    else:
        await update.message.reply_text(f"📝 {ai_response}")

# ---------------- RUN ----------------
def main():
    app = Application.builder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sector", set_sector))
    app.add_handler(CommandHandler("task", add_task))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🚀 Jarvis Multi-Agent System Initializing...")
    app.run_polling()

if __name__ == '__main__':
    main()