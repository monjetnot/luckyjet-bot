"""
bot.py — Bot Telegram LuckyJet avec collecte automatique des cotes via scraper
"""
import os
import json
import asyncio
import logging
import statistics
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from scraper import LuckyJetScraper

# ── CONFIG ───────────────────────────────────────────────────────────────────
TOKEN        = os.getenv("TELEGRAM_TOKEN", "REMPLACE_PAR_TON_TOKEN")
ALERT_CHAT   = os.getenv("ALERT_CHAT_ID", "")   # Ton chat_id pour les alertes auto
DATA_FILE    = "history.json"
MIN_COTES_ANALYSE = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── PERSISTANCE ──────────────────────────────────────────────────────────────
def load_history() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"global": [], "subscribers": []}

def save_history(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_cote_global(cote: float):
    data = load_history()
    data.setdefault("global", [])
    data["global"].append({"cote": cote, "ts": datetime.now().isoformat()})
    data["global"] = data["global"][-500:]   # max 500
    save_history(data)
    return data["global"]

def get_subscribers() -> list:
    return load_history().get("subscribers", [])

def subscribe(chat_id: str):
    data = load_history()
    data.setdefault("subscribers", [])
    if chat_id not in data["subscribers"]:
        data["subscribers"].append(chat_id)
        save_history(data)

def unsubscribe(chat_id: str):
    data = load_history()
    data["subscribers"] = [s for s in data.get("subscribers", []) if s != chat_id]
    save_history(data)

# ── ANALYSE ──────────────────────────────────────────────────────────────────
def analyse(history: list, last_n: int = 30) -> dict | None:
    if len(history) < MIN_COTES_ANALYSE:
        return None
    cotes   = [e["cote"] for e in history]
    recent  = cotes[-last_n:]

    def pct_above(vals, t):
        return round(sum(1 for x in vals if x >= t) / len(vals) * 100, 1)

    tranches     = [1.2, 1.5, 2.0, 3.0, 5.0]
    freq_recent  = {f"{t}x": pct_above(recent, t) for t in tranches}
    freq_global  = {f"{t}x": pct_above(cotes,  t) for t in tranches}

    tranche_sure = 1.2
    for t in tranches:
        if freq_recent.get(f"{t}x", 0) >= 70:
            tranche_sure = t

    std  = statistics.stdev(recent) if len(recent) >= 2 else 99
    mean = statistics.mean(recent)
    cv   = (std / mean) * 100 if mean else 100

    if   cv < 30: confiance, conf_pct = "🟢 Élevée",  min(85, round(90 - cv))
    elif cv < 60: confiance, conf_pct = "🟡 Modérée", min(70, round(75 - cv / 2))
    else:         confiance, conf_pct = "🔴 Faible",  max(25, round(55 - cv / 3))

    streak_low = 0
    for e in reversed(history):
        if e["cote"] < 2.0: streak_low += 1
        else: break

    return {
        "total":        len(cotes),
        "recent_n":     len(recent),
        "moyenne":      round(mean, 2),
        "mediane":      round(statistics.median(recent), 2),
        "min":          round(min(recent), 2),
        "max":          round(max(recent), 2),
        "freq_recent":  freq_recent,
        "freq_global":  freq_global,
        "tranche_sure": tranche_sure,
        "confiance":    confiance,
        "conf_pct":     conf_pct,
        "streak_low":   streak_low,
        "derniere":     round(cotes[-1], 2),
    }

def format_rapport(stats: dict) -> str:
    fr = stats["freq_recent"]
    fg = stats["freq_global"]
    alerte = f"\n⚠️ *ALERTE* : {stats['streak_low']} tours consécutifs < 2x !\n" \
             if stats["streak_low"] >= 4 else ""
    return (
        f"╔══════════════════════════╗\n"
        f"║  📊 *ANALYSE LUCKY JET*\n"
        f"╚══════════════════════════╝\n\n"
        f"🔄 Dernière cote : *{stats['derniere']}x*\n"
        f"📦 Données : *{stats['total']}* cotes _(analyse {stats['recent_n']} récentes)_\n"
        f"{alerte}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *STATISTIQUES RÉCENTES*\n"
        f"• Moyenne  : *{stats['moyenne']}x*\n"
        f"• Médiane  : *{stats['mediane']}x*\n"
        f"• Min / Max : {stats['min']}x → {stats['max']}x\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *FRÉQUENCES*\n"
        f"Cote   | Récent | Global\n"
        f"≥1.2x  | {fr.get('1.2x',0):5}% | {fg.get('1.2x',0):5}%\n"
        f"≥1.5x  | {fr.get('1.5x',0):5}% | {fg.get('1.5x',0):5}%\n"
        f"≥2.0x  | {fr.get('2.0x',0):5}% | {fg.get('2.0x',0):5}%\n"
        f"≥3.0x  | {fr.get('3.0x',0):5}% | {fg.get('3.0x',0):5}%\n"
        f"≥5.0x  | {fr.get('5.0x',0):5}% | {fg.get('5.0x',0):5}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *RECOMMANDATION*\n"
        f"• Tranche sécuritaire : *{stats['tranche_sure']}x*\n"
        f"• Confiance : {stats['confiance']} (*{stats['conf_pct']}%*)\n\n"
        f"_⚠️ Basé sur l'historique capturé automatiquement._"
    )

# ── BOT HANDLERS ─────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    subscribe(chat_id)
    keyboard = [
        [InlineKeyboardButton("📊 Analyse",       callback_data="analyse"),
         InlineKeyboardButton("📜 Historique",    callback_data="historique")],
        [InlineKeyboardButton("🔔 S'abonner",     callback_data="subscribe"),
         InlineKeyboardButton("🔕 Se désabonner", callback_data="unsubscribe")],
        [InlineKeyboardButton("🆔 Mon Chat ID",   callback_data="myid")],
    ]
    await update.message.reply_text(
        "🚀 *Bot Lucky Jet — Collecte Automatique*\n\n"
        "✅ Les cotes sont collectées *automatiquement* depuis 1win.\n\n"
        "📌 *Commandes :*\n"
        "• `/analyse` → analyse + recommandation\n"
        "• `/history` → 15 dernières cotes\n"
        "• `/subscribe` → alertes automatiques après chaque tour\n"
        "• `/myid` → ton Chat ID (pour la config)\n\n"
        "_Tu es automatiquement abonné aux alertes._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_analyse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history = load_history().get("global", [])
    if len(history) < MIN_COTES_ANALYSE:
        await update.message.reply_text(
            f"⏳ Collecte en cours... ({len(history)}/{MIN_COTES_ANALYSE} cotes)\n"
            "Reviens dans quelques instants.",
            parse_mode="Markdown"
        )
        return
    stats = analyse(history)
    await update.message.reply_text(format_rapport(stats), parse_mode="Markdown")

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history = load_history().get("global", [])
    if not history:
        await update.message.reply_text("⏳ Aucune cote collectée pour l'instant.")
        return
    last = history[-15:]
    lines = [f"`{round(e['cote'],2):5}x`  {e['ts'][11:19]}"
             for e in reversed(last)]
    await update.message.reply_text(
        f"📜 *15 dernières cotes collectées :*\n" + "\n".join(lines),
        parse_mode="Markdown"
    )

async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    subscribe(str(update.effective_chat.id))
    await update.message.reply_text("🔔 Abonné ! Tu recevras une analyse après chaque tour.")

async def cmd_unsubscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    unsubscribe(str(update.effective_chat.id))
    await update.message.reply_text("🔕 Désabonné. Utilise /analyse pour les rapports manuels.")

async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Ton Chat ID : `{update.effective_chat.id}`",
        parse_mode="Markdown"
    )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.from_user.id)

    if query.data == "analyse":
        history = load_history().get("global", [])
        if len(history) < MIN_COTES_ANALYSE:
            await query.edit_message_text(
                f"⏳ Collecte en cours... ({len(history)}/{MIN_COTES_ANALYSE} cotes)\n"
                "Reviens dans quelques instants."
            )
        else:
            await query.edit_message_text(
                format_rapport(analyse(history)), parse_mode="Markdown"
            )

    elif query.data == "historique":
        history = load_history().get("global", [])
        if not history:
            await query.edit_message_text("⏳ Aucune cote encore.")
        else:
            last = history[-15:]
            lines = [f"`{round(e['cote'],2):5}x`  {e['ts'][11:19]}"
                     for e in reversed(last)]
            await query.edit_message_text(
                "📜 *15 dernières cotes :*\n" + "\n".join(lines),
                parse_mode="Markdown"
            )

    elif query.data == "subscribe":
        subscribe(chat_id)
        await query.edit_message_text("🔔 Abonné aux alertes automatiques !")

    elif query.data == "unsubscribe":
        unsubscribe(chat_id)
        await query.edit_message_text("🔕 Désabonné.")

    elif query.data == "myid":
        await query.edit_message_text(
            f"🆔 Ton Chat ID : `{chat_id}`", parse_mode="Markdown"
        )

# ── CALLBACK DU SCRAPER ──────────────────────────────────────────────────────
def make_scraper_callback(app: Application):
    """Crée la fonction callback appelée à chaque nouvelle cote capturée."""
    counter = {"n": 0}

    async def on_new_cote(cote: float):
        history = add_cote_global(cote)
        counter["n"] += 1

        # Envoie une analyse tous les 5 tours aux abonnés
        if counter["n"] % 5 == 0:
            stats = analyse(history)
            if not stats:
                return
            msg = f"🔔 *Mise à jour automatique* (tour #{counter['n']})\n\n" \
                  + format_rapport(stats)
            subs = get_subscribers()
            for chat_id in subs:
                try:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.warning(f"Envoi échoué pour {chat_id}: {e}")

    return on_new_cote

# ── MAIN ─────────────────────────────────────────────────────────────────────
async def run_bot_and_scraper():
    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # Handlers
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("analyse",     cmd_analyse))
    app.add_handler(CommandHandler("history",     cmd_history))
    app.add_handler(CommandHandler("subscribe",   cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("myid",        cmd_myid))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Initialise l'app Telegram
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    logger.info("✅ Bot Telegram démarré")

    # Lance le scraper en parallèle
    callback = make_scraper_callback(app)
    scraper  = LuckyJetScraper(on_new_cote_callback=callback)

    try:
        await scraper.start()
    except Exception as e:
        logger.error(f"Erreur scraper: {e}")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(run_bot_and_scraper())
