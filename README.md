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
- `/ping` - check that the bot responds *(No restriction)*

**Payout / Ledger** (`payout.py`):

- `/payout create` — open a modal to create a new payout. On confirm, posts a public recap embed and notifies each participant by DM with their received amount and new balance. *(Requires: Officer role)*
- `/payout config roles` — set the officer and leader roles for payout management, plus an optional `no_dm` role whose members opt out of payout DMs. *(Requires: Administrator permission)*
- `/payout config rates` — update tax rates used in payout calculations. *(Requires: Leader role)*
- `/payout config show` — display current payout configuration including the opt-out role if configured. *(No restriction)*

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
