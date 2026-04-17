import os
import asyncio
import logging
import sys
import time
import ccxt
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from core.engine import PaperTradingEngine

# --- CONFIGURATION DES LOGS ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BotMain")

# --- VARIABLES D'ENVIRONNEMENT ---
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")

app = FastAPI()
templates = Jinja2Templates(directory="templates")
engine = PaperTradingEngine(initial_capital=1000)

# Initialisation de l'échange (Binance public)
exchange = ccxt.binance({
    'enableRateLimit': True,
})

bot_running = False

async def bot_loop():
    global bot_running
    logger.info(f"🚀 Démarrage du bot sur {SYMBOL} avec prix en direct...")
    
    while bot_running:
        try:
            # 1. Récupération du prix en direct
            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = ticker['last']
            current_time = time.strftime("%Y-%m-%d %H:%M:%S")
            
            logger.info(f"📊 Prix actuel de {SYMBOL} : {current_price}$")

            # 2. Logique de trading (Simulation basique)
            if engine.position is None:
                # Acheter arbitrairement pour la démo
                logger.info("💡 Signal d'entrée détecté (Démo)")
                engine.buy(SYMBOL, current_price, current_time)
            
            else:
                # Calcul du profit actuel en direct
                entry_price = engine.position['entry_price']
                profit_pct = (current_price - entry_price) / entry_price
                
                logger.info(f"⏳ Position en cours... P&L latent : {profit_pct*100:.2f}%")

                # Vendre si +0.5% (Take Profit) ou -0.5% (Stop Loss)
                if profit_pct >= 0.005:
                    engine.sell(current_price, current_time, reason="Take Profit (+0.5%)")
                elif profit_pct <= -0.005:
                    engine.sell(current_price, current_time, reason="Stop Loss (-0.5%)")

        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération des données : {e}")
        
        # Attendre 10 secondes avant la prochaine vérification
        await asyncio.sleep(10)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/start")
async def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        asyncio.create_task(bot_loop())
        logger.info("✅ Bot Démarré.")
        return {"status": "Bot démarré"}
    return {"status": "Bot déjà en cours"}

@app.post("/stop")
async def stop_bot():
    global bot_running
    bot_running = False
    logger.info("🛑 Bot Arrêté.")
    return {"status": "Bot arrêté"}

@app.get("/stats")
def get_stats():
    return engine.get_stats()
