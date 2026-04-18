import requests
import logging

logger = logging.getLogger(__name__)

class MarketFetcher:
    def __init__(self):
        self.coingecko_api_url = "https://api.coingecko.com/api/v3/simple/price"
        logger.info("MarketFetcher initialisé avec l'API CoinGecko.")

    def get_current_price(self, symbol):
        """
        Récupère le prix actuel d'un symbole (e.g., 'bitcoin') en USDT depuis CoinGecko.
        Retourne le prix en float ou None en cas d'erreur.
        """
        if '/' in symbol:
            base_coin, quote_coin = symbol.split('/')
            if quote_coin.lower() != 'usdt':
                logger.warning(f"Seul USDT est supporté pour la conversion. Le symbole {symbol} sera traité comme base_coin.")
                # Dans ce cas, on cherche le prix de base_coin en USD (qui est généralement USDT)
            
            # CoinGecko attend les IDs des cryptos, pas les symboles comme BTC/USDT
            # Il faut mapper les symboles courants aux IDs CoinGecko
            coin_id_map = {
                "BTC": "bitcoin",
                "ETH": "ethereum",
                # Ajoutez d'autres cryptos ici si nécessaire
            }
            
            target_id = coin_id_map.get(base_coin.upper())
            if not target_id:
                logger.error(f"L'ID CoinGecko pour le symbole {base_coin} n'est pas défini.")
                return None

            params = {
                'ids': target_id,
                'vs_currencies': 'usd'
            }
            
            try:
                response = requests.get(self.coingecko_api_url, params=params, timeout=10) # Ajout d'un timeout
                response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP (4xx, 5xx)
                data = response.json()
                
                price = data.get(target_id, {}).get('usd')
                if price is not None:
                    return float(price)
                else:
                    logger.error(f"Prix non trouvé dans la réponse CoinGecko pour {target_id}.")
                    return None
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Erreur de requête API CoinGecko : {e}")
                return None
            except ValueError: # Si la réponse n'est pas du JSON valide
                logger.error("Réponse invalide reçue de l'API CoinGecko (pas du JSON).")
                return None
            except Exception as e:
                logger.error(f"Erreur inconnue lors de la récupération du prix : {type(e).__name__} - {e}")
                return None
        else:
            logger.error(f"Format de symbole invalide : {symbol}. Attendu 'BTC/USDT'.")
            return None

# --- Création d'une instance globale de MarketFetcher ---
# Cette instance sera importée par main.py
market_fetcher = MarketFetcher()
