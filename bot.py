import discord
from discord.ext import commands
import sqlite3
import requests
from PIL import Image
from io import BytesIO
import os
import asyncio
import time
import logging

# =========================
# LOGGING
# =========================
logging.getLogger("discord").setLevel(logging.WARNING)

# =========================
# GLOBALS
# =========================
global_lock = asyncio.Lock()
cooldowns = {}

PITY_MAX = 80
COOLDOWN_SECONDS = 10

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# SQLITE SAFE (DOCKER + RENDER)
# =========================
conn = sqlite3.connect("database.db", check_same_thread=False)
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
# SAFE REQUEST
# =========================
def safe_request(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r
        return None
    except:
        return None

# =========================
# OCR SAFE (DOCKER FRIENDLY)
# =========================
def analyze_image(url):
    r = safe_request(url)
    if not r:
        return {"rarity":"Unknown","character":"Unknown","s":False,"a":False}

    try:
        img = Image.open(BytesIO(r.content)).convert("RGB")
    except:
        return {"rarity":"Unknown","character":"Unknown","s":False,"a":False}

    # OCR SAFE IMPORT (IMPORTANT FOR DOCKER)
    try:
        import pytesseract
        text = pytesseract.image_to_string(img).lower()
    except Exception as e:
        print("OCR ERROR:", e)
        return {
            "rarity":"OCR unavailable",
            "character":"Unknown",
            "s":False,
            "a":False
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
# READY EVENT
# =========================
@bot.event
async def on_ready():
    print(f"Bot online as {bot.user}")

# =========================
# PULL COMMAND
# =========================
@bot.command()
async def pull(ctx):

    async with global_lock:

        user_id = str(ctx.author.id)
        now = time.time()

        if user_id in cooldowns:
            if now - cooldowns[user_id] < COOLDOWN_SECONDS:
                await ctx.send("⏳ Cooldown active")
                return

        cooldowns[user_id] = now

        try:
            await ctx.message.delete()
        except:
            pass

        if not ctx.message.attachments:
            await ctx.send("📸 Send a screenshot with !pull")
            return

        img = ctx.message.attachments[0]

        msg = await ctx.send("🎰 Pulling...")
        await asyncio.sleep(1)
        await msg.edit(content="✨ Analyzing image...")
        await asyncio.sleep(1)

        data = analyze_image(img.url)

        user = get_user(ctx.author.id)
        forced_s = (user[3] + 1) >= PITY_MAX

        update_user(
            ctx.author.id,
            force_s=(data["s"] or forced_s),
            force_a=(data["a"] and not forced_s)
        )

        stats = get_user(ctx.author.id)

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
        embed.add_field(
            name=f"#{i+1}",
            value=f"<@{row[0]}> — {row[1]} S-Ranks",
            inline=False
        )

    await ctx.send(embed=embed)

# =========================
# PITY
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
# START BOT
# =========================
token = os.getenv("DISCORD_TOKEN")

if not token:
    print("DISCORD_TOKEN missing")
    exit()

bot.run(token)