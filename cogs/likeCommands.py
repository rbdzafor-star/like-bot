import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime, timedelta
import json
import os
import asyncio

# ---------------- CONFIG ----------------
API_URL = os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"
MAX_REQUESTS = 5
RESET_TIME = timedelta(hours=24)

# ---------------- BOT ADMIN ----------------
ADMIN_USER_IDS = [1215988391066468424]  # <-- aikhane tomar user id diab

# ---------------- GIF ----------------
EMBED_GIF = "https://cdn.discordapp.com/attachments/1382641365799800934/1393525278562717766/standard.gif?ex=68c5e2cc&is=68c4914c&hm=2d66c3d9afc204897a52ae8b8d1482ed9010fdfeb4cba87a7ed8a925953a29b4"

class LikeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host = API_URL
        self.config_data = self.load_config()
        self.cooldowns = {}
        self.requests = {}
        self.session = aiohttp.ClientSession()

    # ---------------- CONFIG ----------------
    def load_config(self):
        default_config = {"servers": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    loaded_config = json.load(f)
                    loaded_config.setdefault("servers", {})
                    return loaded_config
            except json.JSONDecodeError:
                print(f"WARNING: '{CONFIG_FILE}' is corrupt. Resetting.")
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    async def check_channel(self, ctx):
        if ctx.guild is None:
            return True
        guild_id = str(ctx.guild.id)
        like_channels = self.config_data["servers"].get(guild_id, {}).get("like_channels", [])
        return not like_channels or str(ctx.channel.id) in like_channels

    # ---------------- SET LIKE CHANNEL ----------------
    @commands.hybrid_command(
        name="setlikechannel",
        description="Sets channels where /like command is allowed."
    )
    @app_commands.describe(channel="Channel to allow/disallow /like command")
    async def set_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if ctx.author.id not in ADMIN_USER_IDS:
            await ctx.send("🚫 You are not authorized.", ephemeral=True)
            return

        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        like_channels = server_config.setdefault("like_channels", [])
        channel_id_str = str(channel.id)

        if channel_id_str in like_channels:
            like_channels.remove(channel_id_str)
            self.save_config()
            await ctx.send(f"✅ Channel {channel.mention} removed from /like allowed channels.", ephemeral=True)
        else:
            like_channels.append(channel_id_str)
            self.save_config()
            await ctx.send(f"✅ Channel {channel.mention} added to /like allowed channels.", ephemeral=True)

    # ---------------- LIKE COMMAND ----------------
    @commands.hybrid_command(name="like", description="Send likes to a Free Fire player")
    @app_commands.describe(uid="Player UID (numbers only, min 6 digits)")
    async def like_command(self, ctx: commands.Context, server: str = None, uid: str = None):
        is_slash = ctx.interaction is not None

        if uid is None or server is None:
            await ctx.send("❌ UID and server are required.", ephemeral=True)
            return

        if not await self.check_channel(ctx):
            await ctx.send("🚫 This channel is not authorized for /like.", ephemeral=True)
            return

        user_id = ctx.author.id
        now = datetime.now()
        user_requests = self.requests.get(user_id, {"used": 0, "last_reset": now})
        if now - user_requests["last_reset"] > RESET_TIME:
            user_requests = {"used": 0, "last_reset": now}

        if user_requests["used"] >= MAX_REQUESTS:
            await ctx.send("❌ No requests left. Wait 24h for reset.", ephemeral=True)
            return

        # Increment request
        user_requests["used"] += 1
        self.requests[user_id] = user_requests
        remaining = MAX_REQUESTS - user_requests["used"]

        # Cooldown 30s
        cooldown = 30
        if user_id in self.cooldowns:
            last_used = self.cooldowns[user_id]
            remaining_cd = cooldown - (datetime.now() - last_used).seconds
            if remaining_cd > 0:
                await ctx.send(f"⏳ Wait {remaining_cd}s before using /like again.", ephemeral=True)
                return
        self.cooldowns[user_id] = datetime.now()

        if not uid.isdigit() or len(uid) < 6:
            await ctx.send("❌ Invalid UID. Must be numeric, min 6 digits.", ephemeral=True)
            return

        try:
            async with ctx.typing():
                url = f"{self.api_host}/like?uid={uid}&server={server}"
                async with self.session.get(url, timeout=10) as response:
                    if response.status == 404:
                        await self._send_player_not_found(ctx, uid)
                        return
                    if response.status != 200:
                        await self._send_api_error(ctx, response.status)
                        return

                    data = await response.json()
                    embed = discord.Embed(
                        title="✨ FREE FIRE LIKE ✨",
                        color=0x2ECC71 if data.get("status") == 1 else 0xE74C3C,
                        timestamp=datetime.now(),
                    )
                    if data.get("status") == 1:
                        embed.description = (
                            f"**✅ Likes Sent!**\n\n"
                            f"**👤 Player Info**\n```yaml\nNICKNAME: {data.get('player','Unknown')}\nUID: {uid}\n```\n"
                            f"**📊 Like Stats**\n```yaml\nADDED: +{data.get('likes_added',0)}\nBEFORE: {data.get('likes_before','N/A')}\nAFTER: {data.get('likes_after','N/A')}\n```\n"
                            f"**📌 Requests Remaining:** `{remaining}/{MAX_REQUESTS}`"
                        )
                    else:
                        embed.description = "⚠️ UID reached max likes today. Wait 24h."

                    embed.set_image(url="https://cdn.discordapp.com/attachments/1382641365799800934/1393525278562717766/standard.gif?ex=68c5e2cc&is=68c4914c&hm=2d66c3d9afc204897a52ae8b8d1482ed9010fdfeb4cba87a7ed8a925953a29b4")

                    embed.set_footer(text="Developed by Tanvir")
                    await ctx.send(embed=embed, ephemeral=is_slash)


        except asyncio.TimeoutError:
            await self._send_error_embed(ctx, "Timeout", "API took too long to respond.", ephemeral=is_slash)
        except Exception as e:
            await self._send_error_embed(ctx, "Critical Error", f"Unexpected error:\n```{e}```", ephemeral=is_slash)

    # ---------------- ERROR EMBEDS ----------------
    async def _send_player_not_found(self, ctx, uid):
        embed = discord.Embed(
            title="❌ Player Not Found",
            description=f"UID `{uid}` not found.",
            color=0xE74C3C,
            timestamp=datetime.now(),
        )
        embed.set_thumbnail(url=EMBED_GIF)
        embed.set_footer(text="Check UID carefully!")
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_api_error(self, ctx, status):
        embed = discord.Embed(
            title="⚠️ API Error",
            description=f"API returned status {status}.",
            color=0xF39C12,
            timestamp=datetime.now(),
        )
        embed.set_thumbnail(url=EMBED_GIF)
        embed.set_footer(text="Try again later.")
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_error_embed(self, ctx, title, description, ephemeral=True):
        embed = discord.Embed(
            title=f"💥 {title}",
            description=description,
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        embed.set_thumbnail(url=EMBED_GIF)
        embed.set_footer(text="Something went wrong!")
        await ctx.send(embed=embed, ephemeral=ephemeral)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())


async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
