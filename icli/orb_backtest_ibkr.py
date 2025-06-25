from ib_insync import *
from datetime import datetime, timedelta
import pandas as pd

# === ORB BACKTEST FUNCTIONS ===

def detect_orb_signals(df_5min):
    signals = []

    grouped = df_5min.groupby(df_5min.index.date)
    for date, df_day in grouped:
        df_day = df_day.between_time('09:30', '16:00')
        if len(df_day) < 2:
            continue

        opening_candle = df_day.iloc[0]
        high = opening_candle['high']
        low = opening_candle['low']

        for i in range(1, len(df_day)):
            candle = df_day.iloc[i]
            if candle['open'] > high and candle['close'] > high:
                signals.append((candle.name, 'CALL', high, low))
                break
            elif candle['open'] < low and candle['close'] < low:
                signals.append((candle.name, 'PUT', high, low))
                break

    return signals

def estimate_option_price_series(stock_df, entry_time, base_option_price, initial_stock_price, delta, gamma, direction):
    df_after = stock_df.loc[entry_time:]
    prices = []

    for t, row in df_after.iterrows():
        S = row['close']
        dS = S - initial_stock_price
        dP = delta * dS + 0.5 * gamma * dS ** 2
        if direction == 'PUT':
            dP *= -1
        option_price = max(base_option_price + dP, 0.01)
        prices.append({'time': t, 'price': option_price})

    return pd.DataFrame(prices).set_index('time')

def simulate_trade(entry_time, contract_price, stock_df, direction, day_high, day_low, contract_price_series):
    contracts_total = 10
    contracts_remaining = contracts_total
    contract_multiplier = 100
    peak = contract_price
    exit_log = []

    for time, row in contract_price_series.iterrows():
        price = row['price']
        stock_price = stock_df.loc[time]['close']

        # STOP LOSS on stock move
        if direction == 'CALL' and stock_price < day_low:
            exit_log.append({
                'time': time,
                'reason': 'stock SL',
                'contracts': contracts_remaining,
                'price': price
            })
            contracts_remaining = 0
            break
        elif direction == 'PUT' and stock_price > day_high:
            exit_log.append({
                'time': time,
                'reason': 'stock SL',
                'contracts': contracts_remaining,
                'price': price
            })
            contracts_remaining = 0
            break

        # TP1 (30% gain)
        if contracts_remaining == contracts_total and price >= 1.3 * contract_price:
            tp1_contracts = contracts_total // 3
            exit_log.append({
                'time': time,
                'reason': 'TP1 30%',
                'contracts': tp1_contracts,
                'price': price
            })
            contracts_remaining -= tp1_contracts

        # TP2 (50% gain)
        if contracts_remaining <= (2 * contracts_total) // 3 and price >= 1.5 * contract_price:
            tp2_contracts = contracts_total // 3
            exit_log.append({
                'time': time,
                'reason': 'TP2 50%',
                'contracts': tp2_contracts,
                'price': price
            })
            contracts_remaining -= tp2_contracts

        # Trailing stop (20% off peak)
        if price > peak:
            peak = price
        elif price < 0.8 * peak and contracts_remaining > 0:
            exit_log.append({
                'time': time,
                'reason': 'trailing stop',
                'contracts': contracts_remaining,
                'price': price
            })
            contracts_remaining = 0
            break

    # EOD Exit
    if contracts_remaining > 0:
        last_time = contract_price_series.index[-1]
        last_price = contract_price_series.iloc[-1]['price']
        exit_log.append({
            'time': last_time,
            'reason': 'EOD',
            'contracts': contracts_remaining,
            'price': last_price
        })

    # Calculate realized PnL
    realized_pnl = sum(
        e['contracts'] * (e['price'] - contract_price) * contract_multiplier
        for e in exit_log
    )

    return {
        'entry_time': entry_time,
        'entry_price': contract_price,
        'exit_log': exit_log,
        'realized_pnl': realized_pnl
    }

def run_backtest(stock_df, delta, gamma, base_option_price):
    signals = detect_orb_signals(stock_df)
    results = []

    for entry_time, direction, high, low in signals:
        initial_stock_price = stock_df.loc[entry_time]['close']
        option_series = estimate_option_price_series(
            stock_df,
            entry_time,
            base_option_price,
            initial_stock_price,
            delta,
            gamma,
            direction
        )
        result = simulate_trade(
            entry_time,
            base_option_price,
            stock_df,
            direction,
            high,
            low,
            option_series
        )
        result['entry_time'] = entry_time
        result['direction'] = direction  # <-- Add CALL/PUT info to result
        results.append(result)

    return pd.DataFrame(results)



def run_backtest_with_option_bars(ib, stock_df, symbol, chain, base_expiry_days=0):
    signals = detect_orb_signals(stock_df)
    results = []

    # Optional: strike increment rules
    strike_increment = {
        'SPY': 1.0,
        'AAPL': 1.0,
        'TSLA': 2.5,
    }.get(symbol, 1.0)

    def is_valid_strike(s):
        return round((s - round(s)) % strike_increment, 2) == 0 or (s % strike_increment == 0)

    for entry_time, direction, high, low in signals:

        trade_date = entry_time.date()
        underlying_price = stock_df.loc[entry_time]['close']
        atm_strike = round(underlying_price)

        expiry = next((e for e in sorted(chain.expirations)
                       if pd.to_datetime(e).date() >= trade_date + pd.Timedelta(days=base_expiry_days)), None)
        if not expiry:
            continue

        # Filter strikes near ATM (±5), enforce strike granularity
        if direction == 'CALL':
            candidate_strikes = sorted(
                [s for s in chain.strikes if atm_strike <= s <= atm_strike + 4 and is_valid_strike(s)]
            )
        else:  # PUT
            candidate_strikes = sorted(
                [s for s in chain.strikes if atm_strike - 4 <= s <= atm_strike and is_valid_strike(s)],
                reverse=True
            )

        selected_contract = None
        selected_price = None
        for strike in candidate_strikes:
            opt = Option(symbol, expiry, strike, direction[0], 'SMART', underlying_price)
            ib.qualifyContracts(opt)
            ticker = ib.reqMktData(opt, '', snapshot=True)
            ib.sleep(1.5)
            print (ticker.bid, ticker.ask, opt)

            if ticker.bid and ticker.ask:
                mid = (ticker.bid + ticker.ask) / 2
                if 0.20 <= mid <= 1.00:
                    print(opt.localSymbol)
                    selected_contract = opt
                    selected_price = mid
                    break
            ib.cancelMktData(opt)

        print (selected_contract)

        if not selected_contract:
            continue


        bars = ib.reqHistoricalData(
            contract=selected_contract,
            endDateTime=entry_time.strftime('%Y%m%d %H:%M:%S'),
            durationStr='1 D',
            barSizeSetting='5 mins',
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )

        if not bars:
            continue

        df_opt = util.df(bars)
        df_opt.set_index('date', inplace=True)
        df_opt = df_opt[df_opt.index >= entry_time]

        if df_opt.empty:
            continue

        df_opt['price'] = (df_opt['open'] + df_opt['close']) / 2
        option_series = df_opt[['price']]

        contract_price = option_series.iloc[0]['price']
        result = simulate_trade(
            entry_time,
            contract_price,
            stock_df,
            direction,
            high,
            low,
            option_series
        )
        result['entry_time'] = entry_time
        result['direction'] = direction
        result['strike'] = selected_contract.strike
        result['expiry'] = selected_contract.lastTradeDateOrContractMonth
        results.append(result)

    return pd.DataFrame(results)


# === FETCH DATA FROM IBKR ===


def fetch_stock_data(ib, stock, days_back=180):
    bars = []
    end_time = ''

    # Each request will pull 30 calendar days at a time
    for _ in range(days_back // 30 + 1):
        chunk = ib.reqHistoricalData(
            stock,
            endDateTime=end_time,
            durationStr='30 D',
            barSizeSetting='5 mins',
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )
        if not chunk:
            break
        bars = chunk + bars
        end_time = chunk[0].date - timedelta(minutes=5)

    df = util.df(bars)
    df.set_index('date', inplace=True)
    return df

def fetch_data_and_run():
    ib = IB()
    ib.connect('127.0.0.1', 4001, clientId=123)

    symbol = 'SPY'
    stock = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(stock)

    df_stock = fetch_stock_data(ib, stock, days_back=10)
    # print(df_stock.to_csv())
    # df_stock.set_index('date', inplace=True)

    chains = ib.reqSecDefOptParams(stock.symbol, '', stock.secType, stock.conId)
    chain = chains[0]
    expirations = sorted(chain.expirations)
    strikes = sorted(chain.strikes)
    atm_strike = round(df_stock['close'].iloc[-1])
    expiry = expirations[0]

    call_contract = Option(symbol, expiry, atm_strike, 'C', 'SMART')
    ib.qualifyContracts(call_contract)
    ticker = ib.reqMktData(call_contract, '', snapshot=True)
    ib.sleep(2)

    # delta = ticker.modelGreeks.delta if ticker.modelGreeks else 0.5
    # gamma = ticker.modelGreeks.gamma if ticker.modelGreeks else 0.1
    # mid_price = (ticker.bid + ticker.ask) / 2 if ticker.bid and ticker.ask else 0.5


    df_results = run_backtest_with_option_bars(ib, df_stock, symbol, chain)
    ib.disconnect()

    print(df_results)
    df_results.to_csv('orb_backtest_results.csv', index=False)


if __name__ == '__main__':
    fetch_data_and_run()
