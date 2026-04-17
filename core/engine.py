class PaperTradingEngine:
    def __init__(self, initial_capital=1000):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.position = None
        self.trade_history = []
    
    def buy(self, asset, price, time):
        if self.position is None:
            amount = self.capital / price
            self.position = {
                "asset": asset,
                "entry_price": price,
                "amount": amount,
                "time": time
            }
            print(f"[{time}] ACHAT {asset} à {price}$")

    def sell(self, price, time, reason):
        if self.position:
            profit = (price - self.position['entry_price']) / self.position['entry_price']
            self.capital = self.position['amount'] * price
            
            trade = {
                "asset": self.position['asset'],
                "entry_price": self.position['entry_price'],
                "exit_price": price,
                "profit_pct": profit * 100,
                "reason": reason,
                "entry_time": self.position['time'],
                "exit_time": time,
                "new_capital": self.capital
            }
            self.trade_history.append(trade)
            self.position = None
            print(f"[{time}] VENTE ({reason}) à {price}$ | P&L: {profit*100:.2f}% | Capital: {self.capital:.2f}$")

    def get_stats(self):
        trades = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t['profit_pct'] > 0)
        win_rate = (wins / trades * 100) if trades > 0 else 0
        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.capital,
            "total_trades": trades,
            "win_rate": win_rate,
            "history": self.trade_history
        }
