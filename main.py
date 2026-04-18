# ... (début de main.py inchangé)

# --- Fonctions d'initialisation et d'arrêt du Bot ---

# Supprimez ou commentez initialize_exchange et close_exchange si ccxt n'est plus utilisé pour les prix
# Si vous prévoyez d'utiliser ccxt pour le trading réel PLUS TARD, gardez-les mais adaptez leur rôle.

# async def initialize_exchange():
#     # ... code inchangé pour CCXT ...

# async def close_exchange():
#     # ... code inchangé pour CCXT ...

# IMPORTEZ le nouveau market_fetcher
from core.market import market_fetcher 

# --- Logique Principale du Bot ---
async def run_bot_logic():
    """Boucle principale d'exécution du bot avec logs pour le debugging."""
    global bot_state

    # 1. Initialisation de la base de données au démarrage du bot
    init_db()

    # 2. Initialisation de l'échange CCXT (si nécessaire pour trading réel plus tard)
    # Si on utilise juste CoinGecko pour les prix, on peut sauter cette initialisation
    # Si vous voulez tester le trading réel avec Binance via CCXT, gardez-la.
    # Pour l'instant, je commente l'initialisation CCXT car on utilise CoinGecko pour le prix.
    # if not await initialize_exchange():
    #     logger.error("Impossible de démarrer le bot car l'échange n'a pas pu être initialisé.")
    #     bot_state["running"] = False
    #     return
    
    # Si on n'initialise pas CCXT, on doit s'assurer que bot_state["exchange"] est None ou géré différemment.
    bot_state["exchange"] = None # Assure que l'ancien échange CCXT n'est pas utilisé

    logger.info(f"Moteur démarré avec un capital de {bot_state['current_capital']:.2f} $ (simulation paper trading)")
    bot_state["status"] = "Actif" # Le bot est prêt à fonctionner

    while bot_state["running"]:
        try:
            # --- Récupération du prix via CoinGecko ---
            logger.debug("Tentative de récupération du prix BTC/USDT via CoinGecko...")
            # Utilisation du market_fetcher importé
            current_price = market_fetcher.get_current_price("BTC/USDT") 

            if current_price is None:
                logger.error("Impossible de récupérer le prix via CoinGecko. Le bot va attendre avant de réessayer.")
                bot_state["status"] = "Erreur Prix CoinGecko"
                # On pourrait ajouter un délai plus long ici en cas d'échec répété de la récupération prix
                await asyncio.sleep(10) # Pause plus longue si le prix n'est pas récupéré
                continue # Passe à l'itération suivante

            bot_state["current_price"] = current_price
            bot_state["status"] = "Actif" # S'assurer que le statut reste "Actif"
            bot_state["last_error"] = None # Efface les erreurs précédentes si la requête réussit
            logger.info(f"Prix BTC/USDT actuel : {bot_state['current_price']:.2f} $") # Log INFO pour le prix

            # ==========================================
            # 2. STRATÉGIE (Simulation d'achats/ventes)
            # ==========================================
            # ... Le reste de votre logique de stratégie reste le même ...
            # Vous pouvez choisir d'intégrer ici la stratégie_1.py si vous voulez

            if not bot_state["has_position"]:
                # Simulation d'un signal d'achat
                logger.info(f"🚀 Signal d'ACHAT détecté ! Préparation achat à {bot_state['current_price']:.2f} $")
                bot_state["buy_price"] = bot_state["current_price"]
                bot_state["has_position"] = True
                log_trade("ACHAT", bot_state["current_price"]) # Log le trade en base de données
                
            elif bot_state["has_position"] and bot_state["current_price"] > bot_state["buy_price"] * 1.01:
                # Simulation de vente si +1% de profit
                profit = bot_state["current_price"] - bot_state["buy_price"]
                bot_state["current_capital"] += profit
                log_trade("VENTE", bot_state["current_price"], profit) # Log le trade en base de données
                logger.info(f"📉 Signal de VENTE détecté ! Vente à {bot_state['current_price']:.2f} $ | Profit: {profit:.2f} $")
                bot_state["has_position"] = False
                bot_state["buy_price"] = 0.0
                bot_state["current_capital"] = round(bot_state["current_capital"], 2) # Arrondir le capital

            # ==========================================

        # --- Gestion des erreurs ---
        # Supprimez les blocs d'erreur spécifiques à CCXT si vous ne l'utilisez plus pour les prix.
        # Gardez les erreurs générales pour les autres parties si nécessaire.
        # except ccxt.NetworkError as e: ...
        # except ccxt.ExchangeError as e: ...
        
        except Exception as e:
            error_msg = f"Erreur inconnue dans la boucle du bot : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur inconnue"
            await asyncio.sleep(5) # Pause avant de continuer
            
        # Attend avant la prochaine itération si le bot tourne
        if bot_state["running"]:
            await asyncio.sleep(5) # Intervalle entre chaque vérification de prix

    # Le bot s'arrête ici proprement
    logger.info("Moteur du bot arrêté (boucle 'while bot_state[\"running\"]' terminée).")
    bot_state["status"] = "Arrêté"
    # Si vous utilisez CCXT pour le trading réel, appelez close_exchange() ici.
    # Si on n'utilise CCXT que pour les prix, on n'a pas besoin de close_exchange() car on utilise requests.
    # await close_exchange() 
    logger.info("Moteur arrêté. Connexion CCXT (si utilisée) fermée.")
