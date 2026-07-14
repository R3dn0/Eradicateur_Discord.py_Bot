# Discord Commands Guide

## Architecture

```
Discord Command → Cog (interface) → Service (logic) → Repository (data)
```

- **Cog** : receives Discord interactions, calls the service
- **Service** : contains business logic
- **Repository** : data access (async SQLite)

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
- [ ] Permissions set if admin command
- [ ] Tests written and passing (`pytest`)
