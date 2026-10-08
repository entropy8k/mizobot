import discord
from discord.ext import commands
import os

intents = discord.Intents.all()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.messages = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.tree.sync()  # sync slash commands
# Load cogs
async def main():
    async with bot:
        await bot.load_extension('cogs.music')
        await bot.load_extension('cogs.mod')
        await bot.load_extension('cogs.warn')
        await bot.load_extension('cogs.help')
        await bot.load_extension('cogs.fun')
        await bot.load_extension('cogs.link_moderator')
        await bot.load_extension('cogs.logs')
        await bot.load_extension('cogs.meme')
        await bot.load_extension('cogs.starboard')
        await bot.load_extension('cogs.rapedboard')
        await bot.load_extension("cogs.ifunny_cog")
        await bot.load_extension('cogs.soybooru')
        await bot.load_extension('cogs.swabooru')
        await bot.load_extension('cogs.nuttybooru')
        await bot.load_extension('cogs.lastfm')
        await bot.load_extension('cogs.img')
        await bot.start("MTQzMjM4MzI3NDUzMzEzMDM5Mg.GaaNkR.q_hlYtGQTaFyz_Jrp12-g8nIwtYm2TN36-40Fs")

import asyncio
asyncio.run(main())
