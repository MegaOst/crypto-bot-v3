from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import sqlite3
import os

app = FastAPI()

# Configuration du dossier contenant index.html (le dossier actuel)
templates = Jinja2Templates(directory="templates")

# Variables globales du bot
current_price = 0.0
current_capital = 1000.0  # Mettez votre capital de départ ici
bot_state = "Arrêté" # État du bot

# --- CONFIGURATION BASE DE DONNÉES SQLite ---
# Utilise le volume Railway /app/data s'il existe, sinon crée en local
DB_PATH = "/app/data/trades.db" if os.path.exists("/app/data") else "trades.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            buy_price REAL,
            sell_price REAL,
            performance REAL,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Initialiser la base au lancement
init_db()

def enregistrer_trade(buy_price, sell_price, performance, status):
    """ Fonction à appeler dans votre logique de bot quand un trade se termine """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (buy_price, sell_price, performance, status) 
        VALUES (?, ?, ?, ?)
    ''', (buy_price, sell_price, performance, status))
    conn.commit()
    conn.close()

# --- ROUTES WEB ---

@app.get("/")
async def home(request: Request):
    # C'est ici qu'on a corrigé l'erreur précédente : name= et request=
    return templates.TemplateResponse(name="index.html", request=request)

@app.get("/stats")
async def get_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # On récupère tous les trades du plus récent au plus ancien
    cursor.execute('SELECT * FROM trades ORDER BY id DESC')
    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_state": bot_state,
        "trades": trades
    }

# Routes pour les boutons Démarrer/Arrêter
@app.get("/start")
async def start_bot():
    global bot_state
    bot_state = "En cours"
    # Ajoutez ici la logique pour lancer votre bot
    return {"message": "Bot démarré"}

@app.get("/stop")
async def stop_bot():
    global bot_state
    bot_state = "Arrêté"
    # Ajoutez ici la logique pour stopper votre bot
    return {"message": "Bot arrêté"}

# --- VOTRE LOGIQUE DE TRADING (Boucle principale) ---
# Vous pouvez continuer à mettre votre code de trading asynchrone ici
