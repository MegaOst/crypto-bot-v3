import logging

# Configuration du logger pour ce fichier
logger = logging.getLogger("Engine")

class PaperTradingEngine:
    def __init__(self, initial_capital=1000):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position = None
        self.trade_history = []
        logger.info(f"Moteur initialisé avec un capital de {self.initial_capital}$")
    
    def buy(self, asset, price, time):
        if self.position is None:
            amount = self.capital / price
            self.position = {
                "asset": asset,
                "entry_price": price,
                "amount": amount,
                "time": time
            }
            logger.info(f"🟢 ACHAT {asset} à {price}$ | Montant: {amount:.4f}")

    def sell(self, price, time, reason="SIGNAL"):
        if self.position is not None:
            profit = (price - self.position['entry_price']) / self.position['entry_price']
            self.capital = self.position['amount'] * price
            
            self.trade_history.append({
                "asset": self.position['asset'],
                "entry_price": self.position['entry_price'],
                "exit_price": price,
                "entry_time": self.position['time'],
                "exit_time": time,
                "profit_pct": profit,
                "reason": reason
            })
            
            icon = "🔴" if profit < 0 else "🔵"
            logger.info(f"{icon} VENTE {self.position['asset']} à {price}$ | Raison: {reason} | P&L: {profit*100:.2f}% | Capital: {self.capital:.2f}$")
            self.position = None

    def get_stats(self):
        wins = [t for t in self.trade_history if t['profit_pct'] > 0]
        win_rate = (len(wins) / len(self.trade_history) * 100) if self.trade_history else 0
        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.capital,
            "total_trades": len(self.trade_history),
            "win_rate": win_rate
        }
