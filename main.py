import pandas as pd
import asyncio
import discord
import re
import os
import d20
import gspread
import shlex
import argparse
import json
import uvicorn
from discord.ext import commands
from repository import CharacterUserMapRepository
from pydantic import BaseModel
from pydantic.dataclasses import dataclass, Field
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List


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
    # example1 = {
    #     "message": "[[d20 vs ac a]][[1d8+0]]\nHmmm",
    #     "username": "aremiru",
    #     "dump_channel_link": "https://discord.com/channels/1234/1234"
    # }
    # model_config = {
    #     "json_schema_extra": {
    #         "examples": [
    #             example1
    #         ]
    #     }
    # }


@dataclass
class ActionParam():
    name: str = ""
    damage_bonus: str = ""
    d20_bonus: str = ""
    is_adv: bool = False
    is_dis: bool = False
    targets: List[str] = Field(default_factory=list)
    is_halved: bool = False


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
    return message


@bot.event
async def on_ready():
    print("We have logged in as {0.user}".format(bot))


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command(aliases=["add"])
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
        actions_data.to_json(),
        sheet_url=url
        )
    await ctx.send(f"Sheet `{name}` is added.", embed=embed)


@bot.command(aliases=["update"])
async def update_sheet(ctx, url=""):
    charaRepo = CharacterUserMapRepository()
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    url = character[4]
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
        actions_data.to_json(),
        sheet_url=url)
    await ctx.send(f"Sheet `{name}` is updated.", embed=embed)


@bot.command(aliases=["sheet"])
async def char(ctx):
    charaRepo = CharacterUserMapRepository()
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(character[2])
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)


@bot.command()
async def reset(ctx, *, args=None):
    try:
        await ctx.message.delete()
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        actions = pd.read_json(character[3])
        if args is None:
            actions['Usages'] = actions['MaxUsages']
            message = "All actions are reset."
        else:
            max_usages = actions['MaxUsages']
            actions.loc[actions['ResetOn'] == args, 'Usages'] = max_usages
            message = f"`{args}` actions are reset."
        charaRepo.update_character(character[0], None, actions.to_json())
        embed = discord.Embed()
        embed.title = f"{character[1]}'s Actions"
        description = ""
        for i, row in actions.iterrows():
            if row['MaxUsages'] <= 0:
                continue
            usages_quota = f"({row['Usages']}/{row['MaxUsages']})"
            description += f"- **{row['Name']}** {usages_quota}\n"
        embed.description = description
        await ctx.send(message, embed=embed)
    except Exception as e:
        print(e)
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["a"])
async def action(ctx, *, args=None):
    try:
        await ctx.message.delete()
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        name = character[1]
        actions = pd.read_json(character[3])
        if args is None:
            embed = create_action_list_embed(name, actions)
        else:
            args = translate_cvar(args, character[2])
            embed = await handle_action(args, actions, ctx, name, sheet_id)
        await ctx.send(embed=embed)
    except Exception as e:
        print(e)
        await ctx.send("Error. Please check input again.")


def create_action_list_embed(name, df):
    embed = discord.Embed()
    embed.title = f"{name}'s Actions"
    for type1 in df['Type1'].unique().tolist():
        description = ""
        for i, row in df[df['Type1'] == type1].iterrows():
            usages = ""
            if row['MaxUsages'] > 0:
                usages = f" ({row['Usages']}/{row['MaxUsages']})"
            description += f"- **{row['Name']}** ({row['Type2']})."
            description += f" {row['ShortDesc']}{usages}\n"
        embed.add_field(name=type1, value=description, inline=False)
    return embed


async def handle_action(command, df, ctx, name, sheet_id):
    ap = parse_command(command)
    possible_action = df[df['Name'].str.contains(
        ap.name,
        na=False,
        case=False
        )]
    if len(possible_action) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_action) > 1:
        choosen = await get_user_choice(possible_action, 'Name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    if possible_action['MaxUsages'].iloc[choosen] > 0:
        action_name = possible_action['Name'].iloc[choosen]
        usages = df.loc[df['Name'] == action_name, 'Usages'].iloc[0]
        new_usages = usages - 1 if usages > 0 else 0
        df.loc[df['Name'] == action_name, 'Usages'] = new_usages
        charaRepo = CharacterUserMapRepository()
        charaRepo.update_character(sheet_id, None, df.to_json())
    return create_action_result_embed(possible_action, choosen, name, ap)


def parse_command(message) -> ActionParam:
    # dumb things so negative value in args can be done
    parser = argparse.ArgumentParser(prefix_chars='@@')
    message = message.replace('@@', '')
    message = message.replace(' -b', ' @@b')
    message = message.replace(' -d', ' @@d')
    message = re.sub(r'\badv\b', ' @@adv', message)
    message = re.sub(r'\bdis\b', ' @@dis', message)
    message = message.replace(' -t', ' @@t')
    message = message.replace(' -h', ' @@h')

    parser.add_argument('move', type=str, help='The move name')
    parser.add_argument('@@b', type=str)
    parser.add_argument('@@d', type=str)
    parser.add_argument('@@adv', nargs='?', const=True, default=False)
    parser.add_argument('@@dis', nargs='?', const=True, default=False)
    parser.add_argument('@@t', type=str, action='append')
    parser.add_argument('@@h', nargs='?', const=True, default=False)
    splitted_message = shlex.split(message)
    try:
        args = parser.parse_args(splitted_message)
    except SystemExit as e:
        print("Error System Exit", e)
        return None

    action = args.move
    d20_bonus = format_bonus(args.b) if args.b is not None else ""
    damage_bonus = format_bonus(args.d) if args.d is not None else ""
    is_adv = args.adv is not False
    is_dis = args.dis is not False
    targets = args.t if args.t is not None else []
    is_halved = args.h is not False

    param = ActionParam(
        name=action,
        damage_bonus=damage_bonus,
        d20_bonus=d20_bonus,
        is_adv=is_adv,
        is_dis=is_dis,
        targets=targets,
        is_halved=is_halved
    )

    return param


def translate_cvar(message, data):
    df = pd.read_json(data)
    cvar = df[df['category'] == 'CVAR']
    for _, row in cvar.iterrows():
        if row["field_name"] in ["adv", "dis", "-t", "-b", "-d"]:
            continue
        replaceable = fr"\b{re.escape(row['field_name'])}\b"
        message = re.sub(replaceable, str(row["value"]), message)
    return message


async def get_user_choice(choices, column_name, ctx):
    idx = 1
    list = ""
    for _, name in choices[column_name].items():
        list += f"`{idx}. {name}`\n"
        idx += 1
        if idx > 10:
            break
    embed = discord.Embed(
            title="Multiple Found",
            description=f"Do you mean?\n{list}"
        )
    embed.set_footer(text="Type 1-10 to choose, or c to cancel.")
    option_message = await ctx.send(embed=embed)

    def followup(message):
        return (
            message.content.isnumeric() or message.content == "c"
            ) and message.author == ctx.message.author
    try:
        followup_message = await bot.wait_for(
                "message", timeout=60.0, check=followup
            )
    except asyncio.TimeoutError:
        await option_message.delete()
        await ctx.send("Time Out")
        return None
    else:
        if followup_message.content == "c":
            return None
        choosen = int(followup_message.content) - 1
        await option_message.delete()
        await followup_message.delete()
        return choosen


def create_action_result_embed(
        possible_action, choosen, name, ap: ActionParam):
    embed = discord.Embed()
    max_usages = possible_action['MaxUsages'].iloc[choosen]
    usages = possible_action['Usages'].iloc[choosen]
    action_name = possible_action['Name'].iloc[choosen]
    embed_description = ""
    flavor = possible_action['Flavor'].iloc[choosen]
    effect = possible_action['Effect'].iloc[choosen]
    to_hit = possible_action['To Hit'].iloc[choosen]
    damage = possible_action['Damage'].iloc[choosen]
    image = possible_action['Image'].iloc[choosen]
    range = possible_action['Range'].iloc[choosen]
    def_target = possible_action['DefTarget'].iloc[choosen]
    meta = ""

    def is_aoe(range):
        if (
            range.lower().find("close") != -1 or
            range.lower().find("area") != -1
        ):
            return True
        return False

    embed.title = f"{name} uses {action_name}!"
    hit_description = "To Hit"
    if def_target:
        hit_description = f"To Hit vs {def_target}"
    if len(ap.targets) > 0:
        if is_aoe(range):
            if damage:
                expression = damage + ap.damage_bonus
                expression = expression_str(expression, ap.is_halved)
                damage_result = d20.roll(expression)
                meta += f"**Damage**: {damage_result}\n"
            if to_hit or damage:
                embed.add_field(name="Meta", value=meta, inline=False)
        for target in ap.targets:
            meta = ""
            if to_hit:
                if to_hit[0] == "d":
                    to_hit = "1"+to_hit
                if ap.is_adv and ap.is_dis:
                    pass
                elif ap.is_adv:
                    to_hit = to_hit.replace("1d20", "2d20kh1")
                elif ap.is_dis:
                    to_hit = to_hit.replace("1d20", "2d20kl1")
                expression = to_hit + ap.d20_bonus
                expression = expression_str(expression, ap.is_halved)
                hit_result = d20.roll(expression)
                meta += f"**{hit_description}**: {hit_result}\n"
            if damage and not is_aoe(range):
                damage_result = d20.roll(damage + ap.damage_bonus)
                meta += f"**Damage**: {damage_result}\n"
            if to_hit or damage:
                embed.add_field(name=target, value=meta, inline=False)
    else:
        if to_hit:
            if to_hit[0] == "d":
                to_hit = "1"+to_hit
            if ap.is_adv and ap.is_dis:
                pass
            elif ap.is_adv:
                to_hit = to_hit.replace("1d20", "2d20kh1")
            elif ap.is_dis:
                to_hit = to_hit.replace("1d20", "2d20kl1")
            expression = to_hit + ap.d20_bonus
            expression = expression_str(expression, ap.is_halved)
            hit_result = d20.roll(expression)
            meta += f"**{hit_description}**: {hit_result}\n"
        if damage:
            expression = damage + ap.damage_bonus
            expression = expression_str(expression, ap.is_halved)
            damage_result = d20.roll(expression)
            meta += f"**Damage**: {damage_result}\n"
        if to_hit or damage:
            embed.add_field(name="Meta", value=meta, inline=False)
    if flavor:
        embed.add_field(name="Description", value=flavor, inline=False)
    if effect:
        embed.add_field(name="Effect", value=effect, inline=False)
    if image:
        embed.set_image(url=image)
    if max_usages > 0:
        increment = " (-1)"
        usages_value = draw_quota(max_usages, usages - 1)
        if usages <= 0:
            embed.title = f"{name} cannot use {action_name}."
            usages_value = draw_quota(max_usages, usages - 1)
            increment = " (Out of Usages)"
        usages_value += increment
        embed.add_field(name=action_name, value=usages_value, inline=False)

    embed.description = embed_description
    return embed


@bot.command(aliases=["c"])
async def check(ctx, *, args=None):
    try:
        await ctx.message.delete()
        if args is None:
            await ctx.send("Please specify check to roll.")
            return
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        # sheet_id = character[0]
        name = character[1]
        data = pd.read_json(character[2])
        embed = await handle_check(args, data, ctx, name)
        await ctx.send(embed=embed)
    except Exception as e:
        print(e)
        await ctx.send("Error. Please check input again.")


def create_check_result_embed(possible_check, choosen, name, ap: ActionParam):
    embed = discord.Embed()
    modifier = possible_check['value'].iloc[choosen]
    check_name = possible_check['field_name'].iloc[choosen]

    embed.title = f"{name} makes {check_name} check!"
    dice = "1d20"
    if ap.is_adv and ap.is_dis:
        pass
    elif ap.is_adv:
        dice = "2d20kh1"
    elif ap.is_dis:
        dice = "2d20kl1"
    check_result = d20.roll(dice + format_number(modifier) + ap.d20_bonus)
    embed.description = f"{check_result}"
    return embed


async def handle_check(command, df, ctx, name):
    ap = parse_command(command)
    rollable_check = df[df['is_rollable'] == 'TRUE']
    possible_check = rollable_check[rollable_check['field_name'].str.contains(
        ap.name, case=False
    )]
    if len(possible_check) <= 0:
        await ctx.send("No such check found.")
        return None
    elif len(possible_check) > 1:
        choosen = await get_user_choice(possible_check, 'field_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    return create_check_result_embed(possible_check, choosen, name, ap)


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
        is_rollable = row['is_rollable'] == 'TRUE'

        if category not in result:
            result[category] = {}

        if is_rollable:
            result[category][field_name] = format_number(value)
        else:
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
        if category == "CVAR":
            continue
        field_value = ''
        for field_name, value in fields.items():
            if is_formatted_number(str(value)):
                field_value = field_value + f"{field_name} {value}, "
                continue
            field_value = field_value + f"**{field_name}**: {value}\n"
        field_value = field_value.rstrip(", ")
        field_value = field_value.rstrip()
        embed.add_field(name=category, value=field_value, inline=False)
    return embed


def format_number(value) -> str:
    if int(value) >= 0:
        return f"+{value}"
    else:
        return f"{value}"


def format_bonus(value: str) -> str:
    if len(value) == 0:
        return ""
    if value[0] == "+" or value[0] == "-":
        return value
    else:
        return "+" + value


def is_formatted_number(string):
    pattern = r'^[+-]\d+$'
    return bool(re.match(pattern, string))


def draw_quota(max_usages: int, usages: int) -> str:
    used = max_usages - usages
    if usages <= 0:
        return max_usages * "〇"
    return usages * "◉" + used * "〇"


def halve_flat_modifiers(expression):
    def halve_match(match):
        sign = match.group(1)
        halved_value = f"({match.group(2)}/2)"
        return f"{sign}{halved_value}"

    # Regex pattern to match flat modifiers with an optional sign
    pattern = r'([+-])(\d+)\b'
    # Replace all matches with their halved values
    halved_expression = re.sub(pattern, halve_match, expression)
    return halved_expression


def expression_str(expression: str, is_halved: bool):
    if is_halved:
        expression = halve_flat_modifiers(expression)
    return expression


def main():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
    # bot.run(TOKEN)
    pass


if __name__ == "__main__":
    main()
