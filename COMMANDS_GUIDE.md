# Discord Commands Guide

## Architecture

```
Discord Command → Cog (interface) → Service (logic) → Repository (data)
```

- **Cog** : receives Discord interactions, calls the service
- **Service** : contains business logic
- **Repository** : data access (async SQLite)

### Database

Each Discord guild has its own SQLite database file at `data/guilds/<guild_id>.db`.
Connections are opened lazily on the first command for a guild (`GuildDatabaseManager`)
and cached with a last-used timestamp. Idle connections are evicted after 30 minutes.
The manager is thread-safe per guild (uses `asyncio.Lock` per guild ID).

To use a repository in a command, resolve the connection and construct the repo inline:

```python
db = await self.bot.db_manager.get_connection(interaction.guild.id)
repo = MyRepository(db)
await repo.do_something()
```

Do **not** store repository instances as bot-level attributes — connect and
construct per command.

## Organizing cogs

One cog = one file = a set of commands about the same topic. Group commands by **domain**, not by command.

### For example

**`general.py`** - basic bot commands:
- `/ping`, `/help`, `/info`

**`members.py`** - member management:
- `/register`, `/force-register`, `/members`

**`moderation.py`** - moderation:
- `/ban`, `/kick`, `/mute`, `/warn`

**`albion.py`** - guild-specific commands:
- `/stats`, `/builds`, `/events`

**Rule**: if a command has nothing to do with the others in the cog, it goes in another file.

## Adding a command

### 1. Service (if business logic needed)

Create `bot/services/my_service.py`:

```python
from bot.repositories.my_repository import MyRepository


class MyService:
    def __init__(self, repository: MyRepository) -> None:
        self._repo = repository

    async def do_something(self, arg: str) -> str:
        # Business logic here
        return f"Result: {arg}"
```

Update `bot/services/__init__.py`:

```python
from bot.services.my_service import MyService

__all__ = ["MyService"]
```

### 2. Cog

Create `bot/cogs/my_command.py`:

```python
import discord
from discord import app_commands
from discord.ext import commands

from bot.main import EradicateurBot


class MyCommand(commands.Cog):
    def __init__(self, bot: EradicateurBot) -> None:
        self.bot = bot

    @app_commands.command(
        name=app_commands.locale_str("name", key="my_command_name"),
        description=app_commands.locale_str("Description", key="my_command_description"),
    )
    async def my_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Hello!")


async def setup(bot: EradicateurBot) -> None:
    await bot.add_cog(MyCommand(bot))
```

Update `bot/cogs/__init__.py`:

```python
from bot.cogs.my_command import MyCommand

__all__ = ["MyCommand"]
```

### 3. Translations

Add to `bot/locales/fr.json`:

```json
{
    "my_command_name": "name",
    "my_command_description": "Description in French"
}
```

For commands in a custom top-level group (e.g. `config/`), follow the nested key convention:
```json
{
    "config_name": "config",
    "config_nonotification_name": "nonotification",
    "config_nonotification_role_name": "role",
    ...
}
```

### 4. Load the cog

In `bot/main.py`, add to `setup_hook()`:

```python
await self.load_extension("bot.cogs.my_command")
```

### 5. Test

Create `tests/test_my_command.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.cogs.my_command import MyCommand


class TestMyCommand:
    @pytest.fixture
    def cog(self):
        bot = MagicMock()
        return MyCommand(bot)

    @pytest.mark.asyncio
    async def test_my_command_responds(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        await cog.my_command.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
        assert "Hello" in interaction.response.send_message.call_args[0][0]
```

## Parameter types

### Simple text
```python
@app_commands.describe(text="Parameter description")
async def cmd(self, interaction: discord.Interaction, text: str) -> None:
```

### Number
```python
@app_commands.describe(number="A number")
async def cmd(self, interaction: discord.Interaction, number: int) -> None:
```

### Decimal
```python
@app_commands.describe(rate="A percentage")
async def cmd(self, interaction: discord.Interaction, rate: float) -> None:
```

### Boolean
```python
@app_commands.describe(silent="Silent mode")
async def cmd(self, interaction: discord.Interaction, silent: bool = False) -> None:
```

### Discord user
```python
@app_commands.describe(user="Target user")
async def cmd(self, interaction: discord.Interaction, user: discord.Member) -> None:
```

### Text channel
```python
@app_commands.describe(channel="Target channel")
async def cmd(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
```

### Role
```python
@app_commands.describe(role="Role to assign")
async def cmd(self, interaction: discord.Interaction, role: discord.Role) -> None:
```

### Fixed choices (enum)
```python
from enum import Enum

class Option(str, Enum):
    OPTION_A = "a"
    OPTION_B = "b"

@app_commands.describe(option="Choose an option")
async def cmd(self, interaction: discord.Interaction, option: Option) -> None:
```

## Permissions

### Admin only
```python
@app_commands.default_permissions(administrator=True)
async def cmd(self, interaction: discord.Interaction) -> None:
```

### Manage server
```python
@app_commands.default_permissions(manage_guild=True)
async def cmd(self, interaction: discord.Interaction) -> None:
```

### Manage messages
```python
@app_commands.default_permissions(manage_messages=True)
async def cmd(self, interaction: discord.Interaction) -> None:
```

### Role-based permissions

```python
if not isinstance(interaction.user, discord.Member):
    await interaction.response.send_message(
        "This command must be used in a server.", ephemeral=True
    )
    return

bot: EradicateurBot = self.bot
if not await bot.payout_config_service.is_leader(interaction.user):
    await interaction.response.send_message(
        "You need the leader role.", ephemeral=True
    )
    return
```

Use when roles are configured at runtime (`/payout config roles`) instead of hardcoded via `@app_commands.default_permissions(administrator=True)`.

## Responses

### Ephemeral response (visible only to user)
```python
await interaction.response.send_message("Secret!", ephemeral=True)
```

### Normal response
```python
await interaction.response.send_message("Visible to everyone")
```

### Embed response
```python
embed = discord.Embed(title="Title", description="Description", color=discord.Color.blue())
embed.add_field(name="Field", value="Value")
await interaction.response.send_message(embed=embed)
```

### Deferred response (for long processing)
```python
await interaction.response.defer()
# ... processing ...
await interaction.followup.send("Result")
```

### Edit an existing response
```python
await interaction.edit_original_response(content="New content")
```

## Nested command subgroups

❌ Wrong — space in command name:

```python
@app_commands.command(name="config roles", description="...")
```

✅ Correct — `app_commands.Group` as class attribute + `@group.command`:

```python
class PayoutCog(commands.GroupCog, group_name="payout"):
    config = app_commands.Group(name="config", description="Configure payout settings")

    @config.command(name="roles", description="Set the officer and leader roles")
    async def config_roles(self, interaction: discord.Interaction, ...) -> None:
        ...
```

## Concrete examples

### /help command
```python
@app_commands.command(
    name=app_commands.locale_str("help", key="help_name"),
    description=app_commands.locale_str("Shows help", key="help_description"),
)
async def help(self, interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Available commands",
        color=discord.Color.green(),
    )
    embed.add_field(name="/ping", value="Check that the bot responds", inline=False)
    # Add other commands here
    await interaction.response.send_message(embed=embed)
```

### Command with multiple arguments
```python
@app_commands.command(
    name=app_commands.locale_str("embed", key="embed_name"),
    description=app_commands.locale_str("Creates an embed", key="embed_description"),
)
@app_commands.describe(
    title="Embed title",
    description="Embed description",
    color="Hex color",
)
@app_commands.rename(
    title=app_commands.locale_str("title", key="embed_title_name"),
    description=app_commands.locale_str("description", key="embed_description_name"),
    color=app_commands.locale_str("color", key="embed_color_name"),
)
async def embed(
    self,
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: str = "#3498db",
) -> None:
    try:
        color_int = int(color.lstrip("#"), 16)
    except ValueError:
        color_int = discord.Color.blue().value

    embed = discord.Embed(title=title, description=description, color=color_int)
    await interaction.response.send_message(embed=embed)
```

### Admin command with confirmation
```python
@app_commands.command(name="clear", description="Deletes messages")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages to delete")
async def clear(self, interaction: discord.Interaction, amount: int) -> None:
    if amount < 1 or amount > 100:
        await interaction.response.send_message(
            "Invalid number (1-100)", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    channel = interaction.channel
    if isinstance(channel, discord.TextChannel):
        deleted = await channel.purge(limit=amount)
        await interaction.followup.send(
            f"{len(deleted)} messages deleted", ephemeral=True
        )
```

## Testing

### Setup

Tests use `pytest` with `pytest-asyncio` for async commands:

```bash
pip install -r requirements-dev.txt
pytest
```

### Writing tests

Create `tests/test_<cog_name>.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.cogs.my_cog import MyCog


class TestMyCog:
    @pytest.fixture
    def cog(self):
        bot = MagicMock()
        return MyCog(bot)

    @pytest.mark.asyncio
    async def test_command_responds(self, cog):
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.response = AsyncMock()
        await cog.my_command.callback(cog, interaction)
        interaction.response.send_message.assert_awaited_once()
```

## Audit log channel

A per-guild audit log channel can be configured to track all successful slash command executions. Every time a user runs a slash command successfully, a message is sent to the configured channel with the user's mention and the fully-qualified command name.

**Behavior:**
- To set the channel, an admin calls `/config logs channel salon:<TextChannel>`.
- To clear it, the admin calls `/config logs channel` without providing a channel.
- Only successful completions are logged (`on_app_command_completion` fires only on success).
- Command parameters/arguments are included in the log message, formatted as comma-separated `name: value` pairs (mentions for users/roles).
- If the channel cannot be found or the bot lacks send permission, the error is silently logged as a warning — the bot does not crash.

**Implementation:**
- Repository: `BotConfigRepository` with `get_config().log_channel_id` and `update_log_channel(channel_id)`.
- Cog: `ConfigCog` with `/config logs channel` and `/config logs show`.
- Listener: `EradicateurBot.on_app_command_completion()` in `bot/main.py` — resolves the guild's log channel from `bot_config`, builds the message `<@user> a utilisé la commande : /<qualified_name>`, and sends it. Errors are caught per channel.

**Example log message (English):**
```
<@123456789> used a command in <#channel_id>:
`/balance add`
joueur: <@111>, montant: 150000, raison: Compensation erreur payout
```

## Global notification opt-out role

A global opt-out role for payout DMs is configured via `/config nonotification opt-out-role` (separate from payout-specific settings). Members who hold this role will not receive a DM notification when a payout is confirmed. The skipped participants are reported in the ephemeral success message with a neutral note (not an error).

**Behavior:**
- To set the opt-out, an admin calls `/config nonotification role role:<Role>`.
- To clear the opt-out, the admin calls `/config nonotification role` without providing a role.
- Skipped DMs are not counted as failures and do not trigger the "Impossible de contacter en MP" warning.
- The setting is stored in the `bot_config` table (single-row), independent of any payout-specific configuration.

**Implementation:**
- Repository: `BotConfigRepository` with `get_config()` and `update_opt_out_role(role_id)`.
- Cog: `ConfigCog` with `/config nonotification role` and `/config nonotification show`.
- DM flow: `ConfirmCancelView.confirm()` fetches `bot_config.notification_opt_out_role_id` and passes it to `send_bulk_dm(opt_out_role_id=...)`. The `send_bulk_dm` utility handles the role check per recipient.

### Testing patterns

**Test command response:**
```python
@pytest.mark.asyncio
async def test_ping(self, cog):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    await cog.ping.callback(cog, interaction)
    interaction.response.send_message.assert_awaited_once()
    assert "Pong" in interaction.response.send_message.call_args[0][0]
```

**Test ephemeral response:**
```python
@pytest.mark.asyncio
async def test_ephemeral(self, cog):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    await cog.secret_command.callback(cog, interaction)
    call_args = interaction.response.send_message.call_args
    assert call_args[1]["ephemeral"] is True
```

**Test command with arguments:**
```python
@pytest.mark.asyncio
async def test_with_args(self, cog):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    await cog.command_with_args.callback(cog, interaction, "test_value")
    interaction.response.send_message.assert_awaited_once()
```

**Test permission error:**
```python
@pytest.mark.asyncio
async def test_admin_only(self, cog):
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.response = AsyncMock()
    interaction.user.guild_permissions.administrator = False
    await cog.admin_command.callback(cog, interaction)
    interaction.response.send_message.assert_called_with(
        "Not allowed", ephemeral=True
    )
```

### Running tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_my_cog.py

# Run with coverage
pytest --cov=bot
```

## Pre-commit checklist

- [ ] French translations added to `bot/locales/fr.json`
- [ ] Cog loaded in `bot/main.py` (`load_extension`)
- [ ] Folder `__init__.py` updated if needed
- [ ] `locale_str` used for name and description
- [ ] `locale_str` used for parameter descriptions in `@app_commands.describe(...)` — not raw strings
- [ ] Permissions set if admin command
- [ ] Tests written and passing (`pytest`)
- [ ] New repository connected via `bot.db_manager.get_connection(guild_id)` and constructed inline in the command
- [ ] `/help` static list updated in `bot/cogs/help/cog.py` (`_CATEGORIES`) — it won't auto-discover new commands

## Veto / reversal command (`/payout void`)

When a payout must be reversed (e.g. split was wrong, the activity did not happen), use the existing
`PayoutRepository.void_payout()` and the `/payout void` cog command:

```python
# Repository — atomic reversal
async def void_payout(self, payout_id: int, voided_by: int) -> None:
    payout = await self.get_payout(payout_id)
    if payout is None:
        raise ValueError("Payout not found")
    if payout.voided:
        raise ValueError("Payout already voided")
    try:
        await self._db.execute("BEGIN IMMEDIATE")
        await self._db.execute(
            "UPDATE payouts SET voided = 1, voided_by = ?, voided_at = ? WHERE id = ?",
            (voided_by, datetime.utcnow().isoformat(), payout_id),
        )
        # Reverse each transaction
        txns = await self._transaction_repo.list_transactions_for_payout(payout_id)
        for t in txns:
            await self._transaction_repo.add_transaction(
                discord_id=t.discord_id,
                amount=-t.amount,
                reason=f"Void payout #{payout_id}",
                created_by=voided_by,
            )
        await self._db.commit()
    except BaseException:
        await self._db.rollback()
        raise
```

The command flow:
1. Permission check: `is_officer()` (same as `/payout create`)
2. Fetch payout — reject if not found or already voided (ephemeral error)
3. `void_payout()` — atomic `BEGIN IMMEDIATE` + commit/rollback
4. DM each participant with the adjusted amount and new balance (uses `send_bulk_dm`, respects global opt-out role)
5. Public embed recap in the interaction response (ephemeral to the caller)

## Transaction history (`/balance history`)

View a member's transaction history with pagination:

```python
@app_commands.command(name="history", ...)
async def history(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    if member is None:
        discord_id = interaction.user.id
    else:
        # Permission check: check_pay_add_permission()
        if not await payout_config_service.check_pay_add_permission(interaction.user):
            ...
            return
        discord_id = member.id

    txs = await transaction_repo.list_transactions(discord_id)
    if not txs:
        await interaction.response.send_message("No transactions found.", ephemeral=True)
        return

    lines = [
        f"{to_discord_timestamp(tx.created_at)} | {'+' if tx.amount >= 0 else ''}{tx.amount:,.0f} | {tx.reason}"
        for tx in txs
    ]
    embed_title = f"Transaction history for <@{discord_id}>"
    view = paginate_lines(lines, title=embed_title)
    await interaction.response.send_message(embed=view._build_embed(), view=view, ephemeral=True)
```

## Paginator utility

For displaying long lists that exceed Discord's embed limits, use `PaginatorView` from `bot/utils/paginator.py`:

```python
from bot.utils.paginator import paginate_lines, PaginatorView

lines: list[str] = [...]               # up to 1024 chars per line
view = paginate_lines(lines, title="My Title", page_size=10)
await interaction.response.send_message(embed=view._build_embed(), view=view)
```

The utility:
- Splits lines into pages of `page_size` (default 10)
- Renders each page as a single embed field
- Prev/Next buttons with page counter
- Disables buttons at boundaries
- Timeout after 180 seconds

## Shared guard decorator (`@require_guild_member`)

All commands that interact with guild databases should ensure the interaction comes from a guild context.
Instead of inlining the check in every command, use the `@require_guild_member` decorator from `bot/utils/discord_guards.py`:

```python
from bot.utils.discord_guards import require_guild_member

@app_commands.command(...)
@require_guild_member
async def my_command(self, interaction: discord.Interaction) -> None:
    ...
```

The guard returns early with an ephemeral "This command must be used in a server." message if
`interaction.guild` is `None`. No other changes to the command function needed.

## Base repository class

All repositories inherit from `BaseRepository` (`bot/repositories/base_repository.py`) which provides
shared `_run_migrations()` logic:

```python
from bot.repositories.base_repository import BaseRepository


class MyRepository(BaseRepository):
    _COLUMNS: dict[str, str] = {
        "my_table": "CREATE TABLE IF NOT EXISTS my_table (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    }

    _MIGRATIONS: dict[str, str] = {
        "name_not_null": "ALTER TABLE my_table ADD COLUMN name TEXT NOT NULL DEFAULT ''",
    }
```

The base class constructor runs `_run_migrations()` which:
1. Calls `_ensure_table("_schema_version")` (shared across all repos)
2. Calls `_ensure_table()` for each entry in `_COLUMNS` (with the DDL exactly as given)
3. Applies each migration in `_MIGRATIONS` that hasn't been recorded yet
4. Inserts a row in `_schema_version` for each applied migration
5. Uses `BEGIN IMMEDIATE` to prevent concurrent schema races

Do not call `_ensure_tables()` explicitly in subclass constructors — the base class handles it.

## Modal patterns

Discord modals collect structured input before a command proceeds:

```python
class MyModal(discord.ui.Modal, title="Modal Title"):
    field_name = discord.ui.TextInput(
        label="Field label shown to the user",
        placeholder="Placeholder text",
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.field_name.value
        await interaction.response.send_message(f"Got: {value}", ephemeral=True)

# In the command:
await interaction.response.send_modal(MyModal())
```

## Multi-step flows (Modal → Select → Confirm)

Commands that need multiple user inputs before writing to the database follow this pattern:

1. **Slash command** sends a modal (`interaction.response.send_modal(...)`)
2. **Modal `on_submit`** sends an ephemeral message with a `View` (e.g. `UserSelect`)
3. **View callback** computes results and edits the message to show a summary + confirm/cancel `View`
4. **Confirm** writes to the database atomically, DMs each participant with their received amount and new balance, then edits the message to a final state
5. **Cancel** edits the message to a cancelled state without writing anything

## Pure calculation logic in services

When a calculation involves only numbers (no Discord objects), extract it into a pure function in `bot/services/`:

```python
# bot/services/payout_service.py
from dataclasses import dataclass

from bot.services.payout_config_service import PayoutRates


@dataclass(frozen=True)
class PayoutSplitResult:
    ...
    amount_per_player: float
    ...


def compute_split(
    bag_silvers: float,
    item_market_value: float,
    activity_cost: float,
    rates: PayoutRates,
    participant_count: int,
) -> PayoutSplitResult:
    # Pure math — no discord.py imports, no I/O
    ...
```

Benefits:
- Unit-testable without mocking Discord objects
- Same function can be reused by multiple commands (payout create, payout pay, payout add)
- Can be verified by hand with a calculator

Usage in a view:
```python
from bot.services.payout_service import compute_split

split = compute_split(
    bag_silvers=bag_silvers,
    item_market_value=item_market_value,
    activity_cost=activity_cost,
    rates=rates,
    participant_count=n,
)
embed.add_field(name="Amount", value=f"{split.amount_per_player:,.0f}")
```

## Bulk DM utility

When you need to DM multiple guild members with custom content per recipient, use `send_bulk_dm` instead of writing your own loop:

```python
from bot.utils.discord_dm import send_bulk_dm, BulkDMResult

async def _build_content(member: discord.Member) -> discord.Embed:
    balance = await bot.transaction_repo.get_balance(member.id)
    return discord.Embed(title=f"Hello {member.display_name}",
                         description=f"Your balance: {balance:,.0f}")

result = await send_bulk_dm(
    guild=interaction.guild,
    member_ids=[111, 222, 333],
    build_content=_build_content,
    opt_out_role_id=777,  # role ID whose members are skipped
)

# result.sent / result.skipped / result.failed are list[int] of member IDs
if result.failed:
    await interaction.followup.send(
        f"Could not reach: {', '.join(f'<@{uid}>' for uid in result.failed)}"
    )
```

The utility handles:
- `guild.get_member()` → `guild.fetch_member()` fallback
- Opt-out role check (skip, not fail)
- `discord.Forbidden` / `discord.HTTPException` per recipient (other recipients unaffected)

The `build_content` callback receives each resolved `discord.Member` and returns a per-member embed.
The caller decides the embed content — the utility only handles sending and bookkeeping.

## Atomic transactions across repositories

When a single operation must write to multiple tables atomically, manage the transaction at the repository level rather than modifying `TransactionRepository`:

```python
class CombinedRepository:
    async def create_with_children(self, ...) -> int:
        await self._ensure_tables()
        try:
            await self._db.execute("BEGIN")
            cursor = await self._db.execute("INSERT INTO parent ...")
            parent_id = cursor.lastrowid
            for child in children:
                await self._db.execute("INSERT INTO child ...", (..., parent_id))
            await self._db.commit()
            return parent_id
        except BaseException:
            await self._db.rollback()
            raise
```

## Public recap embed after confirm

When a command needs to send a public recap message after a confirm step:

1. Keep all interactive steps ephemeral (modal, select, confirm buttons)
2. On confirm, persist to DB then:
    - DM each participant with their received amount and new total balance (wrap each in try/except, collect failures)
    - `interaction.channel.send(embed=public_embed)` — public message
    - `interaction.response.edit_message(content="Done", embed=None)` — ephemeral update (append a failure note if DMs failed)
3. Compute buyback / informational values at confirm time so they reflect the rates used at that moment

```python
async def confirm(self, interaction, button):
    bot = interaction.client
    payout_id = await repo.create_payout(...)

    failed_dms = []
    for pid in participant_ids:
        member = guild.get_member(pid) or await guild.fetch_member(pid)
        balance = await bot.transaction_repo.get_balance(pid)
        try:
            await member.send(embed=...)
        except (discord.Forbidden, discord.HTTPException):
            failed_dms.append(pid)

    public_embed = discord.Embed(title=f"Payout #{payout_id}", color=discord.Color.green())
    public_embed.add_field(name="Amount", value=f"{amount:,.0f}")
    await interaction.channel.send(embed=public_embed)

    success = f"Payout #{payout_id} created."
    if failed_dms:
        success += "\n⚠️ Could not reach: " + ", ".join(f"<@{pid}>" for pid in failed_dms)
    await interaction.response.edit_message(
        content=success, embed=None, view=self,
    )
```
