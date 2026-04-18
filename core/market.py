import ccxt.async_support as ccxt
import logging

logger = logging.getLogger(__name__)

# --- Initialisation de l'échange ---
# Vous pouvez choisir l'échange que vous préférez (e.g., 'binance', 'kraken', etc.)
# Assurez-vous que l'échange est supporté par ccxt
exchange_id = 'binance'
exchange_class = getattr(ccxt, exchange_id)
exchange = exchange_class()

async def get_current_price(symbol: str):
    """
    Récupère le dernier prix d'une paire de trading sur l'échange spécifié.
    :param symbol: La paire de trading (ex: 'BTC/USDT').
    :return: Un dictionnaire contenant le dernier prix, ou None en cas d'erreur.
    """
    logger.info(f"Tentative de récupération du prix pour {symbol} sur {exchange_id}...")
    try:
        # Exemple: 'BTC/USDT'
        ticker = await exchange.fetch_ticker(symbol)
        logger.debug(f"Ticker pour {symbol}: {ticker}")
        # La clé 'last' contient généralement le dernier prix de transaction
        return {"symbol": symbol, "last": ticker.get('last')}
    except ccxt.NetworkError as e:
        logger.error(f"Erreur réseau CCXT lors de la récupération du prix pour {symbol}: {e}")
        return None
    except ccxt.ExchangeError as e:
        logger.error(f"Erreur d'échange CCXT lors de la récupération du prix pour {symbol}: {e}")
        return None
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la récupération du prix pour {symbol}: {e}", exc_info=True)
        return None
    finally:
        # Il est bon de fermer la connexion si vous ne réutilisez pas l'instance de manière persistante
        # Cependant, pour un serveur d'application qui tourne longtemps, la garder ouverte est souvent mieux
        # Si vous rencontrez des problèmes de connexion, une fermeture et réouverture pourrait aider
        # await exchange.close() # Décommenter si nécessaire
        pass

# Assurez-vous de fermer l'échange proprement à la fin de l'application si elle est gérée par vous
# Si uvicorn gère le cycle de vie, cela peut ne pas être nécessaire ici directement
# async def close_exchange():
#     await exchange.close()

# Pour tester localement :
# async def main():
#     price_data = await get_current_price("BTC/USDT")
#     if price_data:
#         print(f"Le dernier prix de BTC/USDT est : {price_data['last']}")
#     else:
#         print("Impossible de récupérer le prix.")

# if __name__ == "__main__":
#     asyncio.run(main())
