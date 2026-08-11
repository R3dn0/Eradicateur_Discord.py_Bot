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

**Hosting**: Platforms that require a single startup file should point at
`run.py` at the repository root (not `bot/main.py` directly):

```bash
python3 run.py
```

## Available commands

**General** (`help/`, `guild_commands.py`):
- `/help` — show the list of all available commands *(No restriction)*
- `/ping` - check that the bot responds *(No restriction)*

**Payout / Ledger** (`payout/`):

- `/payout create` — open a modal to create a new payout. On confirm, posts a public recap embed and notifies each participant by DM with their received amount and new balance. *(Requires: Officer role)*
- `/payout void <payout_id>` — reverse a completed payout: marks it voided, inserts compensating transactions for each participant (net zero), and sends DMs with adjusted balances. Rejects already-voided or unknown payouts. *(Requires: Officer role)*
- `/payout config roles` — set the officer and leader roles for payout management. *(Requires: Administrator permission)*
- `/payout config rates` — update tax rates used in payout calculations. *(Requires: Leader role)*
- `/payout config permissions` — set the permission level required for `/balance payer` and `/balance ajouter`. *(Requires: Leader role)*
- `/payout config show` — display current payout configuration. *(No restriction)*

**Balance** (`balance/`):

- `/balance show [member]` — view your own balance (no restriction) or another member's balance if authorized. *(Viewing others requires the pay/add permission level — Officer or Leader, depending on `/payout config permissions`)*
- `/balance history [member]` — view a member's transaction history with pagination (Prev/Next). Viewing your own is unrestricted; viewing others requires the pay/add permission level. *(No restriction for own history)*
- `/balance list` — list all members with a non-zero balance. *(Requires the pay/add permission level)*
- `/balance pay` — manually withdraw an amount from a player's balance (rejects if insufficient funds). On success, sends a DM to the affected player with the debited amount and new balance. *(Requires: Officer or Leader role, depending on `/payout config permissions`)*
- `/balance add` — manually credit a player's balance with a reason. On success, sends a DM to the affected player with the credited amount, reason, and new balance. *(Requires: Officer or Leader role, depending on `/payout config permissions`)*

**Activity signups** (`activite/`):

- `/activite creer` — opens a form (title, departure point, optional stuff), then a slot builder: a dropdown fed by the server's **role pool** (same role can be added multiple times, paginated beyond 23 roles) plus a **Manual add** button (`CATEGORY - description`) for exotic compositions. Then a date/time picker. The whole creation happens in an **ephemeral message** (visible only to the creator); the signup embed is only published to the channel once confirmed, with a dropdown to claim a slot, a thread for discussion, and a roster of all slots with the registered players next to them. A `❓ Fill` slot is added automatically at the end. *(No restriction)*
- `/activite pool afficher` — shows the role pool; `/activite pool ajouter <label>` adds a role (e.g. `🛡️ Tank incub`); `/activite pool supprimer <position>` deletes one (with confirmation); `/activite pool réordonner` reorders the pool through a visual picker (pick the role to move, then the target position, then Save); `/activite pool vider` empties the pool (with confirmation). *(Requires: Discord Administrator permission)*
- Slots — anyone can claim a slot from the embed dropdown, or in the activity thread with `/activite rejoindre <slot>`. A player can hold only one slot per activity; several players can share a slot. Picking another slot while already registered automatically moves the registration. `/activite quitter` releases your slot, and the **Close** button freezes the embed. The **Edit** and **Close** menus are only visible to the organizer and admins — **Edit** also lets you rewrite the slot list (existing registrations are kept for identical slots). The embed is the source of truth, so thread commands keep working after a bot restart (no activity database, nothing is tracked).

**Configuration** (`config/`):

- `/config nonotification role` — set or clear the role whose members are skipped in payout DMs. *(Requires: Administrator permission)*
- `/config nonotification show` — display current notification opt-out configuration. *(No restriction)*
- `/config logs channel` — set or clear the audit log channel for slash command usage. *(Requires: Administrator permission)*
- `/config logs show` — display current audit log channel configuration. *(No restriction)*

**Audit logging**: if a log channel is configured, every successful slash command execution is automatically logged there with the user mention and the fully-qualified command name (e.g. `payout create`). Failed commands are not logged.

**Dev logging**: runtime logs are written to per-guild files under `<data_dir>/logs/` (`guild_<id>.log`, plus a global `bot.log` for non-guild activity), with automatic rotation (1 MB per file, 10 backups) and **newest entries at the top** of each file. A global `errors.log` aggregates all `ERROR`+ records from every guild — giving you a single list of every problem to investigate. Every line mentions the guild and user names inline when available, e.g. `executed by 1354... "R3dn0" in guild 1526... "Eradicateur-Bot TEST"`. Each guild's activity is routed to its own file via the slash command execution context. The verbosity is controlled by `LOG_LEVEL` in `.env` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, default `DEBUG`). The console prints `INFO`+ (startup/lifecycle logs and the full stack trace on errors) so you can visually confirm the bot started, while the per-command `DEBUG` detail stays in the files. Command failures are logged with their full traceback — handy for servers you cannot access. User-side rejections (`CheckFailure`, `CommandNotFound`, `CommandOnCooldown`) are logged at `DEBUG` in the files only, not as errors.

## Project structure

```
bot/
├── cogs/           # Discord commands (grouped by feature)
├── repositories/   # Data access layer
├── services/       # Business logic
├── locales/        # i18n translations
├── config.py       # Configuration
├── db_manager.py   # Per-guild database connection manager
├── dev_logs.py     # Per-guild file logging for developers
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
