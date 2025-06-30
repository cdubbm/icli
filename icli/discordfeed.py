from pprint import pprint

import discord as discord

import pandas as pd
from datetime import datetime
from parsediscord import parse_discord_trades  # reuse the function from earlier
from dotenv import dotenv_values
import os
import asyncio
import json
import websockets

CONFIG_DEFAULT = dict(
    ICLI_IBKR_HOST="127.0.0.1", ICLI_IBKR_PORT=4001, ICLI_REFRESH=3.33
)
CONFIG = {**CONFIG_DEFAULT, **dotenv_values("../.env.icli"), **os.environ}

# Create the bot
BOT_TOKEN: str = CONFIG["BOT_TOKEN"]
CHANNEL_ID = [1333145313212498073, 1178451513010561064, 1333145364517359736, 1376788020644286487, ]


# Create the bot
#intents = discord.Intents.default()

# Storage

class MyClient(discord.Client):
    async def on_ready(self):
        print(f'✅ Logged in as {client.user}')

    async def on_message(self, message):
        # Ignore messages from the bot itself

        if message.author == client.user:
            return

        # print(message.channel.id)
        if message.channel.id in CHANNEL_ID :
            # print(message.content)
            df = parse_discord_trades([message.content])
            # df['Timestamp'] = datetime.datetime.now(datetime.UTC)
            df.to_csv("discord_trades_live.csv", mode='a', index=False, header=False)
            # if df["symbol"]:
            print("DF:%s " % df.to_csv())

    # Start the bot

client = MyClient()
client.run(BOT_TOKEN)
#
# async def listen_to_gateway():
#     uri = "wss://gateway.discord.gg/?v=10&encoding=json"
#     async with websockets.connect(uri) as ws:
#         # Receive Hello
#         hello = await ws.recv()
#         hello_data = json.loads(hello)
#         print(hello_data)
#         heartbeat_interval = hello_data['d']['heartbeat_interval'] / 1000
#
#         # Send Identify
#         identify_payload = {
#             "op": 2,
#             "d": {
#                 "token": BOT_TOKEN,
#                 "intents": 512 + 2048 + 32768,
#             },
#             "properties": {
#                 "$os": "mac",
#                 "$device": "mac",
#                 "$browser": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
#             },
#         }
#         await ws.send(json.dumps(identify_payload))
#
#         async def send_heartbeat():
#             while True:
#                 await asyncio.sleep(heartbeat_interval)
#                 await ws.send(json.dumps({"op": 1, "d": None}))
#
#         asyncio.create_task(send_heartbeat())
#
#         # Main loop
#         while True:
#             try:
#                 event = await ws.recv()
#                 data = json.loads(event)
#                 print("event")
#                 print(data)
#
#                 if data.get("t") == "MESSAGE_CREATE":
#                     content = data['d']['content']
#                     channel_id = data['d']['channel_id']
#                     author = data['d']['author']
#                     print(f"[{channel_id}] {content}")
#
#                     if channel_id not in CHANNEL_ID:
#                         print("wrong channel")
#                         return
#
#                     df = parse_discord_trades([message.content])
#                     df['Timestamp'] = datetime.utcnow().isoformat()
#                     pprint(df.to_csv())
#
#             except websockets.exceptions.ConnectionClosed:
#                 print("Disconnected. Reconnecting...")
#                 break
#
# asyncio.run(listen_to_gateway())



