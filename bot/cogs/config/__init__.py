from bot.cogs.config.cog import ConfigCog


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
