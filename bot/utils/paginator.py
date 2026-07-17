import discord

_PAGE_SIZE = 15


class PaginatorView(discord.ui.View):
    def __init__(
        self, pages: list[str], title: str = "", color: discord.Color = discord.Color.blue()
    ) -> None:
        super().__init__(timeout=300)
        self._pages = pages
        self._title = title
        self._color = color
        self._current = 0

        self._update_button_states()

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self._title,
            description=self._pages[self._current],
            color=self._color,
        )
        embed.set_footer(text=f"Page {self._current + 1} / {len(self._pages)}")
        return embed

    def _update_button_states(self) -> None:
        self.prev_button.disabled = self._current == 0
        self.next_button.disabled = self._current >= len(self._pages) - 1

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._current -= 1
        self._update_button_states()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._current += 1
        self._update_button_states()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


def paginate_lines(lines: list[str], title: str = "", page_size: int = _PAGE_SIZE) -> PaginatorView:
    pages: list[str] = []
    current_lines: list[str] = []
    for line in lines:
        tentative = "\n".join(current_lines + [line])
        if len(tentative) > 4000 or len(current_lines) >= page_size:
            pages.append("\n".join(current_lines))
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        pages.append("\n".join(current_lines))
    return PaginatorView(pages, title=title)
