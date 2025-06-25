import math
import os
import json
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas_market_calendars as mcal

# === CONFIG ===
from dotenv import dotenv_values

CONFIG_DEFAULT = dict(
    ICLI_IBKR_HOST="127.0.0.1", ICLI_IBKR_PORT=4001, ICLI_REFRESH=3.33
)
CONFIG = {**CONFIG_DEFAULT, **dotenv_values(".env.icli"), **os.environ}

# Create the bot
API_KEY: str = CONFIG["POLYGON_API_KEY"]

BASE_URL = "https://api.polygon.io"
CACHE_DIR = Path("store")
CACHE_DIR.mkdir(exist_ok=True)

# === UTILITY FUNCTIONS ===

nyse = mcal.get_calendar('NYSE')

def is_market_holiday(date):
    schedule = nyse.schedule(start_date=date.strftime('%Y-%m-%d'), end_date=date.strftime('%Y-%m-%d'))
    # print(f"{schedule.empty}")
    return schedule.empty


def fetch_json(url, params=None, cache_name=None, force_refresh=False):
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if not params:
        params = {}
    params["apiKey"] = API_KEY

    if cache_name:
        cache_file = CACHE_DIR / f"{cache_name}.json"
        if cache_file.exists() and not force_refresh:
            with open(cache_file) as f:
                return json.load(f)

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    if cache_name:
        with open(cache_file, "w") as f:
            json.dump(data, f)

    return data

def get_stock_5min_bars(symbol, from_date, to_date):
    all_bars = []
    current = from_date
    while current <= to_date:
        if is_market_holiday(current):
            current += timedelta(days=1)
            continue

        date_str = current.strftime("%Y-%m-%d")
        file = CACHE_DIR / f"{symbol}_{date_str}_5min.pkl"
        if file.exists():
            # print(f"loading {symbol} bars from cache for {date_str}")
            daily_df = pd.read_pickle(file)
        else:
            url = f"{BASE_URL}/v2/aggs/ticker/{symbol}/range/5/minute/{date_str}/{date_str}"
            data = fetch_json(url, cache_name=f"{symbol}_{date_str}_5min")
            bars = []
            if "results" in data:
                for bar in data["results"]:
                    bar_time = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
                    bars.append({
                        "timestamp": bar_time,
                        "open": bar["o"],
                        "high": bar["h"],
                        "low": bar["l"],
                        "close": bar["c"],
                        "volume": bar["v"]
                    })
            daily_df = pd.DataFrame(bars).set_index("timestamp")
            daily_df.index = daily_df.index.tz_convert("America/New_York")
            daily_df.to_pickle(file)

        all_bars.append(daily_df)
        current += timedelta(days=1)

    df = pd.concat(all_bars)
    df = df.between_time("09:30", "16:00")
    return df

def detect_orb_signal(df_day):
    if len(df_day) < 2:
        return None

    opening_candle = df_day.iloc[0]
    high = opening_candle["high"]
    low = opening_candle["low"]

    for i in range(1, len(df_day)):
        candle = df_day.iloc[i]
        if candle["open"] > high and candle["close"] > high:
            return ("CALL", candle.name, high, low)
        elif candle["open"] < low and candle["close"] < low:
            return ("PUT", candle.name, high, low)
    return None

def get_options_chain(symbol, date):
    date_str = date.strftime("%Y-%m-%d")
    cache_file = CACHE_DIR / f"{symbol}_chain_{date_str}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            return json.load(f).get("results", [])

    url = f"{BASE_URL}/v3/reference/options/contracts"
    params = {
        "underlying_ticker": symbol,
        "as_of": date_str,
        "limit": 1000
    }
    data = fetch_json(url, params=params, cache_name=f"{symbol}_chain_{date_str}")
    return data.get("results", [])

def get_option_5min_bars(option_ticker, date):
    if is_market_holiday(date):
        return

    date_str = date.strftime("%Y-%m-%d")
    file = CACHE_DIR / f"{option_ticker}_{date_str}_5min.pkl"
    if file.exists():
        # print("loading option bars from cache")
        return pd.read_pickle(file).between_time("09:30", "16:00")

    url = f"{BASE_URL}/v2/aggs/ticker/{option_ticker}/range/5/minute/{date_str}/{date_str}"
    data = fetch_json(url, cache_name=f"{option_ticker}_{date_str}_bars")
    bars = []
    if "results" in data:
        for bar in data["results"]:
            bar_time = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
            bars.append({
                "timestamp": bar_time,
                "open": bar["o"],
                "high": bar["h"],
                "low": bar["l"],
                "close": bar["c"],
                "volume": bar["v"]
            })
    df = pd.DataFrame(bars).set_index("timestamp")
    df.index = df.index.tz_convert("America/New_York")
    df = df.between_time("09:30", "16:00")
    df.to_pickle(file)
    return df

def simulate_trade(contracts_total, option_df, stock_df, entry_time, entry_price, direction, day_high, day_low):
    contracts_remaining = contracts_total
    contract_multiplier = 100
    state = "L0"
    peak = entry_price
    log = []
    prevrow = None
    for time, row in option_df.loc[entry_time:].iterrows():
        price = (row['open'] + row['close'])/ 2
        frame = stock_df.loc[time]
        # print (frame.keys())
        # print("%s %f %f %f %f %f %f %f %f" % (time, frame['open'], frame['high'], frame['low'], frame['close'], row['open'], row['high'], row['low'], row['close']))
        if prevrow is not None :
            if ((direction == 'CALL' and prevrow["close"] < day_high and prevrow["open"] < day_high) or (price < entry_price *.8)) and state=="L0":
                cost = entry_price * contracts_remaining
                soldmkt = price * contracts_remaining
                log.append((time, 'stock SL', price, contracts_remaining, 0, soldmkt, cost, soldmkt - cost))
                contracts_remaining = 0
                state = "Z"
                break
            elif ((direction == 'PUT' and prevrow["close"] > day_low and prevrow["open"] > day_low) or (price < entry_price *.8)) and state=="L0":
                cost = entry_price * contracts_remaining
                soldmkt = price * contracts_remaining
                log.append((time, 'stock SL', price, contracts_remaining, 0, soldmkt, cost, soldmkt - cost))
                contracts_remaining = 0
                state = "Z"
                break

        if contracts_remaining == contracts_total and price >= 1.3 * entry_price and state=="L0":
            cost = entry_price * (contracts_remaining//2)
            soldmkt = price * (contracts_remaining//2)
            contracts_remaining -= contracts_total // 2
            log.append((time, 'TP1 30%', price, contracts_total // 2, contracts_remaining, soldmkt, cost, soldmkt - cost))
            state = "L1"
        if contracts_remaining <= (2 * contracts_total) // 4 and price >= (1.5 * entry_price) and state == "L1":
            cost = entry_price * math.ceil((contracts_remaining / 2))
            soldmkt = price * math.ceil((contracts_remaining / 2))
            sold = math.ceil(contracts_remaining / 2)
            contracts_remaining -= sold
            log.append((time, 'TP2 50%', price, sold, contracts_remaining, soldmkt, cost, soldmkt - cost))
            state = "L2"

        if contracts_remaining <= (2 * contracts_total) // 4 and price <= entry_price and state == "L1":
            cost = entry_price * math.ceil((contracts_remaining / 2))
            soldmkt = price * contracts_remaining / 2
            sold = contracts_remaining
            contracts_remaining =0
            log.append((time, 'STOP2 50%', price, sold, contracts_remaining, soldmkt, cost, soldmkt - cost))
            state = "L2"

        if price > peak:
            peak = price

        if price < 0.9 * peak and contracts_remaining > 0 and state == "L2":
            cost = entry_price * contracts_remaining
            soldmkt = price * contracts_remaining
            log.append((time, 'trailing stop', price, contracts_remaining, 0, soldmkt, cost, soldmkt - cost))
            contracts_remaining = 0
            break

        prevrow = frame

    if contracts_remaining > 0:
        cost = entry_price * contracts_remaining
        soldmkt = price * contracts_remaining
        last_time = option_df.index[-1]
        last_price = option_df.iloc[-1]['close']
        log.append((last_time, 'EOD', last_price, contracts_remaining, 0, soldmkt, cost, soldmkt - cost))

    # pnl = sum((event[7]) * contract_multiplier for event in log)
    return log

# === MAIN TEST ===
if __name__ == '__main__':
    symbol = "SPY"
    from_date = datetime.today() - timedelta(days=30)
    to_date = datetime.today() - timedelta(days=4)

    df_stock = get_stock_5min_bars(symbol, from_date, to_date)
    total = 0.0

    current = from_date
    while current <= to_date:
        trade_date = current

        start = pd.Timestamp(trade_date.date(), tz="America/New_York")
        if is_market_holiday(start):
            current += timedelta(days=1)
            continue

        end = start + timedelta(days=1)
        stock_day = df_stock[(df_stock.index >= start) & (df_stock.index < end)]
        # print(f"\n=== {trade_date.strftime('%Y-%m-%d')} ===")
        # print(f"Stock bars on trade date: {len(stock_day)}")

        signal = detect_orb_signal(stock_day)
        if signal:
            direction, entry_time, high, low = signal
            # print(f"ORB Signal: {direction} at {entry_time}")

            option_chain = get_options_chain(symbol, trade_date)
            open_price = stock_day.iloc[0]['open']
            expiry_cutoff = trade_date + timedelta(days=0)

            strikes = sorted(set(opt['strike_price'] for opt in option_chain))
            nearest_strike = min(strikes, key=lambda x: abs(x - open_price))
            strike_range = [s for s in strikes if abs(s - nearest_strike) <= 10]
            # print (strike_range)
            filtered_options = [
                opt for opt in option_chain
                if datetime.fromisoformat(opt['expiration_date']) <= expiry_cutoff and
                opt['strike_price'] in strike_range and opt['contract_type'] == str.lower(direction)
            ]

            if filtered_options:
                for fo in filtered_options:
                    sample_ticker = fo['ticker']
                    df_option = get_option_5min_bars(sample_ticker, trade_date)
                    if not df_option.empty:
                        entry_time = entry_time.tz_convert("America/New_York").floor("5min")
                        option_times = df_option.index
                        entry_match = option_times[option_times >= entry_time]
                        if not entry_match.empty:
                            actual_entry_time = entry_match[0]
                            entry_price = df_option.loc[actual_entry_time]['close']
                            if (entry_price > 0.60 or entry_price < 0.40) :
                                continue
                            size = 100
                            ohigh = max(stock_day.iloc[0]["open"],  stock_day.iloc[0]["close"])
                            olow = min(stock_day.iloc[0]["open"],  stock_day.iloc[0]["close"])
                            log = simulate_trade(size, df_option, stock_day, actual_entry_time, entry_price, direction, ohigh, olow)
                            #print(log)
                            pnl = sum((event[7]) * 100 for event in log)
                            print(f"Simulated trade on {sample_ticker}: {entry_price} {actual_entry_time} Cost = {size * 100 * entry_price} PnL = ${pnl:.2f} ")
                            total += pnl
                           #print (f"{log}")
                            for t, reason, p, qtysold, remain, sold, cost, pnl in log:
                                print(f" - {t} | {reason} @ {entry_price} -> {p:.2f} {qtysold:.2f} {remain:.2f} {pnl*100} ")
                        else:
                            print("No matching entry time in option price data.")
                    else:
                        print("No option price data found.")
            else:
                print("No valid options found near strike/open.")
        else:
            print("No ORB signal for this date.")

        current += timedelta(days=1)

    print(f"total pnl {total}")


