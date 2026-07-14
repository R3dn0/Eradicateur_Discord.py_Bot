# Discord Bot — Albion Online Guild

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in DISCORD_TOKEN and GUILD_ID
python -m bot.main
```

## Available commands

- `/ping` — check that the bot responds
- `/register <ign>` — link your Albion in-game name to your Discord account
- `/members` — list all registered members
