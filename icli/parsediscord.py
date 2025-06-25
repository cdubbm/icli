from pprint import pprint

import requests
import pandas as pd
import re

# ---------- CONFIG ----------
CHANNEL_ID = [1333145313212498073, 1178451513010561064, 1333145364517359736, 1132370664343490641]
LIMIT = 100  # Number of messages to fetch

# ---------- FETCH DISCORD MESSAGES ----------
def fetch_discord_messages(token, channel_id, limit=100):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"{BOT_TOKEN}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
    }

    params = {
        "limit": limit  # number of messages to fetch
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        messages = response.json()
        for msg in messages:
            return [msg["content"] for msg in messages]
    else:
        print(f"Error {response.status_code}: {response.text}")


# ---------- PARSE MESSAGES ----------
def parse_discord_trades(messages):
    results = []

    for msg in messages:
        lower_msg = msg.lower()

        # Flags
        is_heavy_trim = "heavy trim" in lower_msg
        is_trim = "trim" in lower_msg and not is_heavy_trim
        is_starter = "starter" in lower_msg
        is_reentry = "re-entry" in lower_msg or "reentry" in lower_msg

        # Match: SYMBOL STRIKE DIRECTION PRICE (e.g. aapl 195C 0.55 or Anf 23p .45)
        trade_match = re.search(r"\b([a-zA-Z]{1,5})\s+(\d{2,5})([CPcp])\s+(\d+\.\d+)", msg)
        symbol = strike = direction = price = None
        if trade_match:
            symbol = trade_match.group(1).upper()
            strike = float(trade_match.group(2))
            direction = 'CALLS' if trade_match.group(3).upper() == 'C' else 'PUTS'
            price = float(trade_match.group(4))

        # Stop Loss
        sl_match = re.search(r"\bSL\s+(HOD|LOD|\d+\.\d+)", msg, re.IGNORECASE)
        sl = None
        if sl_match:
            val = sl_match.group(1).upper()
            if val in ['HOD', 'LOD']:
                if direction == 'PUTS':
                    sl = 'High' if val == 'HOD' else 'Low'
                else:
                    sl = 'Low' if val == 'HOD' else 'High'
            else:
                sl = float(val)

        # Price Targets
        pt_matches = re.findall(r"PT[:\s]*(\d+\.\d+)", msg, re.IGNORECASE)
        pts = [float(p) for p in pt_matches] if pt_matches else None

        # Percent gain
        gain_match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", msg)
        gain = float(gain_match.group(1)) if gain_match else None

        if any([symbol, strike, direction, price, gain]):
            if symbol is not None:
                results.append({
                    "Message": msg,
                    "Symbol": symbol,
                    "Strike": strike,
                    "Direction": direction,
                    "Price": price,
                    "Stop Loss": sl,
                    "Price Targets": pts,
                    "Percent Gain": gain,
                    "Is Starter": is_starter,
                    "Is Trim": is_trim,
                    "Is Heavy Trim": is_heavy_trim,
                    "Is Reentry": is_reentry
                })

    return pd.DataFrame(results)

# ---------- USAGE ----------
if __name__ == "__main__":
    for i in CHANNEL_ID:
        messages = fetch_discord_messages(BOT_TOKEN, i, LIMIT)
        df = parse_discord_trades(messages)
        df.to_csv(f"discord_trades_{i}.csv", index=False)
