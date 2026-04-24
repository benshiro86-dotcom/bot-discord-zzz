import discord
from discord.ext import commands
import sqlite3
import pytesseract
from PIL import Image
import requests
from io import BytesIO
import re
import os
import asyncio
import time
import logging
import aiohttp

# =========================
# LOGGING SAFE (Render debug)
# =========================
logging.getLogger("discord").setLevel(logging.WARNING)

# =========================
# GLOBALS (ANTI 429 + STABILITY)
# =========================
global_lock = asyncio.Lock()
user_cache = {}
session = None

PITY_MAX = 80
COOLDOWN_SECONDS = 10
cooldowns = {}

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    reconnect=True
)

# =========================
# DATABASE
# =========================
conn = sqlite3.connect("database.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    s_rank INTEGER DEFAULT 0,
    a_rank INTEGER DEFAULT 0,
    pity INTEGER DEFAULT 0
)
""")
conn.commit()

# =========================
# DB FUNCTIONS
# =========================
def get_user(user_id):
    c.execute("SELECT * FROM users WHERE user_id=?", (str(user_id),))
    user = c.fetchone()

    if not user:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (str(user_id),))
        conn.commit()
        return (user_id, 0, 0, 0)

    return user


def update_user(user_id, force_s=False, force_a=False):
    user = get_user(user_id)

    pity = user[3] + 1
    s_rank = user[1]
    a_rank = user[2]

    # PITY SYSTEM
    if pity >= PITY_MAX:
        force_s = True
        pity = 0

    if force_s:
        s_rank += 1
        pity = 0
    elif force_a:
        a_rank += 1

    c.execute("""
    UPDATE users
    SET s_rank=?, a_rank=?, pity=?
    WHERE user_id=?
    """, (s_rank, a_rank, pity, str(user_id)))

    conn.commit()

# =========================
# OCR (SAFE FOR RENDER)
# =========================
def analyze_image(url):
    try:
        img_data = requests.get(url, timeout=10).content
        img = Image.open(BytesIO(img_data))

        text = pytesseract.image_to_string(img).lower()

    except Exception as e:
        print("OCR ERROR:", e)
        return {
            "rarity": "Unknown",
            "character": "Unknown",
            "s": False,
            "a": False
        }

    result = {
        "rarity": "Unknown",
        "character": "Unknown",
        "s": False,
        "a": False
    }

    if "s-rank" in text or "s rank" in text:
        result["rarity"] = "S-Rank ⭐⭐⭐⭐⭐"
        result["s"] = True

    elif "a-rank" in text or "a rank" in text:
        result["rarity"] = "A-Rank ⭐⭐⭐⭐"
        result["a"] = True

    for line in text.split("\n"):
        line = line.strip()
        if 3 < len(line) < 25 and "rank" not in line:
            result["character"] = line.title()
            break

    return result

# =========================
# EMBED
# =========================
def build_embed(ctx, data, stats):
    embed = discord.Embed(
        title="🎰 GACHA RESULT",
        color=0xffcc00 if data["s"] else 0x00ccff if data["a"] else 0xaaaaaa
    )

    embed.add_field(name="Player", value=ctx.author.mention, inline=False)
    embed.add_field(name="Rarity", value=data["rarity"], inline=True)
    embed.add_field(name="Character", value=data["character"], inline=True)

    embed.add_field(name="S-Ranks", value=stats[1], inline=True)
    embed.add_field(name="A-Ranks", value=stats[2], inline=True)
    embed.add_field(name="Pity", value=stats[3], inline=True)

    if stats[3] >= 70:
        embed.add_field(name="⚠️ Soft Pity", value="Increased S-Rank chance", inline=False)

    if stats[3] >= PITY_MAX:
        embed.add_field(name="🔥 GUARANTEED", value="Pity triggered!", inline=False)

    return embed

# =========================
# SAFE USER CACHE
# =========================
async def safe_fetch_user(user_id):
    if user_id in user_cache:
        return user_cache[user_id]

    user = await bot.fetch_user(int(user_id))
    user_cache[user_id] = user
    return user

# =========================
# READY EVENT (FIX STATUS 1 + DOUBLE START)
# =========================
@bot.event
async def on_ready():
    if getattr(bot, "started", False):
        return

    bot.started = True
    print(f"Bot online as {bot.user}")

# =========================
# AIOHTTP SESSION (SAFE INIT)
# =========================
@bot.event
async def setup_hook():
    global session
    session = aiohttp.ClientSession()

# =========================
# 🎰 PULL COMMAND
# =========================
@bot.command()
async def pull(ctx):

    async with global_lock:

        user_id = str(ctx.author.id)
        now = time.time()

        # COOLDOWN
        if user_id in cooldowns:
            if now - cooldowns[user_id] < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - (now - cooldowns[user_id]))
                await ctx.send(f"⏳ Wait {remaining}s")
                return

        cooldowns[user_id] = now

        # DELETE USER MESSAGE
        try:
            await ctx.message.delete()
        except:
            pass

        if not ctx.message.attachments:
            await ctx.send("📸 Send a screenshot with `!pull`")
            return

        img = ctx.message.attachments[0]

        # ANIMATION
        msg = await ctx.send("🎰 Pulling...")
        await asyncio.sleep(1)
        await msg.edit(content="✨ Summoning...")
        await asyncio.sleep(1)

        # OCR
        data = analyze_image(img.url)

        user = get_user(ctx.author.id)
        next_pity = user[3] + 1
        forced_s = next_pity >= PITY_MAX

        update_user(
            ctx.author.id,
            force_s=(data["s"] or forced_s),
            force_a=(data["a"] and not forced_s)
        )

        stats = get_user(ctx.author.id)

        embed = build_embed(ctx, data, stats)

        await msg.edit(content=None, embed=embed)

# =========================
# LEADERBOARD
# =========================
@bot.command()
async def leaderboard(ctx):

    c.execute("SELECT user_id, s_rank FROM users ORDER BY s_rank DESC LIMIT 10")
    rows = c.fetchall()

    embed = discord.Embed(title="🏆 Leaderboard", color=0xffd700)

    for i, row in enumerate(rows):
        user = await safe_fetch_user(row[0])
        embed.add_field(name=f"#{i+1} {user.name}", value=f"{row[1]} S-Ranks", inline=False)

    await ctx.send(embed=embed)

# =========================
# PITY COMMAND
# =========================
@bot.command()
async def pity(ctx):
    user = get_user(ctx.author.id)

    embed = discord.Embed(
        title="📊 Pity",
        color=0xff5555 if user[3] >= 70 else 0x00ff99
    )

    embed.add_field(name="Current pity", value=user[3], inline=False)

    await ctx.send(embed=embed)

# =========================
# SAFE BOT START (FIX STATUS 1)
# =========================
token = os.getenv("DISCORD_TOKEN")

if not token:
    print("ERROR: DISCORD_TOKEN is missing")
    exit()

bot.run(token)