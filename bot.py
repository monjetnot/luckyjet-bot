import os
import json
import logging
import statistics
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

TOKEN     = os.getenv("TELEGRAM_TOKEN", "REMPLACE_PAR_TON_TOKEN")
DATA_FILE = "history.json"
MIN_COTES = 10

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── PERSISTANCE ──────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_history(user_id):
    return load_data().get(str(user_id), [])

def add_cote(user_id, cote):
    data = load_data()
    uid  = str(user_id)
    data.setdefault(uid, [])
    data[uid].append({"cote": cote, "ts": datetime.now().isoformat()})
    data[uid] = data[uid][-300:]
    save_data(data)
    return data[uid]

def clear_history(user_id):
    data = load_data()
    data[str(user_id)] = []
    save_data(data)

# ── ANALYSE ──────────────────────────────────────────────────────────────────
def analyse(history, last_n=30):
    if len(history) < MIN_COTES:
        return None
    cotes  = [e["cote"] for e in history]
    recent = cotes[-last_n:]

    def pct(vals, t):
        return round(sum(1 for x in vals if x >= t) / len(vals) * 100, 1)

    tranches    = [1.2, 1.5, 2.0, 3.0, 5.0]
    freq_recent = {f"{t}x": pct(recent, t) for t in tranches}
    freq_global = {f"{t}x": pct(cotes,  t) for t in tranches}

    tranche_sure = 1.2
    for t in tranches:
        if freq_recent.get(f"{t}x", 0) >= 70:
            tranche_sure = t

    std  = statistics.stdev(recent) if len(recent) >= 2 else 99
    mean = statistics.mean(recent)
    cv   = (std / mean * 100) if mean else 100

    if   cv < 30: conf_label, conf_pct = "🟢 Élevée",  min(85, round(90 - cv))
    elif cv < 60: conf_label, conf_pct = "🟡 Modérée", min(70, round(75 - cv/2))
    else:         conf_label, conf_pct = "🔴 Faible",  max(25, round(55 - cv/3))

    streak = 0
    for e in reversed(history):
        if e["cote"] < 2.0: streak += 1
        else: break

    return {
        "total": len(cotes), "n": len(recent),
        "moy": round(mean, 2), "med": round(statistics.median(recent), 2),
        "min": round(min(recent), 2), "max": round(max(recent), 2),
        "fr": freq_recent, "fg": freq_global,
        "tranche": tranche_sure,
        "conf_label": conf_label, "conf_pct": conf_pct,
        "streak": streak, "derniere": round(cotes[-1], 2),
    }

def signal_court(s):
    """Message court envoyé automatiquement après chaque cote."""
    alerte = "\n⚠️ *Série basse détectée !* Prudence." if s["streak"] >= 4 else ""
    return (
        f"🎯 *PROCHAIN TOUR*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"✅ Mise sécuritaire : *{s['tranche']}x*\n"
        f"📊 Confiance : {s['conf_label']} (*{s['conf_pct']}%*)\n"
        f"📈 Fréquence ≥{s['tranche']}x : *{s['fr'].get(str(s['tranche'])+'x', 0)}%* récent\n"
        f"🔢 Basé sur *{s['total']}* cotes{alerte}"
    )

def rapport_complet(s):
    fr, fg = s["fr"], s["fg"]
    alerte = f"\n⚠️ *ALERTE* : {s['streak']} tours consécutifs < 2x !\n" if s["streak"] >= 4 else ""
    return (
        f"╔══════════════════════════╗\n"
        f"║  📊 *ANALYSE LUCKY JET*\n"
        f"╚══════════════════════════╝\n\n"
        f"🔄 Dernière cote : *{s['derniere']}x*\n"
        f"📦 *{s['total']}* cotes _(analyse {s['n']} récentes)_\n"
        f"{alerte}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *STATISTIQUES*\n"
        f"• Moyenne : *{s['moy']}x* | Médiane : *{s['med']}x*\n"
        f"• Min : {s['min']}x | Max : {s['max']}x\n\n"
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
        f"• Tranche sécuritaire : *{s['tranche']}x*\n"
        f"• Confiance : {s['conf_label']} (*{s['conf_pct']}%*)\n\n"
        f"_⚠️ Basé sur ton historique personnel._"
    )

# ── HANDLERS ────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Analyse complète", callback_data="analyse"),
         InlineKeyboardButton("📜 Historique",        callback_data="historique")],
        [InlineKeyboardButton("🗑️ Effacer",           callback_data="clear")],
    ]
    h = get_history(update.effective_user.id)
    await update.message.reply_text(
        f"🚀 *Bot Lucky Jet*\n\n"
        f"📌 *Comment utiliser :*\n"
        f"• Tape la cote après chaque tour (ex: `2.35`)\n"
        f"• Le bot t'envoie *automatiquement* la recommandation\n"
        f"  pour le prochain tour !\n\n"
        f"📦 Cotes enregistrées : *{len(h)}*\n"
        f"_{MIN_COTES - len(h)} cotes de plus pour activer l'analyse_" if len(h) < MIN_COTES else
        f"📦 Cotes enregistrées : *{len(h)}* ✅",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_analyse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    h = get_history(update.effective_user.id)
    if len(h) < MIN_COTES:
        await update.message.reply_text(
            f"⏳ Besoin de *{MIN_COTES} cotes minimum* ({len(h)} enregistrées).",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(rapport_complet(analyse(h)), parse_mode="Markdown")

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    h = get_history(update.effective_user.id)
    if not h:
        await update.message.reply_text("Aucune cote. Tape un chiffre comme `2.35`", parse_mode="Markdown")
        return
    last  = h[-15:]
    lines = [f"`{e['cote']:5}x`  {e['ts'][11:19]}" for e in reversed(last)]
    await update.message.reply_text(
        f"📜 *{len(h)} cotes — 15 dernières :*\n" + "\n".join(lines),
        parse_mode="Markdown"
    )

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("✅ Oui", callback_data="do_clear"),
        InlineKeyboardButton("❌ Non", callback_data="cancel")
    ]]
    await update.message.reply_text(
        "⚠️ Supprimer tout l'historique ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "analyse":
        h = get_history(uid)
        if len(h) < MIN_COTES:
            await q.edit_message_text(
                f"⏳ Besoin de *{MIN_COTES} cotes* (tu en as {len(h)}).",
                parse_mode="Markdown"
            )
        else:
            await q.edit_message_text(rapport_complet(analyse(h)), parse_mode="Markdown")

    elif q.data == "historique":
        h = get_history(uid)
        if not h:
            await q.edit_message_text("Aucune cote enregistrée.")
        else:
            last  = h[-15:]
            lines = [f"`{e['cote']:5}x`  {e['ts'][11:19]}" for e in reversed(last)]
            await q.edit_message_text(
                f"📜 *{len(h)} cotes — 15 dernières :*\n" + "\n".join(lines),
                parse_mode="Markdown"
            )

    elif q.data == "clear":
        keyboard = [[
            InlineKeyboardButton("✅ Oui", callback_data="do_clear"),
            InlineKeyboardButton("❌ Non", callback_data="cancel")
        ]]
        await q.edit_message_text("⚠️ Confirmer ?", reply_markup=InlineKeyboardMarkup(keyboard))

    elif q.data == "do_clear":
        clear_history(uid)
        await q.edit_message_text("🗑️ Historique effacé.")

    elif q.data == "cancel":
        await q.edit_message_text("✅ Annulé.")

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reçoit une cote, l'enregistre et envoie automatiquement le signal."""
    text = update.message.text.strip().replace(",", ".")
    try:
        cote = float(text)
        if 1.0 <= cote <= 200:
            h = add_cote(update.effective_user.id, cote)
            n = len(h)

            if n < MIN_COTES:
                # Pas encore assez de données
                await update.message.reply_text(
                    f"✅ *{cote}x* enregistré — *{n}/{MIN_COTES}*\n"
                    f"_{MIN_COTES - n} cotes de plus pour activer les signaux_",
                    parse_mode="Markdown"
                )
            else:
                # ✅ Envoie le signal automatiquement pour le prochain tour
                s = analyse(h)
                await update.message.reply_text(
                    f"✅ *{cote}x* enregistré _{n} total_\n\n"
                    + signal_court(s),
                    parse_mode="Markdown"
                )
            return
    except ValueError:
        pass
    await update.message.reply_text(
        "❓ Tape une cote (ex: `2.35`) ou `/start`",
        parse_mode="Markdown"
    )

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("analyse", cmd_analyse))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("clear",   cmd_clear))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("🤖 Bot démarré")
    app.run_polling()

if __name__ == "__main__":
    main()
