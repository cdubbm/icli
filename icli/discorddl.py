import requests

# Replace with your actual bot token and channel ID
CHANNEL_ID = "1333145313212498073"

url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
     #   https://discord.com/api/v10/channels/1333145313212498073/messages?limit=1000
headers = {
    "Authorization": f"{BOT_TOKEN}",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
}

params = {
    "limit": 100  # number of messages to fetch
}

response = requests.get(url, headers=headers, params=params)

if response.status_code == 200:
    messages = response.json()
    for msg in messages:
        print(f"{msg['author']['username']}: {msg['content']}")
else:
    print(f"Error {response.status_code}: {response.text}")



