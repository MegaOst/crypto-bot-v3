import asyncio
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import ccxt
import uvicorn

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
                # Calcul de la performance actuelle
                profit_pct = ((current_price - buy_price) / buy_price) * 100
                bot_status = f"En position | Profit latent: {profit_pct:.2f}%"
                
                # On vend si on touche +0.05% ou -0.05% (Très serré, juste pour voir le bot s'animer vite !)
                if profit_pct >= 0.05 or profit_pct <= -0.05:
                    # Mise à jour du capital
                    current_capital = current_capital + (current_capital * (profit_pct / 100))
                    
                    # Enregistrement du trade
                    trade = {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "buy_price": buy_price,
                        "sell_price": current_price,
                        "profit": profit_pct
                    }
                    trade_history.append(trade)
                    
                    print(f"VENTE à {current_price} $ | Profit: {profit_pct:.2f}%")
                    
                    # Réinitialisation pour le prochain trade
                    position = None
                    buy_price = 0.0
                    bot_status = "Recherche d'opportunité..."
                    
                    # Pause avant de racheter
                    await asyncio.sleep(5)
                    
        except Exception as e:
            bot_status = f"Erreur API: {str(e)}"
            print(f"❌ Erreur: {e}")
            
        # On attend 10 secondes avant la prochaine vérification du prix
        await asyncio.sleep(10)

# --- ROUTES WEB ---
@app.on_event("startup")
async def startup_event():
    # Lancement de la boucle de trading en arrière-plan
    asyncio.create_task(trading_loop())

@app.get("/")
async def home(request: Request):
    # Affiche le dashboard HTML
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/stats")
async def get_stats():
    # Renvoie les données au format JSON pour le dashboard
    return {
        "price": current_price,
        "capital": current_capital,
        "status": bot_status,
        "trades": trade_history[-10:] # On n'envoie que les 10 derniers trades
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
