import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt  # Version asynchrone pour ne pas bloquer FastAPI
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

app = FastAPI()

# --- CONFIGURATION DU DOSSIER TEMPLATES (Chemin absolu 100% fiable) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- VARIABLES GLOBALES ---
current_price = 0.00
current_capital = 1000.00  # Capital de départ par défaut
bot_status = "Arrêté"
bot_running = False

# --- BASE DE DONNÉES SQLITE ---
def init_db():
    # Enregistre la base de données dans le même dossier que le script
    db_path = os.path.join(BASE_DIR, 'trading_bot.db')
    conn = sqlite3.connect(db_path)
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

init_db()

# --- LOGIQUE DU BOT EN ARRIÈRE-PLAN ---
async def run_bot():
    """Boucle qui tourne en permanence pour récupérer le prix"""
    global current_price, bot_status, bot_running
    
    # On utilise Binance en mode asynchrone
    exchange = ccxt.binance()
    
    while True:
        if bot_running:
            try:
                # Récupère le prix du Bitcoin en USDT (avec await car asynchrone)
                ticker = await exchange.fetch_ticker('BTC/USDT')
                current_price = ticker['last']
                bot_status = "Actif"
                print(f"Prix actualisé : {current_price} $")
            except Exception as e:
                print(f"Erreur de récupération du prix : {e}")
        else:
            bot_status = "Arrêté"
            
        # Attend 5 secondes avant de rafraîchir pour ne pas spammer l'API
        await asyncio.sleep(5)
        
    # Fermeture propre de l'échange (bonne pratique, bien que la boucle soit infinie)
    await exchange.close()

# --- DÉMARRAGE DE LA TÂCHE AU LANCEMENT ---
@app.on_event("startup")
async def startup_event():
    # Lance la boucle run_bot() en arrière-plan au démarrage du serveur
    asyncio.create_task(run_bot())

# --- ROUTES DE L'INTERFACE WEB ---
@app.get("/")
async def home(request: Request):
    # Affiche le fichier index.html situé dans le dossier templates
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/stats")
async def stats():
    # Envoie les données en temps réel au dashboard HTML
    return {
        "price": current_price,
        "capital": current_capital,
        "status": bot_status
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
