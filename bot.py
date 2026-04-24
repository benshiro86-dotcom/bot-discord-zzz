import discord
from discord.ext import commands
from PIL import Image
import pytesseract
import requests
from io import BytesIO
import os

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# OCR analysis
def analyze_image(image_url):
    response = requests.get(image_url)
    img = Image.open(BytesIO(response.content))

    # No need for tesseract path on Render (Linux environment)
    text = pytesseract.image_to_string(img).lower()

    result = {
        "rarity": None,
        "character": None,
        "is_s_rank": False,
        "is_a_rank": False
    }

    # Rank detection
    if "s rank" in text or "s-rank" in text:
        result["rarity"] = "S-Rank ⭐⭐⭐⭐⭐"
        result["is_s_rank"] = True

    elif "a rank" in text or "a-rank" in text:
        result["rarity"] = "A-Rank ⭐⭐⭐⭐"
        result["is_a_rank"] = True

    # Character detection (simple heuristic)
    lines = text.split("\n")
    for line in lines:
        if 3 < len(line) < 30:
            if "rank" not in line:
                result["character"] = line.strip().title()
                break

    return result


@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")


@bot.command()
async def pull(ctx):
    if not ctx.message.attachments:
        await ctx.send("❌ Please send a screenshot with the !pull command.")
        return

    image = ctx.message.attachments[0]

    await ctx.send("🔍 Analyzing pull...")

    data = analyze_image(image.url)

    if data["is_s_rank"]:
        emoji = "🎉🔥"
    elif data["is_a_rank"]:
        emoji = "✨"
    else:
        emoji = "❓"

    msg = f"""
{emoji} **PULL DETECTED** {emoji}

👤 Player: {ctx.author.mention}
🎯 Rank: {data['rarity'] or 'Not detected'}
🧍 Character: {data['character'] or 'Unknown'}
"""

    await ctx.send(msg)


# Run bot with environment variable (IMPORTANT)
bot.run(os.getenv("DISCORD_TOKEN"))