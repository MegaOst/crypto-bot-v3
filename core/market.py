# core/market.py

import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("Market")

# --- Configuration CoinGecko ---
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
# Vous pouvez définir ici les symboles que vous souhaitez suivre
# Assurez-vous que les IDs correspondent à ceux utilisés par CoinGecko
SUPPORTED_ASSETS = {
    "BTC/USDT": "bitcoin", # L'ID de Bitcoin sur CoinGecko
    "ETH/USDT": "ethereum" # L'ID d'Ethereum sur CoinGecko
}

class MarketDataFetcher:
    def __init__(self):
        self.last_price_data = {} # Pour stocker les derniers prix récupérés
        logger.info("Fetcher de données de marché initialisé.")

    def get_current_price(self, symbol="BTC/USDT"):
        """
        Récupère le prix actuel d'un actif via l'API CoinGecko.
        Retourne le prix en float, ou None en cas d'erreur.
        """
        if symbol not in SUPPORTED_ASSETS:
            logger.warning(f"Le symbole {symbol} n'est pas supporté pour la récupération de prix.")
            return None

        coin_id = SUPPORTED_ASSETS[symbol]
        api_endpoint = f"{COINGECKO_API_URL}/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": "usd"
        }

        try:
            logger.debug(f"Requête API CoinGecko pour le prix de {coin_id}...")
            response = requests.get(api_endpoint, params=params)
            response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)
            data = response.json()

            if coin_id in data and "usd" in data[coin_id]:
                price = float(data[coin_id]["usd"])
                self.last_price_data[symbol] = {"price": price, "timestamp": datetime.now()}
                logger.info(f"Prix de {symbol} récupéré : {price:.2f} $")
                return price
            else:
                logger.error(f"Réponse inattendue de CoinGecko pour {coin_id}: {data}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur lors de la requête à l'API CoinGecko pour {coin_id}: {e.__class__.__name__} - {e}")
            return None
        except Exception as e:
            logger.error(f"Erreur inattendue lors de la récupération du prix de {coin_id}: {e.__class__.__name__} - {e}")
            return None

    # Vous pouvez ajouter ici une fonction pour récupérer les données OHLCV si nécessaire
    # def fetch_ohlcv(self, symbol, interval='15m', limit=100):
    #     """
    #     Récupère les données OHLCV (Open, High, Low, Close, Volume) pour un symbole donné.
    #     """
    #     if symbol not in SUPPORTED_ASSETS:
    #         logger.warning(f"Le symbole {symbol} n'est pas supporté pour la récupération OHLCV.")
    #         return []
        
    #     coin_id = SUPPORTED_ASSETS[symbol]
    #     # CoinGecko's /coins/{id}/market_chart API returns data in a specific format
    #     # The 'interval' parameter is not directly supported like in CCXT.
    #     # We need to calculate the timestamp for 'days' based on the interval.
    #     # For example, 15m interval over 100 candles would be roughly 100 * 15m = 1500 minutes = 25 hours.
    #     # This part requires careful calculation of 'days' parameter for the API.
    #     # For simplicity, let's fetch daily data for now and explain how to adapt if needed.
        
    #     # CoinGecko's market_chart is for price, volume, and market_cap over time.
    #     # It doesn't directly give OHLCV bars in the same way as exchange APIs.
    #     # If OHLCV is strictly needed, an exchange API (like CCXT) is usually better.
    #     # For this example, we'll focus on the current price as the primary need.
        
    #     # If you ABSOLUTELY need OHLCV for CoinGecko, you might need to:
    #     # 1. Fetch daily data and try to interpolate/calculate for 15m (complex and less accurate)
    #     # 2. Use a different API source for OHLCV if CoinGecko doesn't provide it granularly.
    #     # For now, let's stick to `get_current_price`.
    #     logger.warning("La récupération OHLCV via CoinGecko n'est pas directement supportée comme avec les APIs d'échange. Utilisation de get_current_price.")
    #     return [] # Retourne une liste vide pour signaler que OHLCV n'est pas géré ici

# --- Instanciation pour être utilisée globalement (ou passée en argument) ---
market_fetcher = MarketDataFetcher()

# Exemple d'utilisation (pour test)
if __name__ == "__main__":
    print("Test de la récupération de prix...")
    btc_price = market_fetcher.get_current_price("BTC/USDT")
    if btc_price:
        print(f"Prix actuel de BTC/USDT : {btc_price:.2f} $")
    else:
        print("Impossible de récupérer le prix de BTC/USDT.")
        
    eth_price = market_fetcher.get_current_price("ETH/USDT")
    if eth_price:
        print(f"Prix actuel de ETH/USDT : {eth_price:.2f} $")
    else:
        print("Impossible de récupérer le prix de ETH/USDT.")
