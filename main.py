import asyncio
import sqlite3
import os
import logging
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

# --- IMPORTS PERSONNALISÉS ---
# Assurez-vous que le fichier core/market.py existe et contient la fonction get_current_price
try:
    from core.market import get_current_price # Importe la fonction directement
except ImportError as e:
    logging.error(f"Erreur d'importation : {e}. Assurez-vous que le dossier 'core' existe et contient 'market.py' avec la fonction 'get_current_price'.")
    # Si l'import échoue, on ne peut pas continuer, on peut lever l'exception pour arrêter le démarrage
    raise

# --- CONFIGURATION DU DOSSIER TEMPLATES (Chemin absolu 100% fiable) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- CONFIGURATION DU LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# --- VARIABLES GLOBALES ---
current_price = 0.00
current_capital = 1000.00
bot_status = "Arrêté"
bot_running = False # Ce booléen indique si le processus du bot est actif

# --- CONNEXION BASE DE DONNÉES ---
DATABASE_NAME = "trading_bot.db"

def initialize_database():
    """Initialise la base de données SQLite et la table des trades si elles n'existent pas."""
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # Crée la table 'trades' avec des colonnes pour les détails de chaque transaction
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                type TEXT NOT NULL, -- 'BUY' ou 'SELL'
                amount REAL NOT NULL,
                price REAL NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        logger.info(f"Base de données '{DATABASE_NAME}' et table 'trades' sont prêtes.")
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
    finally:
        if conn:
            conn.close()

# --- LOGIQUE DU BOT ---

async def run_bot_logic():
    """
    Cette fonction contient la logique principale du bot :
    1. Récupère le prix actuel.
    2. Prend des décisions de trading (BUY/SELL).
    3. Exécute les trades.
    4. Enregistre les trades.
    """
    global current_price, current_capital, bot_status, bot_running
    bot_running = True
    bot_status = "En cours"
    logger.info("Démarrage de la boucle logique du bot...")

    while bot_running:
        try:
            # --- Étape 1 : Récupérer le prix ---
            # Utilise la fonction importée de core.market
            # Note: l'appel attend des identifiants comme "bitcoin", "usd"
            # Si vous voulez trader BTC/USDT, vous devez convertir cela en ID CoinGecko
            # Pour simplifier, je vais utiliser "bitcoin" et "usd" comme exemple.
            # Adaptez si nécessaire pour votre paire spécifique (ex: eth, usd)
            price_fetch_success = False
            try:
                # Ici, j'utilise "bitcoin" et "usd" comme exemples.
                # Si vous voulez trader BTC/USDT, vous devrez peut-être gérer les symboles différemment
                # ou vous assurer que "bitcoin" correspond à la paire que vous souhaitez.
                # Par défaut, CoinGecko utilise des IDs comme 'bitcoin', 'ethereum', 'tether', etc.
                current_price = await get_current_price("bitcoin", "usd")
                if current_price is not None:
                    logger.info(f"Prix actuel du Bitcoin (USD): {current_price:.4f} $")
                    price_fetch_success = True
                else:
                    logger.warning("Impossible de récupérer le prix actuel.")
                    current_price = 0.00 # Réinitialiser si la récupération échoue
            except NameError:
                logger.error("La fonction 'get_current_price' n'est pas disponible. Vérifiez l'importation depuis core.market.")
                # Si le bot ne peut pas récupérer le prix, on arrête la boucle pour éviter des erreurs graves
                bot_running = False
                bot_status = "Erreur: Impossible d'importer le module marché"
                break # Sortir de la boucle while

            if not price_fetch_success:
                # Attendre un peu plus longtemps avant de réessayer si la récupération de prix a échoué
                await asyncio.sleep(30) # Attend 30 secondes avant la prochaine tentative
                continue # Passer à la prochaine itération de la boucle

            # --- Étape 2 : Logique de décision de trading ---
            # C'est ici que vous implémentez vos stratégies de trading.
            # Exemple très simple : acheter si le prix est bas, vendre s'il est haut.
            # Cette partie doit être développée en fonction de votre stratégie.

            # Exemple:
            # if bot_status == "En cours" and current_capital > 100: # Assurez-vous d'avoir du capital
            #     if current_price < 30000: # Exemple de seuil d'achat
            #         logger.info("Condition d'achat remplie. Tentative d'achat...")
            #         # Ici, vous appelleriez une fonction pour exécuter un ordre d'achat
            #         # Exemple: await execute_trade("BUY", "BTC/USDT", 0.001, current_price)
            #     elif current_price > 35000: # Exemple de seuil de vente
            #         logger.info("Condition de vente remplie. Tentative de vente...")
            #         # Exemple: await execute_trade("SELL", "BTC/USDT", 0.001, current_price)

            # --- Étape 3 : Enregistrement du prix (optionnel, pour suivi) ---
            # Vous pourriez vouloir stocker current_price dans une base de données,
            # ou juste le garder dans une variable globale comme c'est le cas.

            # --- Attente avant la prochaine itération ---
            # Adaptez ce délai en fonction de la fréquence de mise à jour des prix et de votre stratégie
            # Un délai trop court peut entraîner des erreurs d'API (Rate Limiting)
            # Un délai trop long peut faire manquer des opportunités.
            await asyncio.sleep(15) # Attend 15 secondes

        except asyncio.CancelledError:
            logger.info("Tâche de logique du bot annulée.")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue dans la boucle principale du bot : {e}")
            # On ne met pas bot_running = False ici pour permettre de potentiellement récupérer
            # Mais si l'erreur est critique, il faudrait peut-être le faire.
            await asyncio.sleep(10) # Petite pause avant de réessayer

    bot_status = "Arrêté"
    bot_running = False
    logger.info("Boucle logique du bot terminée.")

# --- FONCTIONS FastAPI ---
app = FastAPI()

@app.get("/")
async def read_root(request: Request):
    """Page d'accueil affichant l'état actuel du bot."""
    return templates.TemplateResponse("index.html", {"request": request, "current_price": current_price, "current_capital": current_capital, "bot_status": bot_status})

@app.post("/start_bot")
async def start_bot_endpoint():
    """Endpoint pour démarrer le bot."""
    global bot_running, bot_status
    if not bot_running:
        # Lancer la logique du bot dans une tâche séparée pour ne pas bloquer le serveur FastAPI
        asyncio.create_task(run_bot_logic())
        bot_status = "Démarrage en cours..."
        logger.info("Demande de démarrage du bot reçue.")
        return {"message": "Démarrage du bot demandé."}
    else:
        return {"message": "Le bot est déjà en cours d'exécution."}

@app.post("/stop_bot")
async def stop_bot_endpoint():
    """Endpoint pour arrêter le bot."""
    global bot_running, bot_status
    if bot_running:
        bot_running = False # Signale à la boucle de s'arrêter
        bot_status = "Arrêt en cours..."
        logger.info("Demande d'arrêt du bot reçue.")
        # Attendre un peu que la boucle se termine proprement (optionnel)
        # await asyncio.sleep(1) # Petite pause pour permettre à la tâche de s'arrêter
        return {"message": "Arrêt du bot demandé. Veuillez patienter."}
    else:
        return {"message": "Le bot est déjà arrêté."}

# --- INITIALISATION AU LANCEMENT ---
@app.on_event("startup")
async def startup_event():
    """Fonction appelée au démarrage de l'application FastAPI."""
    logger.info("Événement startup : Initialisation de la base de données...")
    initialize_database()
    logger.info("Moteur démarré avec capital actuel: {:.2f} $".format(current_capital))
    # Si vous souhaitez que le bot démarre automatiquement au lancement, décommentez la ligne suivante:
    # asyncio.create_task(run_bot_logic())
    # bot_status = "Démarrage automatique..." # Mettez à jour le statut si le démarrage est auto
