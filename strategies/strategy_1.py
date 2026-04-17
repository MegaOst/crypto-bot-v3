def check_entry_signal(df):
    """
    Vérifie le signal : 1+ chandelle rouge suivie de 2 vertes.
    """
    if len(df) < 3:
        return False
    
    c1 = df.iloc[-3]
    c2 = df.iloc[-2]
    c3 = df.iloc[-1]

    c1_is_red = c1['close'] < c1['open']
    c2_is_green = c2['close'] > c2['open']
    c3_is_green = c3['close'] > c3['open']

    if c1_is_red and c2_is_green and c3_is_green:
        return True
    return False

def check_exit_signal(current_price, entry_price, take_profit=0.01, stop_loss=0.005):
    """
    Vérifie si le TP (+1%) ou le SL (-0.5%) est atteint.
    """
    performance = (current_price - entry_price) / entry_price

    if performance >= take_profit:
        return "TAKE_PROFIT", performance
    elif performance <= -stop_loss:
        return "STOP_LOSS", performance
    
    return None, performance
