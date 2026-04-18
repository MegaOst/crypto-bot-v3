import httpx # Assurez-vous que httpx est installé: pip install httpx
import os
import logging

logger = logging.getLogger(__name__)

# --- Récupération de la clé API ---
# Essayer de récupérer la clé API depuis les variables d'environnement
COINGECKO_API_KEY = os.environ.get('COINGECKO_API_KEY')
if COINGECKO_API_KEY:
    logger.info("Clé API CoinGecko trouvée. Utilisation de l'API authentifiée.")
else:
    # Si pas de clé, on log un warning et on s'assure que les appels respectent les limites publiques
    logger.warning("Clé API CoinGecko non trouvée. Utilisation de l'API publique gratuite. Les limites de taux peuvent s'appliquer.")

# --- Configuration de l'URL de base pour CoinGecko ---
# La plupart des endpoints de l'API CoinGecko sont sur la même base
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"

async def get_current_price(coin_id: str = "bitcoin", vs_currency: str = "usd") -> float | None:
    """
    Récupère le prix actuel d'une crypto-monnaie par rapport à une autre devise depuis CoinGecko.
    Utilise la clé API si disponible.
    """
    # --- Construction de l'URL de l'endpoint ---
    # Endpoint pour obtenir le prix simple
    endpoint = f"/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": vs_currency,
    }

    headers = {}
    # --- Ajout de la clé API dans les headers si elle existe ---
    if COINGECKO_API_KEY:
        # Selon la documentation CoinGecko, la clé API est envoyée dans le header 'x-cg-demo-api-key'
        # ou un header similaire selon le plan. Pour les plans payants, c'est souvent
        # 'x-api-key' ou via un paramètre 'x_cg_api_key'. 
        # Vérifiez la documentation de VOTRE plan CoinGecko API.
        # L'exemple ci-dessous utilise 'x-cg-demo-api-key' comme dans les démos CoinGecko,
        # mais il est très probable que vous deviez utiliser 'x-api-key' ou similaire pour un plan payant.
        # FAITES CETTE VÉRIFICATION : https://www.coingecko.com/en/api/documentation
        
        # Exemple d'utilisation d'une clé API (adaptez le nom du header si nécessaire)
        # Pour un plan standard ou pro, le header est souvent 'x-api-key'
        headers['x-api-key'] = COINGECKO_API_KEY 
        # Si votre plan utilise un autre nom de header ou un paramètre, adaptez ici.
        # Par exemple, pour certains plans, ce serait : params['x_cg_api_key'] = COINGECKO_API_KEY

    try:
        # Utilisation de httpx pour faire la requête asynchrone
        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.get(f"{COINGECKO_API_URL}{endpoint}", params=params)
            response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)

        data = response.json()

        # --- Extraction du prix ---
        price = data.get(coin_id, {}).get(vs_currency)

        if price is not None:
            logger.debug(f"Prix récupéré pour {coin_id}/{vs_currency}: {price}")
            return float(price)
        else:
            logger.warning(f"Impossible de trouver le prix pour {coin_id}/{vs_currency} dans la réponse : {data}")
            return None

    except httpx.HTTPStatusError as e:
        # Si la réponse est un 429 (Too Many Requests)
        if e.response.status_code == 429:
            logger.error(f"Erreur de requête API CoinGecko : Trop de requêtes (429). URL: {e.request.url}")
            # Ici, vous pouvez implémenter une logique de retry plus avancée si besoin
            # Si une clé API est configurée, cela signifie qu'elle est peut-être limitée aussi, 
            # ou que vous dépassez même les limites du plan.
            # Si pas de clé API, c'est la limite de l'API publique.
        else:
            logger.error(f"Erreur de requête API CoinGecko : {e.response.status_code} {e.response.reason_phrase} for url: {e.request.url}")
        return None
    except httpx.RequestError as e:
        logger.error(f"Erreur de requête réseau vers CoinGecko : {e} for url: {e.request.url}")
        return None
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la récupération du prix CoinGecko : {e}")
        return None

# --- Assurez-vous que d'autres parties de votre code qui appellent cette fonction
# --- sont préparées à recevoir `None` et à gérer les délais en conséquence. ---
