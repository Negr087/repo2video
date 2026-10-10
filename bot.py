"""Bot de Telegram: pegale un link de GitHub y te devuelve un video vertical
(motion graphics) que explica como funciona el repo."""
import asyncio
import logging
import os
import re
import shutil
import tempfile
import urllib.error
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import pipeline
from github_summary import RepoError
from storyboard import StoryboardError

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
SEND_JSON = os.getenv("SEND_JSON", "0") == "1"   # manda tambien el guion para revisarlo
lock = asyncio.Lock()  # un video a la vez: el modelo y el render usan casi toda la RAM


def allowed(update: Update) -> bool:
    return not ALLOWED or update.effective_user.id in ALLOWED


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Pegame un link de GitHub y te armo un video vertical que explica cómo funciona "
        "el proyecto. Tarda varios minutos.\n"
        f"Tu ID de Telegram: {update.effective_user.id}")


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    msg = update.message
    if not re.search(r"github\.com/", msg.text or ""):
        await msg.reply_text("Mandame un link de GitHub, por ejemplo https://github.com/usuario/repo")
        return
    tmp = Path(tempfile.mkdtemp())
    loop = asyncio.get_running_loop()
    try:
        status = await msg.reply_text("En cola..." if lock.locked() else "Empezando...")

        def on_status(text):  # se llama desde el hilo de trabajo
            asyncio.run_coroutine_threadsafe(status.edit_text(text), loop)

        async with lock:
            r = await asyncio.to_thread(pipeline.run, msg.text, tmp / "out", on_status)

        caption = (f"{r['info']['owner']}/{r['info']['repo']}\n"
                   "Guion generado con un modelo local: puede tener errores, revisalo.")
        with open(r["video"], "rb") as v:
            await msg.reply_video(v, caption=caption, supports_streaming=True,
                                  width=720, height=1280,
                                  read_timeout=300, write_timeout=300)
        if SEND_JSON:
            with open(r["guion"], "rb") as g:
                await msg.reply_document(g, filename="guion.json")
        await status.delete()
    except RepoError as e:
        await msg.reply_text(str(e))
    except StoryboardError as e:
        await msg.reply_text(f"{e} Probá de nuevo o con otro repo.")
    except urllib.error.URLError:
        await msg.reply_text("No pude hablar con Ollama. ¿Está prendido? "
                             "En el nodo: sudo docker start ollama")
    except Exception as e:
        logging.exception("Fallo procesando")
        await msg.reply_text(f"No pude armar el video:\n{(getattr(e, 'stderr', '') or str(e))[-400:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    app = Application.builder().token(TOKEN).read_timeout(300).write_timeout(300).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.run_polling()


if __name__ == "__main__":
    main()
