from typing import Optional
import numpy as np

def ema(values, period: int):
    arr = np.asarray(values, dtype=float)
    if len(arr) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    out = float(arr[0])
    for value in arr[1:]:
        out = alpha * float(value) + (1.0 - alpha) * out
    return out

def rsi(values, period: int = 14) -> Optional[float]:
    arr = np.asarray(values, dtype=float)
    if len(arr) < period + 1:
        return None
    changes = np.diff(arr)
    gains = np.clip(changes, 0, None)
    losses = np.clip(-changes, 0, None)
    avg_gain = float(np.mean(gains[-period:]))
    avg_loss = float(np.mean(losses[-period:]))
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def atr(highs, lows, closes, period: int = 14) -> Optional[float]:
    h, l, c = map(lambda x: np.asarray(x, dtype=float), (highs, lows, closes))
    if len(c) < period + 1:
        return None
    prev = c[:-1]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - prev), np.abs(l[1:] - prev)))
    return float(np.mean(tr[-period:]))

def build_signal(candles, config):
    """Return a scored BUY/SELL setup or None. This is a rules-based research signal, not advice."""
    closes = [x["close"] for x in candles]
    highs = [x["high"] for x in candles]
    lows = [x["low"] for x in candles]
    fast_n = int(config["ema_fast"])
    slow_n = int(config["ema_slow"])
    rsi_n = int(config["rsi_period"])
    atr_n = int(config["atr_period"])
    if len(closes) < max(slow_n, rsi_n + 1, atr_n + 1) + 2:
        return None

    fast = ema(closes, fast_n)
    slow = ema(closes, slow_n)
    momentum = rsi(closes, rsi_n)
    volatility = atr(highs, lows, closes, atr_n)
    if None in (fast, slow, momentum, volatility) or volatility <= 0:
        return None

    last = float(closes[-1])
    prior = float(closes[-2])
    score_buy = 0
    score_sell = 0

    if fast > slow:
        score_buy += 1
    elif fast < slow:
        score_sell += 1

    if last > fast:
        score_buy += 1
    elif last < fast:
        score_sell += 1

    if 50 <= momentum <= 68:
        score_buy += 1
    elif 32 <= momentum <= 50:
        score_sell += 1

    if last > prior:
        score_buy += 1
    elif last < prior:
        score_sell += 1

    threshold = int(config.get("minimum_confluence", 3))
    direction = "BUY" if score_buy >= threshold and score_buy > score_sell else (
        "SELL" if score_sell >= threshold and score_sell > score_buy else None
    )
    if not direction:
        return None

    stop_distance = volatility * float(config["stop_atr_multiple"])
    sign = 1 if direction == "BUY" else -1
    entry = last
    stop = entry - sign * stop_distance
    t1 = entry + sign * stop_distance * float(config["target_1_r"])
    t2 = entry + sign * stop_distance * float(config["target_2_r"])
    return {
        "direction": direction, "score": max(score_buy, score_sell),
        "entry": entry, "stop": stop, "target1": t1, "target2": t2,
        "rsi": momentum, "ema_fast": fast, "ema_slow": slow,
        "atr": volatility, "timestamp": candles[-1]["timestamp"]
    }
