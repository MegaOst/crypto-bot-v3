import asyncio
import ccxt
import pandas as pd
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.templating import Jinja2Templates
from core.engine import PaperTradingEngine
from strategies.strategy_1 import check_entry_signal, check_exit_signal

app = FastAPI(title="Crypto Bot Simulation")
templates = Jinja2Templates(directory="templates")
engine = PaperTradingEngine(initial_capital=1000)
exchange = ccxt.binance()
SYMBOL = "BTC/USDT"
TIMEFRAME = "15m"
BOT_RUNNING = False

async def bot_loop():
    global BOT_RUNNING
    while BOT_RUNNING:
        try:
            ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=10)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_price = df.iloc[-1]['close']
            current_time = df.iloc[-1]['timestamp']

            if engine.position:
                exit_signal, perf = check_exit_signal(current_price, engine.position['entry_price'])
                if exit_signal:
                    engine.sell(current_price, current_time, exit_signal)
            else:
                if check_entry_signal(df.iloc[:-1]): 
                    engine.buy(SYMBOL, current_price, current_time)
        except Exception as e:
            print(f"Erreur dans la boucle: {e}")
        
        await asyncio.sleep(60)

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health_check():
    return {"status": "healthy", "bot_running": BOT_RUNNING}

@app.post("/start")
async def start_bot(background_tasks: BackgroundTasks):
    global BOT_RUNNING
    if not BOT_RUNNING:
        BOT_RUNNING = True
        background_tasks.add_task(bot_loop)
        return {"message": "Bot démarré"}
    return {"message": "Le bot est déjà en cours d'exécution"}

@app.post("/stop")
def stop_bot():
    global BOT_RUNNING
    BOT_RUNNING = False
    return {"message": "Bot arrêté"}

@app.get("/stats")
def get_stats():
    return engine.get_stats()
