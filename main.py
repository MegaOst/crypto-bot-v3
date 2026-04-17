import asyncio
import logging
import sys
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from core.engine import PaperTradingEngine
# Si vous avez un fichier market.py et strategy_1.py :
# from core.market import fetch_ohlcv
# from strategies.strategy_1 import check_entry_signal, check_exit_signal

# --- CONFIGURATION DES LOGS POUR RAILWAY ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)] # Force l'affichage dans les logs Railway
)
logger = logging.getLogger("BotMain")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
engine = PaperTradingEngine(initial_capital=1000)

bot_running = False

async def bot_loop():
    global bot_running
    logger.info("🚀 Démarrage de la boucle du bot...")
    while bot_running:
        logger.info("Analyse du marché en cours...")
        # Ici vous mettrez la logique de fetch_ohlcv et les signaux
        # Exemple factice pour montrer que ça tourne :
        await asyncio.sleep(60) # Pause de 60 secondes entre chaque analyse

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/start")
async def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        asyncio.create_task(bot_loop())
        logger.info("✅ Commande reçue : Bot Démarré via l'interface web.")
        return {"status": "Bot démarré"}
    return {"status": "Bot déjà en cours"}

@app.post("/stop")
async def stop_bot():
    global bot_running
    bot_running = False
    logger.info("🛑 Commande reçue : Bot Arrêté via l'interface web.")
    return {"status": "Bot arrêté"}

@app.get("/stats")
def get_stats():
    return engine.get_stats()
