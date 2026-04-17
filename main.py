import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

app = FastAPI()

# --- CONFIGURATION DU DOSSIER TEMPLATES (Chemin absolu 100% fiable) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- VARIABLES GLOBALES ---
current_price = 0.00
current_capital = 1000.00
bot_status = "Arrêté"
bot_running = False

# Variables pour la simulation de stratégie
has_position = False
buy_price = 0.0

# --- BASE DE DONNÉES SQLITE ---
DB_PATH = os.path.join(BASE_DIR, 'trading_bot.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            action TEXT, 
            price REAL, 
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def log_trade(action, price):
    """Enregistre un trade dans la base de données"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO trades (action, price) VALUES (?, ?)", (action, price))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Erreur BDD : {e}")

def get_recent_trades():
    """Récupère les 50 derniers trades pour le dashboard"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT action, price, timestamp FROM trades ORDER BY timestamp DESC LIMIT 50")
        trades = [{"action": row[0], "price": row[1], "date": row[2]} for row in c.fetchall()]
        conn.close()
        return trades
    except:
        return []

init_db()

# --- LOGIQUE DU BOT EN ARRIÈRE-PLAN ---
async def run_bot():
    global current_price, bot_status, bot_running, current_capital
    global has_position, buy_price
    
    exchange = ccxt.binance()
    
    # Message de démarrage pour les logs
    print("Engine: Moteur initialisé avec un capital de", current_capital, "$")
    
    while True:
        if bot_running:
            try:
                # 1. Récupération du prix
                ticker = await exchange.fetch_ticker('BTC/USDT')
                current_price = ticker['last']
                bot_status = "Actif"
                print(f"[BOT] Prix actualisé : {current_price} $")

                # ==========================================
                # 2. STRATÉGIE (Simulation d'achats/ventes)
                # ==========================================
                if not has_position:
                    # On simule un signal d'achat
                    print(f"🚀 Signal d'ACHAT détecté ! Achat à {current_price} $")
                    buy_price = current_price
                    has_position = True
                    log_trade("ACHAT", current_price)
                    
                elif has_position and current_price != buy_price:
                    # On simule une vente (dès que le prix bouge pour l'exemple)
                    profit = current_price - buy_price
                    current_capital += profit
                    print(f"📉 Signal de VENTE détecté ! Vente à {current_price} $ | Profit: {profit:.2f} $")
                    has_position = False
                    log_trade("VENTE", current_price)
                # ==========================================

            except Exception as e:
                print(f"Erreur de récupération du prix : {e}")
        else:
            bot_status = "Arrêté"
            
        # Attend 5 secondes avant de rafraîchir
        await asyncio.sleep(5)

# --- DÉMARRAGE DE LA TÂCHE AU LANCEMENT ---
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_bot())

# --- ROUTES DE L'INTERFACE WEB ---
@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/stats")
async def stats():
    # Renvoie les statistiques ET l'historique des trades au dashboard
    return {
        "price": current_price,
        "capital": current_capital,
        "status": bot_status,
        "trades": get_recent_trades()
    }

@app.post("/start")
async def start_bot():
    global bot_running
    bot_running = True
    return {"message": "Bot démarré"}

@app.post("/stop")
async def stop_bot():
    global bot_running
    bot_running = False
    return {"message": "Bot arrêté"}
