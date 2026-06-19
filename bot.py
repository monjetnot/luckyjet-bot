import os
import csv
import io
import statistics
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InputFile
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# ─── Stockage en mémoire (par chat_id) ──────────────────────────────────
# Chaque entrée : {"ts": datetime, "cote": float, "mise": float|None, "resultat": float|None}
user_sessions = defaultdict(list)
user_bankroll = defaultdict(lambda: {"depot_initial": None, "mise_defaut": 100.0})

LOSS_STREAK_ALERT_THRESHOLD = 4  # alerte après N pertes consécutives


# ─── Helpers ─────────────────────────────────────────────────────────────
def get_entries(chat_id):
    return user_sessions[chat_id]


def get_cotes(chat_id):
    return [e["cote"] for e in get_entries(chat_id)]


def session_key(ts: datetime):
    """Regroupe par jour pour les stats de session"""
    return ts.strftime("%Y-%m-%d")


# ─── Analyse statistique (cotes) ────────────────────────────────────────
def analyse_fourchette(cotes):
    if len(cotes) < 5:
        return None
    recent = cotes[-20:] if len(cotes) >= 20 else cotes
    last5 = cotes[-5:]
    mean = statistics.mean(recent)
    stdev = statistics.stdev(recent) if len(recent) >= 2 else 0.5
    freq_2plus = sum(1 for c in recent if c >= 2.0) / len(recent) * 100
    high_recently = any(c > 5.0 for c in last5)

    if high_recently:
        low = max(1.05, mean - stdev)
        high = mean + 0.3 * stdev
        tendency = "⬇️ Tend vers BAS (pic récent)"
    elif cotes[-1] < 1.5 and sum(1 for c in last5 if c < 1.5) >= 3:
        low = 1.5
        high = mean + stdev
        tendency = "⬆️ Rebond possible"
    else:
        low = max(1.05, mean - 0.5 * stdev)
        high = mean + 0.7 * stdev
        tendency = "➡️ Zone neutre"

    return {
        "low": round(low, 2), "high": round(high, 2), "mean": round(mean, 2),
        "freq_2plus": round(freq_2plus, 1), "tendency": tendency, "nb_cotes": len(cotes)
    }


def signal_auto(cotes):
    if len(cotes) < 5:
        return f"📥 Encore {5 - len(cotes)} cote(s) pour l'analyse..."
    res = analyse_fourchette(cotes)
    prob_2plus = "🔥 HAUTE" if res["freq_2plus"] >= 50 else ("⚡ MOYENNE" if res["freq_2plus"] >= 35 else "❄️ BASSE")
    return (
        f"🎯 *Tendance (informative, pas une prédiction)*\n"
        f"📊 Fourchette observée : `{res['low']}x — {res['high']}x`\n"
        f"🎰 Fréquence ≥2.0 récente : {prob_2plus} ({res['freq_2plus']}%)\n"
        f"{res['tendency']}\n"
        f"📈 Moyenne : {res['mean']}x ({res['nb_cotes']} cotes)"
    )


# ─── Bankroll : calcul gains/pertes ──────────────────────────────────────
def calc_bankroll(entries):
    """Retourne stats bankroll à partir des entrées avec mise/resultat connus"""
    total_mise = 0.0
    total_resultat = 0.0
    nb_paris = 0
    for e in entries:
        if e.get("mise") is not None and e.get("resultat") is not None:
            total_mise += e["mise"]
            total_resultat += e["resultat"]
            nb_paris += 1
    solde = total_resultat - total_mise
    return {
        "total_mise": round(total_mise, 2),
        "total_resultat": round(total_resultat, 2),
        "solde": round(solde, 2),
        "nb_paris": nb_paris
    }


def current_loss_streak(entries):
    """Compte la série de pertes consécutives (résultat < mise)"""
    streak = 0
    for e in reversed(entries):
        if e.get("mise") is None or e.get("resultat") is None:
            continue
        if e["resultat"] < e["mise"]:
            streak += 1
        else:
            break
    return streak


# ─── Stats par session (jour) ────────────────────────────────────────────
def stats_par_session(entries):
    sessions = defaultdict(list)
    for e in entries:
        sessions[session_key(e["ts"])].append(e)

    result = []
    for day, day_entries in sorted(sessions.items()):
        cotes = [e["cote"] for e in day_entries]
        bk = calc_bankroll(day_entries)
        result.append({
            "jour": day,
            "nb_tours": len(cotes),
            "moyenne": round(statistics.mean(cotes), 2),
            "freq_2plus": round(sum(1 for c in cotes if c >= 2.0) / len(cotes) * 100, 1),
            "bankroll": bk
        })
    return result


# ─── COMMANDES ────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 *Bot Lucky Jet v3 — Suivi complet*\n\n"
        "📌 *Saisie simple (sans argent) :*\n"
        "• Tape juste la cote : `2.35`\n\n"
        "💰 *Saisie avec suivi bankroll :*\n"
        "• Format : `cote mise resultat`\n"
        "• Exemple : `2.35 100 235` (mise 100f, tu as gagné 235f)\n"
        "• Si tu perds : `1.20 100 0`\n\n"
        "📊 *Commandes :*\n"
        "/analyse — Tendance statistique (informative)\n"
        "/bankroll — Bilan gains/pertes\n"
        "/sessions — Stats par jour\n"
        "/graphique — Graphique visuel\n"
        "/export — Export CSV de toutes tes données\n"
        "/historique — Dernières cotes\n"
        "/reset — Effacer l'historique\n\n"
        "⚠️ Ce bot ne prédit pas l'avenir. Il t'aide à suivre tes données pour jouer de façon plus consciente."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def handle_cote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", ".")
    chat_id = update.effective_chat.id
    parts = text.split()

    cote = mise = resultat = None
    try:
        if len(parts) == 1:
            cote = float(parts[0])
        elif len(parts) == 3:
            cote, mise, resultat = float(parts[0]), float(parts[1]), float(parts[2])
        else:
            return
        if not (1.0 <= cote <= 1000):
            return
    except ValueError:
        return

    now = datetime.now()
    entry = {"ts": now, "cote": cote, "mise": mise, "resultat": resultat}
    user_sessions[chat_id].append(entry)
    entries = get_entries(chat_id)
    cotes = get_cotes(chat_id)

    marker = "🔴" if cote < 1.5 else ("🟡" if cote < 2.0 else "🟢")
    lines = [f"{marker} Cote : *{cote}x* (#{len(cotes)})"]

    # Si mise/résultat fournis → afficher le P&L de ce tour + alerte série
    if mise is not None:
        pnl = resultat - mise
        pnl_str = f"+{pnl:.0f}f ✅" if pnl >= 0 else f"{pnl:.0f}f ❌"
        lines.append(f"💰 Mise {mise:.0f}f → {resultat:.0f}f ({pnl_str})")

        streak = current_loss_streak(entries)
        if streak >= LOSS_STREAK_ALERT_THRESHOLD:
            lines.append(
                f"\n🛑 *Alerte* : {streak} pertes consécutives.\n"
                f"Ça peut être un bon moment pour faire une pause. 🙏"
            )

    lines.append("─────────────────")
    lines.append(signal_auto(cotes))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def analyse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cotes = get_cotes(chat_id)
    if len(cotes) < 5:
        await update.message.reply_text(f"⚠️ Il faut au moins 5 cotes. Tu en as {len(cotes)}.")
        return

    res = analyse_fourchette(cotes)
    recent = cotes[-10:]
    serie = " | ".join([f"{'🟢' if c>=2 else '🔴'}{c}x" for c in recent])

    streak_bas = 0
    for c in reversed(cotes):
        if c < 2.0:
            streak_bas += 1
        else:
            break
    streak_msg = f"⚠️ {streak_bas} cotes consécutives < 2.0" if streak_bas >= 3 else "✅ Pas de série négative"

    msg = (
        f"📊 *Analyse — {len(cotes)} cotes*\n\n"
        f"🎯 Fourchette observée : `{res['low']}x — {res['high']}x`\n"
        f"📈 Moyenne : *{res['mean']}x*\n"
        f"🔥 Fréquence ≥2.0 : *{res['freq_2plus']}%*\n"
        f"{res['tendency']}\n\n"
        f"📉 Dernières cotes :\n{serie}\n\n"
        f"{streak_msg}\n\n"
        f"_Ceci décrit le passé, ça ne prédit pas le prochain tour._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def bankroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    entries = get_entries(chat_id)
    bk = calc_bankroll(entries)

    if bk["nb_paris"] == 0:
        await update.message.reply_text(
            "📭 Aucune mise enregistrée encore.\n\n"
            "Pour suivre ton bankroll, saisis : `cote mise resultat`\n"
            "Exemple : `2.35 100 235`"
        )
        return

    solde_str = f"+{bk['solde']:.0f}f ✅" if bk['solde'] >= 0 else f"{bk['solde']:.0f}f ❌"
    streak = current_loss_streak(entries)
    streak_msg = f"\n🛑 Série actuelle : {streak} perte(s) consécutive(s)" if streak > 0 else "\n✅ Pas de perte en cours"

    msg = (
        f"💰 *Bilan Bankroll*\n\n"
        f"🎲 Nombre de paris : {bk['nb_paris']}\n"
        f"📥 Total misé : {bk['total_mise']:.0f}f\n"
        f"📤 Total reçu : {bk['total_resultat']:.0f}f\n"
        f"━━━━━━━━━━━━\n"
        f"*Solde net : {solde_str}*"
        f"{streak_msg}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def sessions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    entries = get_entries(chat_id)
    if not entries:
        await update.message.reply_text("📭 Aucune donnée enregistrée.")
        return

    stats = stats_par_session(entries)
    lines = ["📅 *Statistiques par session (jour)*\n"]
    for s in stats[-14:]:  # 14 derniers jours max
        bk = s["bankroll"]
        line = f"📆 *{s['jour']}* — {s['nb_tours']} tours, moy {s['moyenne']}x, {s['freq_2plus']}% ≥2.0"
        if bk["nb_paris"] > 0:
            solde_str = f"+{bk['solde']:.0f}f" if bk['solde'] >= 0 else f"{bk['solde']:.0f}f"
            line += f"\n   💰 {bk['nb_paris']} paris → {solde_str}"
        lines.append(line)

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def graphique(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    entries = get_entries(chat_id)
    if len(entries) < 5:
        await update.message.reply_text("⚠️ Il faut au moins 5 cotes pour générer un graphique.")
        return

    ts_list = [e["ts"] for e in entries]
    cotes = [e["cote"] for e in entries]

    fig, axes = plt.subplots(2, 1, figsize=(9, 7), gridspec_kw={"height_ratios": [2, 1]})

    # Graphique 1 : cotes dans le temps
    colors = ["#e74c3c" if c < 2.0 else "#27ae60" for c in cotes]
    axes[0].bar(range(len(cotes)), cotes, color=colors)
    axes[0].axhline(y=2.0, color="#34495e", linestyle="--", linewidth=1, label="Seuil 2.0x")
    axes[0].set_title("Historique des cotes", fontsize=13, fontweight="bold")
    axes[0].set_ylabel("Cote (x)")
    axes[0].set_xlabel("Tour #")
    axes[0].legend()

    # Graphique 2 : évolution bankroll cumulée
    cum = 0
    cum_values = []
    for e in entries:
        if e.get("mise") is not None and e.get("resultat") is not None:
            cum += (e["resultat"] - e["mise"])
        cum_values.append(cum)

    axes[1].plot(range(len(cum_values)), cum_values, color="#2980b9", linewidth=2)
    axes[1].fill_between(range(len(cum_values)), cum_values, 0,
                          where=[v >= 0 for v in cum_values], color="#27ae60", alpha=0.2)
    axes[1].fill_between(range(len(cum_values)), cum_values, 0,
                          where=[v < 0 for v in cum_values], color="#e74c3c", alpha=0.2)
    axes[1].axhline(y=0, color="black", linewidth=0.8)
    axes[1].set_title("Solde cumulé (F CFA)", fontsize=11, fontweight="bold")
    axes[1].set_ylabel("Solde (f)")
    axes[1].set_xlabel("Tour #")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130)
    buf.seek(0)
    plt.close(fig)

    await update.message.reply_photo(photo=InputFile(buf, filename="graphique.png"))


async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    entries = get_entries(chat_id)
    if not entries:
        await update.message.reply_text("📭 Aucune donnée à exporter.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date_heure", "cote", "mise", "resultat", "gain_perte"])
    for e in entries:
        pnl = ""
        if e.get("mise") is not None and e.get("resultat") is not None:
            pnl = round(e["resultat"] - e["mise"], 2)
        writer.writerow([
            e["ts"].strftime("%Y-%m-%d %H:%M:%S"),
            e["cote"],
            e.get("mise") or "",
            e.get("resultat") or "",
            pnl
        ])

    byte_buf = io.BytesIO(buf.getvalue().encode("utf-8"))
    byte_buf.seek(0)
    filename = f"luckyjet_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    await update.message.reply_document(document=InputFile(byte_buf, filename=filename))


async def historique(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    entries = get_entries(chat_id)
    if not entries:
        await update.message.reply_text("📭 Aucune cote enregistrée.")
        return

    last20 = entries[-20:]
    lines = [f"📋 *{len(entries)} cotes (20 dernières) :*\n"]
    for i, e in enumerate(last20, 1):
        idx = len(entries) - len(last20) + i
        marker = "🟢" if e["cote"] >= 2.0 else ("🟡" if e["cote"] >= 1.5 else "🔴")
        extra = ""
        if e.get("mise") is not None:
            pnl = e["resultat"] - e["mise"]
            extra = f" ({'+' if pnl>=0 else ''}{pnl:.0f}f)"
        lines.append(f"{marker} #{idx} → *{e['cote']}x*{extra} — {e['ts'].strftime('%H:%M')}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    nb = len(user_sessions[chat_id])
    user_sessions[chat_id] = []
    await update.message.reply_text(f"🗑️ Historique effacé ({nb} entrées supprimées).")


# ─── MAIN ─────────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN manquant")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analyse", analyse))
    app.add_handler(CommandHandler("bankroll", bankroll))
    app.add_handler(CommandHandler("sessions", sessions_cmd))
    app.add_handler(CommandHandler("graphique", graphique))
    app.add_handler(CommandHandler("export", export_csv))
    app.add_handler(CommandHandler("historique", historique))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cote))

    print("✅ Bot Lucky Jet v3 démarré !")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
