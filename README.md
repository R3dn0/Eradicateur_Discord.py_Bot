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

**Payout / Ledger** (`payout/`):

- `/payout create` — open a modal to create a new payout. On confirm, posts a public recap embed and notifies each participant by DM with their received amount and new balance. *(Requires: Officer role)*
- `/payout pay` — manually withdraw an amount from a player's balance (rejects if insufficient funds). *(Requires: Officer or Leader role, depending on `/payout config permissions`)*
- `/payout add` — manually credit a player's balance with a reason. *(Requires: Officer or Leader role, depending on `/payout config permissions`)*
- `/payout config roles` — set the officer and leader roles for payout management. *(Requires: Administrator permission)*
- `/payout config rates` — update tax rates used in payout calculations. *(Requires: Leader role)*
- `/payout config permissions` — set the permission level required for `/payout pay` and `/payout add`. *(Requires: Leader role)*
- `/payout config show` — display current payout configuration. *(No restriction)*

**Balance** (`balance/`):

- `/balance show [member]` — view your own balance (no restriction) or another member's balance if authorized. *(Viewing others requires the pay/add permission level — Officer or Leader, depending on `/payout config permissions`)*
- `/balance list` — list all members with a non-zero balance. *(Requires the pay/add permission level)*

**Configuration** (`config/`):

- `/config nonotification role` — set or clear the role whose members are skipped in payout DMs. *(Requires: Administrator permission)*
- `/config nonotification show` — display current notification opt-out configuration. *(No restriction)*
- `/config logs channel` — set or clear the audit log channel for slash command usage. *(Requires: Administrator permission)*
- `/config logs show` — display current audit log channel configuration. *(No restriction)*

**Audit logging**: if a log channel is configured, every successful slash command execution is automatically logged there with the user mention and the fully-qualified command name (e.g. `payout create`). Failed commands are not logged.

## Project structure

```
bot/
├── cogs/           # Discord commands (grouped by feature)
├── repositories/   # Data access layer
├── services/       # Business logic
├── locales/        # i18n translations
├── config.py       # Configuration
├── db_manager.py   # Per-guild database connection manager
├── i18n.py         # Translator
└── main.py         # Entry point
```

### Database

Each Discord guild has its own SQLite database file at `data/guilds/<guild_id>.db`.
Connections are opened lazily on the first command for a guild and are
automatically closed after 30 minutes of inactivity. The connection manager
(`GuildDatabaseManager`) is thread-safe per guild.

When adding a new command that needs a repository, resolve the connection
first, then construct the repository inline:

```python
db = await self.bot.db_manager.get_connection(interaction.guild.id)
repo = MyRepository(db)
await repo.do_something()
```
