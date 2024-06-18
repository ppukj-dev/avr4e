import pandas as pd
import asyncio
import discord
import re
import os
import d20
import uvicorn
from discord.ext import commands
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv


load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
bot = commands.Bot(command_prefix=";;", intents=discord.Intents.all())

app = FastAPI()
origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
    "*",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(bot.start(TOKEN))


@app.get("/")
async def root():
    return {"message": "{0.user}".format(bot)}


class Roll(BaseModel):
    message: str
    username: str
    dump_channel_link: str
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": "[[d20 vs ac a]][[1d8+0]]\nHmmm",
                    "username": "aremiru",
                    "dump_channel_link": "https://discord.com/channels/1226890887443906561/1236547275786944542"
                }
            ]
        }
    }


@app.post("/roll")
async def roll(roll: Roll):
    message = process_message(roll.message)
    server_id = get_server_id(roll.dump_channel_link)
    channel_id = get_channel_id(roll.dump_channel_link)
    guild = bot.get_guild(int(server_id))
    member = guild.get_member_named(roll.username)
    channel = guild.get_channel(int(channel_id))
    await channel.send(f"<@{member.id}>\n{message}")
    return {
        "server": f"{server_id}",
        "channel": f"{channel_id}",
    }


def find_inline_roll(content: str):
    pattern = r'\[\[(.*?)\]\]'
    return re.findall(pattern=pattern, string=content)


def get_server_id(url):
    pattern = r"https://discord.com/channels/(\d+)/(\d+)"
    match = re.search(pattern, url)

    if match:
        return match.group(1)
    else:
        return None


def get_channel_id(url):
    pattern = r"https://discord.com/channels/(\d+)/(\d+)"
    match = re.search(pattern, url)

    if match:
        return match.group(2)
    else:
        return None


def process_message(message: str) -> str:
    inline_rolls = find_inline_roll(message)
    end_text = ""
    if len(inline_rolls) == 0:
        return message
    for inline_roll in inline_rolls:
        result = d20.roll(inline_roll, allow_comments=True)
        comment = f" {result.comment}" if result.comment else ""
        crit = ""
        if result.crit == 2:
            crit = "💀"
        if result.crit == 1:
            crit = "💥"
        inline_replacement = f"`( {result.total}{crit}{comment} )` "
        message = message.replace(f"[[{inline_roll}]]", inline_replacement, 1)
        end_text = f"{end_text}\n{comment}: {result}"
    message = message + end_text
    return message


@bot.event
async def on_ready():
    print("We have logged in as {0.user}".format(bot))


def main():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))


if __name__ == "__main__":
    main()
