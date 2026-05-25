import gspread
from google.oauth2.service_account import Credentials

print("🔍 Testing Google Sheets Connection...")

try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
    print("✅ Credentials loaded")
    
    gc = gspread.authorize(creds)
    print("✅ Authorized")
    
    sheet = gc.open("Jarvis_Memory").sheet1
    print("✅ Sheet opened")
    
    sheet.append_row(["TEST", "Connection", "Successful"])
    print("✅✅✅ SHEETS CONNECTION SUCCESSFUL! Check your Google Sheet.")
    
except Exception as e:
    print(f"❌❌❌ ERROR: {e}")