# Discord Bot - ERADICATEURS - Albion Online Guild

> 🇫🇷 [Lire en français](README.fr.md)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in DISCORD_TOKEN and GUILD_ID
python -m bot.main
```

## Available commands

**General** (`guild_commands.py`):
- `/ping` - check that the bot responds

**Payout / Ledger** (`payout.py`):
- `/payout config roles <officer> <leader>` — set the officer and leader roles for payout management (Administrator only)
- `/payout config rates <market> <guild> <transport>` — update tax rates used in payout calculations (Leader role required)
- `/payout config show` — display current payout configuration (no restriction)

## Project structure

```
bot/
├── cogs/           # Discord commands (grouped by feature)
├── repositories/   # Data access layer
├── services/       # Business logic
├── locales/        # i18n translations
├── config.py       # Configuration
├── i18n.py         # Translator
└── main.py         # Entry point
```
