import pandas as pd
import asyncio
import discord
import re
import os
import d20
import gspread
import json
import uvicorn
from discord.ext import commands
from repository import CharacterUserMapRepository
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
    if len(inline_rolls) == 0:
        return message

    for inline_roll in inline_rolls:
        result = d20.roll(inline_roll, allow_comments=True)
        if result.comment:
            inline_replacement = f"{result.comment} : {result}\n"
        else:
            inline_replacement = f"{result}\n"
        message = message.replace(f"[[{inline_roll}]]", inline_replacement, 1)

    # for inline_roll in inline_rolls:
    #     result = d20.roll(inline_roll, allow_comments=True)
    #     comment = f" {result.comment}" if result.comment else ""
    #     crit = ""
    #     if result.crit == 2:
    #         crit = "💀"
    #     if result.crit == 1:
    #         crit = "💥"
    #     inline_replacement = f"`( {result.total}{crit}{comment} )` "
    #     message = message.replace(f"[[{inline_roll}]]", inline_replacement, 1)
    #     end_text = f"{end_text}\n{comment}: {result}"
    # message = message + end_text
    return message


@bot.event
async def on_ready():
    print("We have logged in as {0.user}".format(bot))


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command()
async def add_sheet(ctx, url=""):
    spreadsheet_id = get_spreadsheet_id(url)
    if spreadsheet_id == "":
        await ctx.send("Please provide a url")
        return
    df_data = get_df(spreadsheet_id, "data")
    actions_data = get_df(spreadsheet_id, "actions")
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    name = df_data[df_data['field_name'] == 'Name']['value'].iloc[0]
    charaRepo = CharacterUserMapRepository()
    charaRepo.set_character(
        ctx.guild.id,
        ctx.author.id,
        name,
        df_data.to_json(),
        actions_data.to_json())
    await ctx.send(f"Sheet `{name}` is added.", embed=embed)


@bot.command()
async def char(ctx):
    charaRepo = CharacterUserMapRepository()
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    name = character[0]
    df_data = pd.read_json(character[1])
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    await ctx.send(name, embed=embed)


@bot.command()
async def action(ctx, *, args=None):
    await ctx.message.delete()
    charaRepo = CharacterUserMapRepository()
    character = charaRepo.get_actions(ctx.guild.id, ctx.author.id)
    name = character[0]
    df = pd.read_json(character[1])
    if args is None:
        embed = discord.Embed()
        embed.title = f"{name}'s Actions"
        for type1 in df['Type1'].unique().tolist():
            description = ""
            for i, row in df[df['Type1'] == type1].iterrows():
                description += f"- **{row['Name']}** " + \
                    f"({row['Type2']}). " + f"{row['ShortDesc']}\n"
            embed.add_field(name=type1, value=description, inline=False)
    else:
        action = args
        possible_action = df[df['Name'].str.contains(action, na=False, case=False)]
        choosen = 0
        if len(possible_action) <= 0:
            await ctx.send("No actions found")
            return
        elif len(possible_action) > 1:
            idx = 1
            list = ""
            for _, name in possible_action['Name'].items():
                list = list + f"`{idx}. {name}`\n"
                idx += 1

            def followup(message):
                return (
                    message.content.isnumeric() or message.content == "c"
                ) and message.author == ctx.message.author

            description = """Do you mean?\n{}""".format(list)
            embed = discord.Embed(title="Multiple Found", description=description)
            embed.set_footer(text="Type 1-10 to choose, or c to cancel.")
            option_message = await ctx.send(embed=embed)
            try:
                followup_message = await bot.wait_for(
                    "message", timeout=60.0, check=followup
                )
            except asyncio.TimeoutError:
                await option_message.delete()
                await ctx.send("Time Out")
            else:
                if followup_message.content == "c":
                    return
                choosen = int(followup_message.content) - 1
                await option_message.delete()
                await followup_message.delete()
        embed = discord.Embed()
        embed_description = ""
        flavor = possible_action['Flavor'].iloc[choosen]
        effect = possible_action['Effect'].iloc[choosen]
        to_hit = possible_action['To Hit'].iloc[choosen]
        damage = possible_action['Damage'].iloc[choosen]
        image = possible_action['Image'].iloc[choosen]
        action_name = possible_action['Name'].iloc[choosen]
        embed.title = f"{name} uses {action_name}!"
        if to_hit:
            hit_result = d20.roll(to_hit)
            embed_description += f"**Hit**: {hit_result}\n"
        if damage:
            damage_result = d20.roll(damage)
            embed_description += f"**Damage**: {damage_result}\n"
        if flavor:
            embed.add_field(name="Description", value=flavor, inline=False)
        if effect:
            embed.add_field(name="Effect", value=effect, inline=False)
        if image:
            embed.set_image(url=image)
        embed.description = embed_description

    await ctx.send(embed=embed)


def get_spreadsheet_id(url):
    # Regular expression to match the spreadsheet ID in the URL
    pattern = r"/spreadsheets/d/([a-zA-Z0-9-_]+)"
    match = re.search(pattern, url)

    # Check if a match was found
    if match:
        return match.group(1)
    else:
        return ""


def get_df(spreadsheet_id: str, sheet_name: str):
    creds = None
    with open("credentials.json") as f:
        creds = json.load(f)
    gc = gspread.service_account_from_dict(creds)
    sheet = gc.open_by_key(spreadsheet_id)
    worksheet = sheet.worksheet(sheet_name)

    data = worksheet.get_all_records()
    return pd.DataFrame(data)


def create_data_dict(df) -> dict:
    result = {}
    for _, row in df.iterrows():
        category = row['category']
        field_name = row['field_name']
        value = row['value']

        if category not in result:
            result[category] = {}

        result[category][field_name] = value
    return result


def create_embed(data_dict: dict) -> discord.Embed:
    embed = discord.Embed()

    for category, fields in data_dict.items():
        if category == "Special":
            embed.title = fields['Title']
            embed.description = fields['Description']
            embed.set_thumbnail(url=fields['Thumbnail'])
            embed.set_image(url=fields['Image'])
            continue
        field_value = ''
        for field_name, value in fields.items():
            field_value = field_value + f"**{field_name}**: {value}\n"
        embed.add_field(name=category, value=field_value, inline=True)
    return embed


def main():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
    pass


if __name__ == "__main__":
    main()
