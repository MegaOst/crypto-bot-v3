import ccxt
import time
import os
from datetime import datetime, timedelta

# --- Configuration ---
# Récupérer les clés API de Binance depuis les variables d'environnement
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY')

# Vérification des clés API
if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
    print("Erreur critique : Les clés API Binance (BINANCE_API_KEY, BINANCE_SECRET_KEY) ne sont pas configurées dans les variables d'environnement.")
    print("Veuillez vous assurer que ces variables sont définies sur votre plateforme de déploiement.")
    # Pour un test local temporaire SANS PUSH EN PRODUCTION, vous pourriez faire :
    # BINANCE_API_KEY = "VOTRE_API_KEY_BINANCE_TEST"
    # BINANCE_SECRET_KEY = "VOTRE_SECRET_KEY_BINANCE_TEST"
    # MAIS NE JAMAIS FAIRE CECI POUR UN DEPLOIEMENT REEL.
    exit() # Arrête le script si les clés ne sont pas trouvées

# Paramètres de trading
SYMBOL = 'BTC/USDT' # Le symbole que nous allons trader (Bitcoin contre Tether)
INTERVAL = '15m'    # L'intervalle de temps pour les chandeliers (15 minutes)
TRADE_AMOUNT_BTC = 0.001 # Montant de BTC à trader par transaction (ajuster selon votre capital et risque)
# IMPORTANT: Pour du trading réel, ce montant doit être défini prudemment.
# Il est préférable de calculer cela dynamiquement en fonction de votre capital disponible.

# --- Initialisation de l'échange Binance via ccxt ---
def initialize_binance_exchange(api_key, secret_key):
    """
    Initialise la connexion à l'échange Binance en utilisant ccxt.
    Inclut les clés API pour des appels plus fiables et potentiellement pour le trading.
    Utilise le endpoint de l'API des futures pour une meilleure précision, sinon le spot.
    """
    try:
        # Tente d'initialiser avec le endpoint des Futures si disponible/souhaité, sinon utilise le Spot
        # Pour des raisons de simplicité et compatibilité, on reste sur le Spot ici.
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret_key,
            'enableRateLimit': True, # Respecter les limites de taux de l'API Binance
            'options': {
                'defaultType': 'spot', # 'spot' ou 'future'
            },
        })
        print("Connexion à Binance initialisée avec succès.")
        return exchange
    except Exception as e:
        print(f"Erreur lors de l'initialisation de Binance : {e}")
        return None

# --- Fonctions utilitaires et de trading ---

def fetch_ohlcv(exchange, symbol, interval, limit=100):
    """
    Récupère les données OHLCV (Open, High, Low, Close, Volume) pour un symbole donné.
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, interval, limit=limit)
        # ccxt renvoie les données dans cet ordre : [timestamp, open, high, low, close, volume]
        # Le timestamp est en millisecondes
        return ohlcv
    except ccxt.NetworkError as e:
        print(f"Erreur réseau lors de la récupération des données OHLCV : {e}")
        return None
    except ccxt.ExchangeError as e:
        print(f"Erreur d'échange lors de la récupération des données OHLCV : {e}")
        return None
    except Exception as e:
        print(f"Erreur inattendue lors de la récupération des données OHLCV : {e}")
        return None

def calculate_moving_averages(ohlcv_data, short_window=10, long_window=30):
    """
    Calcule les moyennes mobiles courtes et longues à partir des données OHLCV.
    Retourne les deux dernières valeurs calculées pour les moyennes mobiles.
    """
    if not ohlcv_data or len(ohlcv_data) < long_window:
        return None, None # Pas assez de données pour calculer les moyennes

    closes = [candle[4] for candle in ohlcv_data] # Candle[4] est le prix de clôture

    # Calcul de la moyenne mobile courte
    short_ma = sum(closes[-short_window:]) / short_window

    # Calcul de la moyenne mobile longue
    long_ma = sum(closes[-long_window:]) / long_window

    return short_ma, long_ma

def trading_logic_sma(ohlcv_data, short_ma_prev, long_ma_prev, short_ma_curr, long_ma_curr):
    """
    Logique de trading simple basée sur le croisement des moyennes mobiles.
    Retourne un signal : 'BUY', 'SELL', ou None.
    """
    if short_ma_curr is None or long_ma_curr is None:
        return None # Pas assez de données pour la logique

    # Signal d'achat : La moyenne mobile courte croise au-dessus de la moyenne mobile longue
    if short_ma_prev is not None and long_ma_prev is not None:
        if short_ma_prev <= long_ma_prev and short_ma_curr > long_ma_curr:
            return 'BUY'
        # Signal de vente : La moyenne mobile courte croise en dessous de la moyenne mobile longue
        if short_ma_prev >= long_ma_prev and short_ma_curr < long_ma_curr:
            return 'SELL'

    return None # Pas de signal

def execute_trade(exchange, signal, symbol, amount):
    """
    Exécute un trade (achat ou vente) sur l'échange.
    NOTE: Cette fonction est configurée pour SIMULER les trades.
          Pour trader réellement, vous devez décommenter les lignes ccxt et ajuster les paramètres.
    """
    if signal == 'BUY':
        print(f"--- Signal d'ACHAT détecté pour {symbol} ---")
        # Pour un trade réel, décommentez la ligne suivante :
        # try:
        #     order = exchange.create_market_buy_order(symbol, amount)
        #     print(f"Ordre d'achat exécuté : {order}")
        # except Exception as e:
        #     print(f"Erreur lors de l'exécution de l'ordre d'achat : {e}")

        # Simulation pour l'instant :
        print(f"SIMULATION : Achat de {amount} {symbol.split('/')[0]} à prix de marché.")
        # Vous pouvez ajouter ici un enregistrement dans un fichier log ou une base de données.

    elif signal == 'SELL':
        print(f"--- Signal de VENTE détecté pour {symbol} ---")
        # Pour un trade réel, décommentez la ligne suivante :
        # try:
        #     order = exchange.create_market_sell_order(symbol, amount)
        #     print(f"Ordre de vente exécuté : {order}")
        # except Exception as e:
        #     print(f"Erreur lors de l'exécution de l'ordre de vente : {e}")

        # Simulation pour l'instant :
        print(f"SIMULATION : Vente de {amount} {symbol.split('/')[0]} à prix de marché.")
        # Vous pouvez ajouter ici un enregistrement dans un fichier log ou une base de données.
    else:
        print("Aucun signal de trading détecté.")

# --- Boucle Principale du Bot ---
def run_trading_bot():
    """
    Fonction principale qui exécute le bot de trading en continu.
    """
    exchange = initialize_binance_exchange(BINANCE_API_KEY, BINANCE_SECRET_KEY)
    if not exchange:
        print("Arrêt du bot en raison d'une erreur d'initialisation.")
        return

    print(f"Bot de trading démarré. Symbole: {SYMBOL}, Intervalle: {INTERVAL}")
    print("Attente de la prochaine bougie...")

    # Variables pour conserver les moyennes mobiles précédentes pour la logique de croisement
    short_ma_prev = None
    long_ma_prev = None

    while True:
        try:
            # 1. Récupérer les données OHLCV
            # Nous avons besoin d'au moins 'long_window' bougies pour le calcul des moyennes.
            # Ajoutons une petite marge pour s'assurer d'avoir suffisamment de données.
            ohlcv_data = fetch_ohlcv(exchange, SYMBOL, INTERVAL, limit=100) # Récupère les 100 dernières bougies

            if ohlcv_data and len(ohlcv_data) >= 30: # S'assurer qu'on a assez de données pour la moyenne longue
                current_candle_timestamp_ms = ohlcv_data[-1][0]
                current_candle_dt = datetime.fromtimestamp(current_candle_timestamp_ms / 1000)

                # Calculer les moyennes mobiles actuelles
                short_ma_curr, long_ma_curr = calculate_moving_averages(ohlcv_data, short_window=10, long_window=30)

                # Déterminer le signal de trading
                signal = trading_logic_sma(ohlcv_data, short_ma_prev, long_ma_prev, short_ma_curr, long_ma_curr)

                # Si un signal est trouvé, exécuter le trade
                if signal:
                    print(f"Heure actuelle de la bougie : {current_candle_dt}")
                    print(f"Moyenne courte actuelle : {short_ma_curr:.4f}, Moyenne longue actuelle : {long_ma_curr:.4f}")
                    execute_trade(exchange, signal, SYMBOL, TRADE_AMOUNT_BTC)
                    # Après un trade, il est prudent de réinitialiser les moyennes précédentes
                    # pour éviter des signaux multiples sur la même tendance.
                    # Ou ajuster la logique pour gérer les états (déjà acheté, déjà vendu).
                    short_ma_prev = short_ma_curr
                    long_ma_prev = long_ma_curr
                else:
                    # Si aucun signal, simplement mettre à jour les moyennes précédentes pour la prochaine itération
                    short_ma_prev = short_ma_curr
                    long_ma_prev = long_ma_curr
                    print(f"Heure actuelle de la bougie : {current_candle_dt} - Pas de signal. Moyennes : SC={short_ma_curr:.4f}, SL={long_ma_curr:.4f}")


                # Calculer le temps d'attente jusqu'à la fin de la bougie actuelle
                # Cela garantit que nous n'analysons pas des données partielles et que nous agissons sur des bougies complètes.
                time_to_wait = 0
                if INTERVAL == '15m':
                    now = datetime.utcnow()
                    # Le timestamp de la dernière bougie est le début de cette bougie.
                    # On ajoute 15 minutes pour obtenir le début de la *prochaine* bougie.
                    next_candle_start_dt = current_candle_dt + timedelta(minutes=15)
                    # Calculer la différence en secondes
                    time_to_wait = (next_candle_start_dt - now).total_seconds()
                    # S'assurer que le temps d'attente est positif (pas dans le passé)
                    if time_to_wait < 0:
                         time_to_wait = 1 # Petite pause si on est légèrement en retard

                elif INTERVAL == '1h': # Exemple pour '1h'
                    now = datetime.utcnow()
                    next_candle_start_dt = current_candle_dt + timedelta(hours=1)
                    time_to_wait = (next_candle_start_dt - now).total_seconds()
                    if time_to_wait < 0:
                         time_to_wait = 1

                # Ajoutez d'autres conditions pour d'autres intervalles si nécessaire

                if time_to_wait > 0:
                    print(f"Attente de {time_to_wait:.2f} secondes jusqu'à la fin de la bougie...")
                    time.sleep(time_to_wait)
                else: # Si on est déjà en retard ou si le calcul est bizarre, on fait une pause courte
                    time.sleep(10) # Pause de 10 secondes

            else:
                print("Pas assez de données OHLCV récupérées ou erreur de récupération. Réessai dans 60 secondes.")
                time.sleep(60) # Attendre avant de réessayer si les données sont insuffisantes

        except KeyboardInterrupt:
            print("\nArrêt manuel du bot...")
            break
        except Exception as e:
            print(f"Une erreur s'est produite dans la boucle principale : {e}")
            print("Redémarrage de la boucle dans 60 secondes...")
            time.sleep(60) # Attendre avant de réessayer en cas d'erreur inattendue

# --- Point d'entrée du script ---
if __name__ == "__main__":
    run_trading_bot()
