import ccxt
import logging
import os
from dotenv import load_dotenv # Assurez-vous que python-dotenv est installé (pip install python-dotenv)

# --- Configuration du logging ---
# Créez un fichier de log pour capturer les détails.
logging.basicConfig(
    level=logging.DEBUG,  # Capturez tous les niveaux de log, de DEBUG à CRITICAL
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"), # Nom du fichier de log
        logging.StreamHandler() # Affiche aussi les logs dans la console
    ]
)

# Obtenez un logger pour ce module
logger = logging.getLogger(__name__)

# Chargez les variables d'environnement à partir d'un fichier .env s'il existe
# C'est une bonne pratique, même si vous les avez définies ailleurs.
load_dotenv()

# --- Initialisation de l'échange ---
exchange_id = 'binance'
exchange_class = getattr(ccxt, exchange_id)

# Récupérez les clés API à partir des variables d'environnement
# Assurez-vous que ces variables sont correctement définies
api_key = os.environ.get('BINANCE_API_KEY')
secret_key = os.environ.get('BINANCE_SECRET_KEY')

logger.info(f"Tentative d'initialisation de l'échange : {exchange_id}")

try:
    # Vérifiez si les clés API sont présentes
    if not api_key or not secret_key:
        logger.error("Les clés API BINANCE_API_KEY et BINANCE_SECRET_KEY ne sont pas définies.")
        raise ValueError("Clés API manquantes pour Binance.")

    exchange = exchange_class({
        'apiKey': api_key,
        'secret': secret_key,
        # Options spécifiques à Binance si nécessaire, par exemple pour le mode futures
        # 'options': {
        #     'defaultType': 'spot', # 'spot', 'future', 'margin', 'delivery'
        # },
        # 'enableRateLimit': True, # Laissez ccxt gérer les limites de taux
    })
    logger.info("Échange ccxt initialisé avec succès.")

    # Optionnel : Chargez les marchés pour vérifier la connexion et l'authentification
    # Cela peut aussi lever des exceptions si les clés sont invalides ou si le réseau pose problème.
    logger.info("Tentative de chargement des marchés...")
    # Si vous utilisez le mode asynchrone, vous devrez adapter cette partie avec `await`
    # Pour un script synchrone, la ligne suivante est correcte.
    # Si vous utilisez le mode asynchrone, il faudrait utiliser `ccxt.async_support.binance`
    # et `await exchange.load_markets()` dans une fonction `async def`.
    markets = exchange.load_markets()
    logger.info("Marchés chargés avec succès.")
    logger.info(f"Connexion à {exchange_id} réussie. Nombre de marchés chargés : {len(markets)}")

except ccxt.AuthenticationError as e:
    logger.error(f"Erreur d'authentification CCXT: {e}. Vérifiez vos clés API.", exc_info=True)
    raise
except ccxt.PermissionDenied as e:
    logger.error(f"Permission refusée par CCXT: {e}. Vérifiez les permissions de vos clés API.", exc_info=True)
    raise
except ccxt.NetworkError as e:
    logger.error(f"Erreur réseau CCXT: {e}. Problème de connexion à l'échange.", exc_info=True)
    raise
except ccxt.ExchangeError as e:
    logger.error(f"Erreur d'échange CCXT: {e}. Problème spécifique à l'échange.", exc_info=True)
    raise
except ValueError as e: # Pour l'erreur de clés API manquantes
    logger.error(f"Erreur de configuration: {e}", exc_info=True)
    raise
except Exception as e:
    logger.error(f"Une erreur inattendue s'est produite lors de l'initialisation de l'échange: {e}", exc_info=True)
    raise

# --- Reste de votre code (par exemple, le démarrage du bot) ---
# Assurez-vous que le reste de votre code utilise l'objet 'exchange'
# et que toute fonction qui pourrait générer l'erreur "no such table: trades"
# est aussi enveloppée dans des blocs try...except si nécessaire.

# Exemple : Si votre fonction de récupération de trades est dans `get_trades()`
# def get_trades():
#     try:
#         trades = exchange.fetch_my_trades('BTC/USDT') # Exemple
#         logger.info(f"Récupération des trades réussie. Nombre de trades : {len(trades)}")
#         return trades
#     except Exception as e:
#         logger.error(f"Erreur lors de la récupération des trades : {e}", exc_info=True)
#         return []

# ...appel de get_trades() ailleurs dans votre code...

# Pour déclencher l'erreur "no such table: trades" :
# Si le bot essaie d'accéder à une table de base de données qui n'existe pas,
# c'est que l'initialisation a échoué, même si l'échange CCXT a pu s'initialiser.
# Cela pourrait venir de la logique interne du bot qui s'attend à une base de données.
# L'ajout de logs ici est aussi crucial.

# Si votre bot a une fonction `start_bot()` :
# def start_bot():
#     logger.info("Démarrage du bot...")
#     # ... votre logique de démarrage ...
#     try:
#         # Si une base de données est impliquée ici
#         # from your_db_module import initialize_db, get_trades_from_db
#         # initialize_db()
#         # trades_data = get_trades_from_db()
#         pass # Remplacez par votre logique réelle
#     except Exception as e:
#         logger.error(f"Erreur lors de l'initialisation de la base de données ou de la récupération des données : {e}", exc_info=True)

# start_bot()
