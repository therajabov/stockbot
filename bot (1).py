"""
📈 Stock Alert Bot — MA & RSI
"""

import asyncio
import logging
import io
from datetime import datetime

import yfinance as yf
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8399224333:AAGo2LT4h05bbzfm8L-NuEgBe7yPS3d_0Gk"
CHECK_INTERVAL = 120  # 2 daqiqada bir tekshiradi

user_alerts: dict[int, list[dict]] = {}

S_TICKER, S_TYPE, S_PRICE_VAL, S_PRICE_DIR, S_RSI_DIR, S_MA_TYPE = range(6)


# ── CHART ─────────────────────────────────────────────────────────────────────

def make_chart(ticker: str, note: str) -> bytes:
    df = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"{ticker} topilmadi")

    close = df["Close"].squeeze()
    df["MA20"]  = close.rolling(20).mean()
    df["MA50"]  = close.rolling(50).mean()
    df["MA200"] = close.rolling(200).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["RSI"] = 100 - (100 / (1 + gain / loss))

    fig = plt.figure(figsize=(12, 7), facecolor="#0d1117")
    gs = GridSpec(3, 1, figure=fig, height_ratios=[3, 1, 1], hspace=0.06)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    for ax in [ax1, ax2, ax3]:
        ax.set_facecolor("#0d1117")
        ax.tick_params(colors="#8b949e", labelsize=8)
        ax.spines[:].set_color("#30363d")
        ax.grid(color="#21262d", linewidth=0.5, linestyle="--")

    last  = float(close.iloc[-1])
    first = float(close.iloc[0])
    color = "#3fb950" if last >= first else "#f85149"

    ax1.plot(df.index, close,              color=color,    linewidth=2,   label="Narx")
    ax1.plot(df.index, df["MA20"].squeeze(), color="#e3b341", linewidth=1.3, linestyle="--", label="MA20")
    ax1.plot(df.index, df["MA50"].squeeze(), color="#58a6ff", linewidth=1.3, linestyle="--", label="MA50")
    ma200 = df["MA200"].squeeze()
    if ma200.notna().sum() > 5:
        ax1.plot(df.index, ma200, color="#ff7b72", linewidth=1.0, linestyle=":", label="MA200")
    ax1.fill_between(df.index, close, close.min(), alpha=0.07, color=color)
    ax1.axhline(last, color=color, linewidth=0.7, linestyle=":")
    ax1.text(df.index[-1], last, f"  ${last:.2f}", color=color, fontsize=9, va="center", fontweight="bold")

    change = (last - first) / first * 100
    sign   = "▲" if change >= 0 else "▼"
    name   = yf.Ticker(ticker).info.get("shortName", ticker)
    ax1.set_title(
        f"{name} ({ticker})   {sign} {abs(change):.2f}%  |  3 oy\n🔔 {note}",
        color="white", fontsize=10, fontweight="bold", pad=8, loc="left"
    )
    ax1.legend(loc="upper left", facecolor="#161b22", edgecolor="#30363d", labelcolor="white", fontsize=8)
    ax1.set_ylabel("Narx ($)", color="#8b949e", fontsize=8)

    vol  = df["Volume"].squeeze()
    vcol = ["#3fb950" if c >= o else "#f85149"
            for c, o in zip(df["Close"].squeeze(), df["Open"].squeeze())]
    ax2.bar(df.index, vol, color=vcol, alpha=0.7, width=0.8)
    ax2.set_ylabel("Hajm", color="#8b949e", fontsize=8)

    rsi = df["RSI"].squeeze()
    ax3.plot(df.index, rsi, color="#bc8cff", linewidth=1.5)
    ax3.axhline(70, color="#f85149", linewidth=0.8, linestyle="--")
    ax3.axhline(30, color="#3fb950", linewidth=0.8, linestyle="--")
    ax3.fill_between(df.index, rsi, 70, where=(rsi >= 70), alpha=0.2, color="#f85149")
    ax3.fill_between(df.index, rsi, 30, where=(rsi <= 30), alpha=0.2, color="#3fb950")
    ax3.set_ylim(0, 100)
    ax3.set_ylabel("RSI", color="#8b949e", fontsize=8)
    rsi_last = float(rsi.iloc[-1])
    ax3.text(df.index[-1], rsi_last, f"  {rsi_last:.1f}", color="#bc8cff", fontsize=8, va="center")

    plt.setp(ax1.get_xticklabels(), visible=False)
    plt.setp(ax2.get_xticklabels(), visible=False)
    ax3.tick_params(axis="x", rotation=30)

    fig.text(0.99, 0.01, f"StockAlertBot • {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
             color="#484f58", fontsize=7, ha="right")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── ALERT TEKSHIRUVI ──────────────────────────────────────────────────────────

def check_price(a):
    info  = yf.Ticker(a["ticker"]).info
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        return False, ""
    t = a["target"]
    if a["dir"] == "above" and price >= t:
        return True, f"💹 <b>{a['ticker']}</b> narxi <b>${price:.2f}</b> ga yetdi  (chegara: >${t})"
    if a["dir"] == "below" and price <= t:
        return True, f"📉 <b>{a['ticker']}</b> narxi <b>${price:.2f}</b> ga tushdi  (chegara: <${t})"
    return False, ""

def check_rsi(a):
    df = yf.download(a["ticker"], period="1mo", interval="1d", progress=False, auto_adjust=True)
    if df.empty or len(df) < 15:
        return False, ""
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])
    lv, dr = a["rsi_level"], a["rsi_dir"]
    if dr == "above" and rsi >= lv:
        return True, f"🔴 <b>{a['ticker']}</b> RSI = <b>{rsi:.1f}</b> — OVERBOUGHT (>{lv})"
    if dr == "below" and rsi <= lv:
        return True, f"🟢 <b>{a['ticker']}</b> RSI = <b>{rsi:.1f}</b> — OVERSOLD (<{lv})"
    return False, ""

def check_ma(a):
    df = yf.download(a["ticker"], period="12mo", interval="1d", progress=False, auto_adjust=True)
    sp, lp = a["ma_short"], a["ma_long"]
    if df.empty or len(df) < lp + 5:
        return False, ""
    close    = df["Close"].squeeze()
    short_ma = close.rolling(sp).mean()
    long_ma  = close.rolling(lp).mean()
    if short_ma.iloc[-2:].isna().any() or long_ma.iloc[-2:].isna().any():
        return False, ""
    prev_above = float(short_ma.iloc[-2]) > float(long_ma.iloc[-2])
    curr_above = float(short_ma.iloc[-1]) > float(long_ma.iloc[-1])
    if not prev_above and curr_above:
        return True, f"🌟 <b>{a['ticker']}</b> GOLDEN CROSS!\nMA{sp} MA{lp} dan oshdi → Bullish 📈"
    if prev_above and not curr_above:
        return True, f"☠️ <b>{a['ticker']}</b> DEATH CROSS!\nMA{sp} MA{lp} dan tushdi → Bearish 📉"
    return False, ""

CHECKERS = {"price": check_price, "rsi": check_rsi, "ma": check_ma}

async def alert_loop(app: Application):
    await asyncio.sleep(15)
    while True:
        for chat_id, alerts in list(user_alerts.items()):
            for alert in list(alerts):
                try:
                    fn = CHECKERS.get(alert["type"])
                    if not fn:
                        continue
                    triggered, msg = fn(alert)
                    if triggered:
                        note = msg.replace("<b>", "").replace("</b>", "")
                        img  = make_chart(alert["ticker"], note)
                        await app.bot.send_photo(
                            chat_id=chat_id,
                            photo=img,
                            caption=(
                                f"🔔 <b>ALERT ISHGA TUSHDI!</b>\n\n"
                                f"{msg}\n\n"
                                f"⏰ {datetime.utcnow().strftime('%H:%M:%S')} UTC"
                            ),
                            parse_mode="HTML"
                        )
                        if alert.get("once", False):
                            alerts.remove(alert)
                except Exception as e:
                    logger.error(f"Alert xato ({alert.get('ticker')}): {e}")
        await asyncio.sleep(CHECK_INTERVAL)


# ── KOMANDALAR ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📈 <b>Stock Alert Bot</b>ga xush kelibsiz!\n\n"
        "Amerika aksiyalarini kuzatib, shart bajarilganda chart bilan xabar yuboraman.\n\n"
        "🔧 <b>Komandalar:</b>\n"
        "/add — yangi alert qo'shish\n"
        "/list — alertlar ro'yxati\n"
        "/delete — alert o'chirish\n"
        "/chart AAPL — chart ko'rish\n"
        "/help — yordam",
        parse_mode="HTML"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Yordam</b>\n\n"
        "<b>Alert turlari:</b>\n"
        "• 💰 <b>Narx</b> — belgilangan narxga yetganda\n"
        "• 📊 <b>RSI</b> — 70+ (overbought) yoki 30− (oversold)\n"
        "• 🔀 <b>MA Kesishuv</b> — MA20/50 yoki MA50/200 kesishganda\n\n"
        "<b>Ticker misollari:</b>\n"
        "AAPL · TSLA · NVDA · MSFT · AMZN · META · GOOGL · SPY\n\n"
        "<b>Tekshiruv:</b> har 2 daqiqada\n"
        "<b>Ma'lumot:</b> Yahoo Finance (bepul)",
        parse_mode="HTML"
    )

async def cmd_chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("❗ Misol: /chart AAPL")
        return
    ticker = args[0].upper()
    m = await update.message.reply_text(f"⏳ {ticker} chart yuklanmoqda...")
    try:
        img = make_chart(ticker, "So'rov bo'yicha")
        await update.message.reply_photo(
            photo=img,
            caption=f"📊 <b>{ticker}</b> — 3 oylik chart",
            parse_mode="HTML"
        )
        await m.delete()
    except Exception as e:
        await m.edit_text(f"❌ {e}")

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid    = update.effective_chat.id
    alerts = user_alerts.get(cid, [])
    if not alerts:
        await update.message.reply_text("📭 Alert yo'q. /add orqali qo'shing.")
        return
    lines = ["📋 <b>Alertlaringiz:</b>\n"]
    for i, a in enumerate(alerts, 1):
        if a["type"] == "price":
            s    = ">" if a["dir"] == "above" else "<"
            desc = f"Narx {s} ${a['target']}"
        elif a["type"] == "rsi":
            s    = ">" if a["rsi_dir"] == "above" else "<"
            desc = f"RSI {s} {a['rsi_level']}"
        else:
            desc = f"MA{a['ma_short']}/MA{a['ma_long']} kesishuv"
        lines.append(f"{i}. <b>{a['ticker']}</b> — {desc}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid    = update.effective_chat.id
    alerts = user_alerts.get(cid, [])
    if not alerts:
        await update.message.reply_text("📭 O'chirish uchun alert yo'q.")
        return
    kb = []
    for i, a in enumerate(alerts):
        if a["type"] == "price":
            label = f"{a['ticker']} | Narx {'>' if a['dir']=='above' else '<'} ${a['target']}"
        elif a["type"] == "rsi":
            label = f"{a['ticker']} | RSI {'>' if a['rsi_dir']=='above' else '<'} {a['rsi_level']}"
        else:
            label = f"{a['ticker']} | MA{a['ma_short']}/MA{a['ma_long']}"
        kb.append([InlineKeyboardButton(f"🗑 {label}", callback_data=f"del_{i}")])
    kb.append([InlineKeyboardButton("❌ Bekor", callback_data="del_x")])
    await update.message.reply_text(
        "Qaysi alertni o'chirmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cb_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "del_x":
        await q.edit_message_text("Bekor qilindi.")
        return
    cid    = q.message.chat_id
    idx    = int(q.data.replace("del_", ""))
    alerts = user_alerts.get(cid, [])
    if 0 <= idx < len(alerts):
        r = alerts.pop(idx)
        await q.edit_message_text(f"✅ <b>{r['ticker']}</b> alerti o'chirildi.", parse_mode="HTML")


# ── /add CONVERSATION ─────────────────────────────────────────────────────────

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "➕ <b>Yangi alert</b>\n\nAksiya tickerini kiriting:\n"
        "<i>Misol: AAPL · TSLA · NVDA · SPY</i>",
        parse_mode="HTML"
    )
    return S_TICKER

async def got_ticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ticker = update.message.text.strip().upper()
    info   = yf.Ticker(ticker).info
    price  = info.get("currentPrice") or info.get("regularMarketPrice")
    if not price:
        await update.message.reply_text(f"❌ <b>{ticker}</b> topilmadi. Qayta kiriting:", parse_mode="HTML")
        return S_TICKER
    ctx.user_data["ticker"]    = ticker
    ctx.user_data["price_now"] = price
    name = info.get("shortName", ticker)
    kb = [
        [InlineKeyboardButton("💰  Narx alerta",  callback_data="t_price")],
        [InlineKeyboardButton("📊  RSI alerta",   callback_data="t_rsi")],
        [InlineKeyboardButton("🔀  MA Kesishuv",  callback_data="t_ma")],
        [InlineKeyboardButton("❌  Bekor",        callback_data="t_cancel")],
    ]
    await update.message.reply_text(
        f"✅ <b>{name}</b> ({ticker}) — ${price:.2f}\n\nAlert turini tanlang:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML"
    )
    return S_TYPE

async def got_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    t      = q.data
    ticker = ctx.user_data["ticker"]
    price  = ctx.user_data["price_now"]

    if t == "t_cancel":
        await q.edit_message_text("❌ Bekor qilindi.")
        return ConversationHandler.END

    if t == "t_price":
        ctx.user_data["atype"] = "price"
        await q.edit_message_text(
            f"💰 <b>{ticker}</b> joriy narx: <b>${price:.2f}</b>\n\n"
            "Qaysi narxda xabar yuborsin?\n<i>Misol: 220</i>",
            parse_mode="HTML"
        )
        return S_PRICE_VAL

    if t == "t_rsi":
        ctx.user_data["atype"] = "rsi"
        kb = [
            [InlineKeyboardButton("🔴  RSI > 70  (Overbought)",  callback_data="rsi_above_70")],
            [InlineKeyboardButton("🟢  RSI < 30  (Oversold)",    callback_data="rsi_below_30")],
            [InlineKeyboardButton("🔴  RSI > 80  (Kuchli OB)",   callback_data="rsi_above_80")],
            [InlineKeyboardButton("🟢  RSI < 20  (Kuchli OS)",   callback_data="rsi_below_20")],
        ]
        await q.edit_message_text(
            f"📊 <b>{ticker}</b> — RSI sharti:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML"
        )
        return S_RSI_DIR

    if t == "t_ma":
        ctx.user_data["atype"] = "ma"
        kb = [
            [InlineKeyboardButton("MA 20 / 50   (qisqa muddat)",  callback_data="ma_20_50")],
            [InlineKeyboardButton("MA 50 / 200  (uzoq muddat)",   callback_data="ma_50_200")],
        ]
        await q.edit_message_text(
            f"🔀 <b>{ticker}</b> — MA juftini tanlang:\n"
            "<i>Golden Cross yoki Death Cross bo'lganda xabar keladi</i>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML"
        )
        return S_MA_TYPE

async def got_price_val(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip().replace("$", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Faqat raqam kiriting. Misol: 220")
        return S_PRICE_VAL
    ctx.user_data["price_target"] = val
    kb = [
        [InlineKeyboardButton(f"⬆️  ${val} dan OSHSA",  callback_data="dir_above")],
        [InlineKeyboardButton(f"⬇️  ${val} dan TUSHSA", callback_data="dir_below")],
    ]
    await update.message.reply_text(
        f"Narx ${val:.2f} bo'lganda qachon xabar yuborsin?",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return S_PRICE_DIR

async def got_price_dir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
    await q.answer()
    direction = q.data.replace("dir_", "")
    cid       = q.message.chat_id
    ticker    = ctx.user_data["ticker"]
    target    = ctx.user_data["price_target"]
    user_alerts.setdefault(cid, []).append({
        "type": "price", "ticker": ticker,
        "target": target, "dir": direction, "once": True
    })
    s = ">" if direction == "above" else "<"
    await q.edit_message_text(
        f"✅ Alert qo'shildi!\n\n📌 <b>{ticker}</b> narxi {s} ${target:.2f} bo'lganda xabar olasiz 🔔",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def got_rsi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    parts  = q.data.split("_")       # rsi_above_70
    dr, lv = parts[1], int(parts[2])
    cid    = q.message.chat_id
    ticker = ctx.user_data["ticker"]
    user_alerts.setdefault(cid, []).append({
        "type": "rsi", "ticker": ticker,
        "rsi_dir": dr, "rsi_level": lv, "once": False
    })
    emoji = "🔴" if dr == "above" else "🟢"
    s     = ">" if dr == "above" else "<"
    label = "OVERBOUGHT" if dr == "above" else "OVERSOLD"
    await q.edit_message_text(
        f"✅ Alert qo'shildi!\n\n📌 {emoji} <b>{ticker}</b> RSI {s} {lv} ({label}) bo'lganda xabar olasiz 🔔",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def got_ma(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    parts  = q.data.split("_")       # ma_20_50
    sp, lp = int(parts[1]), int(parts[2])
    cid    = q.message.chat_id
    ticker = ctx.user_data["ticker"]
    user_alerts.setdefault(cid, []).append({
        "type": "ma", "ticker": ticker,
        "ma_short": sp, "ma_long": lp, "once": False
    })
    await q.edit_message_text(
        f"✅ Alert qo'shildi!\n\n📌 <b>{ticker}</b> MA{sp}/MA{lp} kesishganda\n"
        f"(Golden Cross yoki Death Cross) xabar olasiz 🔔",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def cancel_conv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            S_TICKER:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_ticker)],
            S_TYPE:      [CallbackQueryHandler(got_type,      pattern="^t_")],
            S_PRICE_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_price_val)],
            S_PRICE_DIR: [CallbackQueryHandler(got_price_dir, pattern="^dir_")],
            S_RSI_DIR:   [CallbackQueryHandler(got_rsi,       pattern="^rsi_")],
            S_MA_TYPE:   [CallbackQueryHandler(got_ma,        pattern="^ma_")],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("chart",  cmd_chart))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(cb_delete, pattern="^del_"))

    async def post_init(application: Application):
        asyncio.create_task(alert_loop(application))
    app.post_init = post_init

    logger.info("🤖 Bot ishga tushdi!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
