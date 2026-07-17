from bot.cogs.help.cog import HelpCog


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
