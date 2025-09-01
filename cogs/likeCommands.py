import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime, date
import json
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
API_URL=os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"
MAX_REQUESTS = 3  # ✅ Daily max requests

class LikeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host = API_URL
        self.config_data = self.load_config()
        self.cooldowns = {}
        self.requests_log = {}  # ✅ {user_id: {"count":int, "day":date}}
        self.session = aiohttp.ClientSession()

    # -------------------- CONFIG --------------------
    def load_config(self):
        default_config = {"servers": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    loaded_config = json.load(f)
                    # ensure both keys exist
                    for sid, conf in loaded_config.get("servers", {}).items():
                        conf.setdefault("like_channels", [])
                        conf.setdefault("auto_like", [])
                    return loaded_config
            except json.JSONDecodeError:
                print(f"WARNING: {CONFIG_FILE} is corrupt, resetting.")
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    async def check_channel(self, ctx):
        if ctx.guild is None:
            return True
        guild_id = str(ctx.guild.id)
        like_channels = self.config_data["servers"].get(guild_id, {}).get("like_channels", [])
        return not like_channels or str(ctx.channel.id) in like_channels

    async def cog_load(self):
        pass

    # -------------------- COMMANDS --------------------
    @commands.hybrid_command(name="setlikechannel", description="Sets allowed channels for /like")
    @commands.has_permissions(administrator=True)
    async def set_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        guild_id = str(ctx.guild.id)
        server_conf = self.config_data["servers"].setdefault(guild_id, {})
        like_channels = server_conf.setdefault("like_channels", [])
        server_conf.setdefault("auto_like", [])  # ensure exists

        cid = str(channel.id)
        if cid in like_channels:
            like_channels.remove(cid)
            self.save_config()
            await ctx.send(f"❌ Removed {channel.mention} from allowed /like channels.", ephemeral=True)
        else:
            like_channels.append(cid)
            self.save_config()
            await ctx.send(f"✅ Added {channel.mention} to allowed /like channels.", ephemeral=True)
        @commands.hybrid_command(name="likestats", description="Check your daily like request usage")
    async def like_stats(self, ctx: commands.Context):
        user_id = ctx.author.id
        today = date.today()
        user_data = self.requests_log.get(user_id, {"count": 0, "day": today})

        # Reset if a new day
        if user_data["day"] != today:
            user_data = {"count": 0, "day": today}
            self.requests_log[user_id] = user_data

        used = user_data["count"]
        remaining = MAX_REQUESTS - used

        embed = discord.Embed(
            title="📊 Like Request Stats",
            color=0x3498DB,
            timestamp=datetime.now()
        )
        embed.add_field(name="Used Today", value=f"{used}/{MAX_REQUESTS}", inline=True)
        embed.add_field(name="Remaining", value=f"{remaining}", inline=True)
        embed.set_footer(text="Resets at midnight server time • DEVELOPED BY TANVIR")

        await ctx.send(embed=embed, ephemeral=True)
       

    @commands.hybrid_command(name="like", description="Send likes to a Free Fire player")
    @app_commands.describe(uid="Player UID", server="Region/Server")
    async def like_command(self, ctx: commands.Context, server: str=None, uid: str=None):
        is_slash = ctx.interaction is not None
        if uid and server is None:
            return await ctx.send("UID and server are required", delete_after=10)
        if not await self.check_channel(ctx):
            msg = "This command is not available in this channel."
            if is_slash: await ctx.response.send_message(msg, ephemeral=True)
            else: await ctx.reply(msg, mention_author=False)
            return

        user_id = ctx.author.id
        today = date.today()
        user_data = self.requests_log.get(user_id, {"count": 0, "day": today})

        # reset if a new day
        if user_data["day"] != today:
            user_data = {"count": 0, "day": today}

        if user_data["count"] >= MAX_REQUESTS:
            await ctx.send(f"🚫 You have reached the daily limit of {MAX_REQUESTS} requests.", ephemeral=is_slash)
            return

        # Cooldown check
        cooldown = 30
        if user_id in self.cooldowns:
            last_used = self.cooldowns[user_id]
            remaining = cooldown - (datetime.now() - last_used).seconds
            if remaining > 0:
                await ctx.send(f"⏳ Wait {remaining}s before reusing.", ephemeral=is_slash)
                return
        self.cooldowns[user_id] = datetime.now()

        if not uid.isdigit() or len(uid) < 6:
            await ctx.reply("Invalid UID. Must be numbers only, >=6 chars.", ephemeral=is_slash)
            return

        try:
            async with ctx.typing():
                url = f"{self.api_host}/like?uid={uid}&server={server}"
                async with self.session.get(url) as response:
                    if response.status == 404:
                        return await self._send_player_not_found(ctx, uid)
                    if response.status != 200:
                        return await self._send_api_error(ctx)

                    data = await response.json()

                    # update count
                    user_data["count"] += 1
                    self.requests_log[user_id] = user_data
                    remaining = MAX_REQUESTS - user_data["count"]

                    embed = discord.Embed(
                        title="FREE FIRE LIKE",
                        color=0x2ECC71 if data.get("status") == 1 else 0xE74C3C,
                        timestamp=datetime.now()
                    )
                    if data.get("status") == 1:
                        embed.description = (
                            f"┌  ACCOUNT\n"
                            f"├─ NICKNAME: {data.get('player','Unknown')}\n"
                            f"├─ UID: {uid}\n"
                            f"└─ RESULT:\n"
                            f"   ├─ ADDED: +{data.get('likes_added',0)}\n"
                            f"   ├─ BEFORE: {data.get('likes_before','N/A')}\n"
                            f"   ├─ AFTER: {data.get('likes_after','N/A')}\n"
                            f"📌 Requests remaining: {remaining}/{MAX_REQUESTS}\n"
                        )
                    else:
                        embed.description = (
                            "This UID has reached max likes today.\n"
                            f"📌 Requests remaining: {remaining}/{MAX_REQUESTS}"
                        )

                    embed.set_footer(text="DEVELOPED BY TANVIR")
                    await ctx.send(embed=embed, ephemeral=is_slash)

        except Exception as e:
            print(f"Error in like_command: {e}")
            await self._send_error_embed(ctx, "Critical Error", "Unexpected error.", ephemeral=is_slash)

    # -------------------- HELPERS --------------------
    async def _send_player_not_found(self, ctx, uid):
        embed = discord.Embed(title="Player Not Found", description=f"UID {uid} not found.", color=0xE74C3C)
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_api_error(self, ctx):
        embed = discord.Embed(title="⚠️ Service Down", description="Free Fire API not responding.", color=0xF39C12)
        await ctx.send(embed=embed, ephemeral=True)

    async def _send_error_embed(self, ctx, title, description, ephemeral=True):
        embed = discord.Embed(title=f"❌ {title}", description=description, color=discord.Color.red())
        await ctx.send(embed=embed, ephemeral=ephemeral)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
