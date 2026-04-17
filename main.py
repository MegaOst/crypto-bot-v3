import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import ccxt

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- VARIABLES GLOBALES ---
current_capital = 1000.0
current_price = 0.0
bot_status = "Démarrage..."
trade_history = []  # Historique des trades
position = None     # None si on n'a rien, "LONG" si on a acheté
buy_price = 0.0     # Prix auquel on a acheté

# Configuration de l'échange (KuCoin ne bloque pas les IP US)
exchange = ccxt.kucoin({'enableRateLimit': True})
symbol = 'BTC/USDT'

# --- BOUCLE DE TRADING (Tâche de fond) ---
async def trading_loop():
    global current_capital, current_price, bot_status, trade_history, position, buy_price
    
    await asyncio.sleep(2) # Attendre que le serveur démarre
    
    while True:
        try:
            # 1. Récupération du prix en direct
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            
            # 2. Logique de trading (Simulation / Paper Trading)
            if position is None:
                # On simule un achat pour l'exemple
                position = "LONG"
                buy_price = current_price
                bot_status = "En position (Achat effectué)"
                print(f"ACHAT à {buy_price} $")
            
            elif position == "LONG":
                # Vérification des conditions de vente (ex: variation de 0.05% pour tester vite)
                variation = (current_price - buy_price) / buy_price * 100
                
                if variation >= 0.05 or variation <= -0.05:
                    profit_percent = variation
                    profit_usd = current_capital * (profit_percent / 100)
                    current_capital += profit_usd
                    
                    # On enregistre le trade
                    trade_history.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "buy_price": buy_price,
                        "sell_price": current_price,
                        "profit": profit_percent
                    })
                    
                    print(f"VENTE à {current_price} $ | Profit: {profit_percent:.2f}%")
                    
                    # On réinitialise pour le prochain trade
                    position = None
                    bot_status = "En attente d'opportunité..."
            
        except Exception as e:
            print(f"Erreur dans la boucle de trading: {e}")
        
        await asyncio.sleep(5)  # Pause de 5 secondes entre chaque vérification

# Démarrer la boucle en arrière-plan au lancement de l'API
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(trading_loop())

# --- ROUTES WEB ---
@app.get("/")
async def home(request: Request):
    # C'EST ICI LA CORRECTION : on utilise request=request et name="index.html"
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/stats")
async def get_stats():
    # Renvoie les statistiques au format JSON pour le dashboard
    return {
        "capital": current_capital,
        "price": current_price,
        "status": bot_status,
        "trades": trade_history
    }
