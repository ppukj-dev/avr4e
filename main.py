import pandas as pd
import asyncio
import discord
import re
import os
import d20
import gspread
import shlex
import json
import io
import uvicorn
import requests
import traceback
from discord.ext import commands, tasks
import datetime
from repository import CharacterUserMapRepository
from pydantic import BaseModel
from pydantic.dataclasses import dataclass, Field
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List
from PIL import Image, ImageOps, ImageDraw

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
class TargetParam():
    name: str = ""
    damage_bonus: str = ""
    d20_bonus: str = ""
    is_adv: bool = False
    is_dis: bool = False


@dataclass
class ActionParam():
    name: str = ""
    damage_bonus: str = ""
    d20_bonus: str = ""
    is_adv: bool = False
    is_dis: bool = False
    targets: List[TargetParam] = Field(default_factory=list)
    is_halved: bool = False
    thumbnail: str = ""
    is_critical: bool = False
    usages: int = 1
    multiroll: int = 1


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
    check_timestamps.start()
    print("We have logged in as {0.user}".format(bot))


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command(aliases=["add"])
async def add_sheet(ctx, url=""):
    try:
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")
        data_dict = create_data_dict(df_data)
        embed = create_embed(data_dict)

        # clean empty cells
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0, )
        actions_data['Usages'] = actions_data['Usages'].replace('', 0, )
        actions_data = actions_data.replace('#REF!', None, )
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

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
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["update"])
async def update_sheet(ctx, url=""):
    try:
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        old_actions_data = pd.read_json(io.StringIO(character[3]))
        url = character[4]
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")
        data_dict = create_data_dict(df_data)
        embed = create_embed(data_dict)

        # clean empty cells
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0)
        actions_data['Usages'] = actions_data['Usages'].replace('', 0)
        actions_data = actions_data.replace('#REF!', None)
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        madf = pd.merge(
            actions_data,
            old_actions_data[['Name', 'Usages']],
            on='Name',
            how='left',
            suffixes=('', '_old')
        )
        madf['Usages'] = madf['Usages_old'].combine_first(
            madf['Usages']
        )
        madf = madf.drop(columns=['Usages_old'])

        name = df_data[df_data['field_name'] == 'Name']['value'].iloc[0]
        charaRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            madf.to_json(),
            sheet_url=url)
        await ctx.send(f"Sheet `{name}` is updated.", embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["sheet"])
async def char(ctx):
    charaRepo = CharacterUserMapRepository()
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(io.StringIO(character[2]))
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)


@bot.command()
async def reset(ctx, *, args=None):
    try:
        await ctx.message.delete()
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        actions = pd.read_json(io.StringIO(character[3]))
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
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["a"])
async def action(ctx, *, args=None):
    try:
        await ctx.message.delete()
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        name = character[1]
        data = pd.read_json(io.StringIO(character[2]))
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            embed = create_action_list_embed(name, actions)
        else:
            args = translate_cvar(args, data)
            embed = await handle_action(args, actions, ctx, data, sheet_id)
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command()
async def token(ctx, *, args=None):
    try:
        if args is None:
            await ctx.message.delete()
            charaRepo = CharacterUserMapRepository()
            character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
            data = pd.read_json(io.StringIO(character[2]))
            embed = discord.Embed()
            name = data[data['field_name'] == 'Name']['value'].iloc[0]
            token = data[data['field_name'] == 'Thumbnail']['value'].iloc[0]
            embed.title = name
            embed.set_image(url=token)
            await ctx.send(embed=embed)
        if args == "shinreigumi":
            await ctx.message.delete()
            charaRepo = CharacterUserMapRepository()
            character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
            data = pd.read_json(io.StringIO(character[2]))
            name = data[data['field_name'] == 'Name']['value'].iloc[0]
            token = data[data['field_name'] == 'Thumbnail']['value'].iloc[0]
            new_token = add_border_template(
                token, "shinreigumi_border.png", name)
            file_token = discord.File(new_token, filename=f"{name}.png")
            await ctx.send(file=file_token)
            os.remove(new_token)
    except Exception as e:
        print(e, traceback.format_exc())
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


async def handle_action(command, df, ctx, data, sheet_id):
    ap = parse_command(command)
    possible_action = df[df['Name'].str.contains(
        ap.name,
        na=False,
        case=False
        )]
    ap.thumbnail = data[data['field_name'] == 'Thumbnail']['value'].iloc[0]
    name = data[data['field_name'] == 'Name']['value'].iloc[0]
    if len(possible_action) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_action) > 1:
        choosen = await get_user_choice(possible_action, 'Name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    embed = create_action_result_embed(possible_action, choosen, name, ap)
    max_usages = possible_action['MaxUsages'].iloc[choosen]
    usages = possible_action['Usages'].iloc[choosen]
    if max_usages > 0:
        action_name = possible_action['Name'].iloc[choosen]
        new_usages = usages - ap.usages
        increment = f" ({format_bonus(str(-ap.usages))})"
        if new_usages < 0:
            new_usages = usages
            embed.title = f"{name} cannot use {action_name}."
            increment = f" (Out of Usages; {format_bonus(str(-ap.usages))})"
        elif new_usages > max_usages:
            new_usages = max_usages
        usages_value = draw_quota(max_usages, new_usages)
        usages_value += increment
        embed.add_field(name=action_name, value=usages_value, inline=False)
        df.loc[df['Name'] == action_name, 'Usages'] = new_usages
        charaRepo = CharacterUserMapRepository()
        charaRepo.update_character(sheet_id, None, df.to_json())
    return embed


def parse_command(message) -> ActionParam:
    appended_args = [
        "-b", "-d", "adv", "dis", "-adv", "-dis"
    ]
    general_args = [
        "-h", "-crit", "-u", "crit", "-rr"
    ]
    dict_of_args = {}

    # for general args
    splitted_message = shlex.split(message)
    for idx, arg in enumerate(splitted_message):
        if arg in general_args:
            dict_of_args[arg] = idx

    splitted_message = message.split("-t")
    if len(splitted_message) < 1:
        return None
    targets_string = splitted_message[1:]
    message = splitted_message[0]

    first_arg_idx = 99
    splitted_message = shlex.split(message)
    for idx, arg in enumerate(splitted_message):
        if arg in appended_args or arg in general_args:
            if idx < first_arg_idx:
                first_arg_idx = idx
        if arg in appended_args:
            dict_of_args[arg] = idx
    action = " ".join(splitted_message[:first_arg_idx])

    param = ActionParam(
        name=action,
        damage_bonus="",
        d20_bonus="",
        is_adv=False,
        is_dis=False,
        targets=[],
        is_halved=False,
        thumbnail="",
        is_critical=False,
        usages=1
    )

    for key, value in dict_of_args.items():
        if value == -1:
            continue
        if key == "-b":
            param.d20_bonus = format_bonus(splitted_message[value+1])
        elif key == "-d":
            param.damage_bonus = format_bonus(splitted_message[value+1])
        elif key == "adv" or key == "-adv":
            param.is_adv = True
        elif key == "dis" or key == "-dis":
            param.is_dis = True
        elif key == "-h":
            param.is_halved = True
        elif key == "-crit" or key == "crit":
            param.is_critical = True
        elif key == "-u":
            param.usages = int(splitted_message[value+1])
        elif key == "-rr":
            param.multiroll = int(splitted_message[value+1])

    for idx, target_string in enumerate(targets_string):
        target = parse_target_param(target_string)
        target.d20_bonus = param.d20_bonus + target.d20_bonus
        target.damage_bonus = param.damage_bonus + target.damage_bonus
        target.is_adv = param.is_adv or target.is_adv
        target.is_dis = param.is_dis or target.is_dis
        param.targets.append(target)

    if len(param.targets) == 0:
        param.targets.append(
            TargetParam(
                name="Meta",
                damage_bonus=param.damage_bonus,
                d20_bonus=param.d20_bonus,
                is_adv=param.is_adv,
                is_dis=param.is_dis
            )
        )

    return param


def parse_target_param(message) -> TargetParam:
    list_of_args = [
        "-b", "-d", "adv", "dis", "-dis", "-adv"
    ]
    dict_of_args = {}

    first_arg_idx = 99
    splitted_message = shlex.split(message)
    for idx, arg in enumerate(splitted_message):
        if arg in list_of_args:
            if idx < first_arg_idx:
                first_arg_idx = idx
            dict_of_args[arg] = idx
    target_name = " ".join(splitted_message[:first_arg_idx])

    param = TargetParam(
        name=target_name,
        damage_bonus="",
        d20_bonus="",
        is_adv=False,
        is_dis=False
    )

    for key, value in dict_of_args.items():
        if value == -1:
            continue
        if key == "-b":
            param.d20_bonus = format_bonus(splitted_message[value+1])
        elif key == "-d":
            param.damage_bonus = format_bonus(splitted_message[value+1])
        elif key == "adv" or key == "-adv":
            param.is_adv = True
        elif key == "dis" or key == "-dis":
            param.is_dis = True

    return param


def translate_cvar(message, df):
    cvar = df[df['category'] == 'CVAR']
    for _, row in cvar.iterrows():
        if row["field_name"].lower() in [
                    "adv", "dis", "-t", "-b", "-d",
                    "crit", "-u", "-adv", "-dis", "crit",
                    "-h"
                ]:
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
    action_name = possible_action['Name'].iloc[choosen]
    embed_description = ""
    critdie = ""
    flavor = str(possible_action['Flavor'].iloc[choosen])
    effect = str(possible_action['Effect'].iloc[choosen])
    to_hit = str(possible_action['To Hit'].iloc[choosen])
    damage = str(possible_action['Damage'].iloc[choosen])
    image = str(possible_action['Image'].iloc[choosen])
    range = str(possible_action['Range'].iloc[choosen])
    def_target = str(possible_action['DefTarget'].iloc[choosen])
    if 'FreeText' in possible_action:
        embed_description = str(possible_action['FreeText'].iloc[choosen])
    if 'Critdie' in possible_action:
        critdie = format_bonus(str(possible_action['Critdie'].iloc[choosen]))
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
    if is_aoe(range):
        if damage:
            expression = damage + ap.damage_bonus
            expression = expression_str(expression, ap.is_halved)
            damage_result = d20.roll(expression)
            crit_expression = crit_damage_expression(expression) + critdie
            crit_result = d20.roll(crit_expression)
    for target in ap.targets:
        meta = ""
        if not ap.is_critical and to_hit:
            if to_hit[0] == "d":
                to_hit = "1"+to_hit
            if target.is_adv and target.is_dis:
                pass
            elif target.is_adv:
                to_hit = to_hit.replace("1d20", "2d20kh1")
            elif target.is_dis:
                to_hit = to_hit.replace("1d20", "2d20kl1")
            expression = to_hit + target.d20_bonus
            expression = expression_str(expression, ap.is_halved)
            hit_result = d20.roll(expression)
            meta += f"**{hit_description}**: {hit_result}\n"
        if damage and not is_aoe(range):
            expression = damage + target.damage_bonus
            expression = expression_str(expression, ap.is_halved)
            if ap.is_critical or (to_hit and hit_result.crit == 1):
                expression = crit_damage_expression(expression) + critdie
            damage_result = d20.roll(expression)
            meta += f"**Damage**: {damage_result}\n"
        elif damage and is_aoe(range):
            aoedamage = damage_result
            if ap.is_critical or (to_hit and hit_result.crit == 1):
                aoedamage = crit_result
            meta += f"**Damage**: {aoedamage}\n"
        if to_hit or damage:
            embed.add_field(name=target.name, value=meta, inline=False)
    if flavor:
        embed.add_field(name="Description", value=flavor, inline=False)
    if effect:
        embed.add_field(name="Effect", value=effect, inline=False)
    if image:
        embed.set_image(url=image)
    if ap.thumbnail:
        embed.set_thumbnail(url=ap.thumbnail)

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
        data = pd.read_json(io.StringIO(character[2]))
        embed = await handle_check(args, data, ctx, name)
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def create_check_result_embed(possible_check, choosen, name, ap: ActionParam):
    embed = discord.Embed()
    modifier = possible_check['value'].iloc[choosen]
    check_name = possible_check['field_name'].iloc[choosen]

    embed.title = f"{name} makes {check_name} check!"
    if ap.multiroll > 1:
        for i in range(ap.multiroll):
            dice = "1d20"
            if ap.is_adv and ap.is_dis:
                pass
            elif ap.is_adv:
                dice = "2d20kh1"
            elif ap.is_dis:
                dice = "2d20kl1"
            expression = dice + format_number(modifier) + str(ap.d20_bonus)
            expression = expression_str(expression, ap.is_halved)
            check_result = d20.roll(expression)
            embed.add_field(
                name=f"Check {i+1}",
                value=check_result,
                inline=True
            )
    else:
        dice = "1d20"
        if ap.is_adv and ap.is_dis:
            pass
        elif ap.is_adv:
            dice = "2d20kh1"
        elif ap.is_dis:
            dice = "2d20kl1"
        expression = dice + format_number(modifier) + str(ap.d20_bonus)
        expression = expression_str(expression, ap.is_halved)
        check_result = d20.roll(expression)
        embed.description = f"{check_result}"
    if ap.thumbnail:
        embed.set_thumbnail(url=ap.thumbnail)
    return embed


async def handle_check(command, df, ctx, name):
    ap = parse_command(command)
    rollable_check = df[df['is_rollable'] == 'TRUE']
    possible_check = rollable_check[rollable_check['field_name'].str.contains(
        ap.name, case=False
    )]
    ap.thumbnail = df[df['field_name'] == 'Thumbnail']['value'].iloc[0]
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

    pattern = r'([+-])(\d+)\b'
    halved_expression = re.sub(pattern, halve_match, expression)
    return halved_expression


def expression_str(expression: str, is_halved: bool):
    if is_halved:
        expression = halve_flat_modifiers(expression)
    return expression


def crit_damage_expression(expression: str):
    pattern = r'([\d]+)d([\d]+)[khrmiaope]*[\d]*'

    def replace_dice(match):
        dice_count = match.group(1)
        dice_value = match.group(2)
        return f"({dice_count}*{dice_value})"

    modified_expression = re.sub(pattern, replace_dice, expression)

    return modified_expression


def add_border_template(url, template_path, name=""):
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to download image: {response.status_code}")
    img = Image.open(io.BytesIO(response.content)).convert("RGBA")
    template = Image.open(template_path).convert("RGBA")

    # Resize the image to fit within the template's inner circle
    template_size = template.size
    img = ImageOps.fit(img, template_size, centering=(0.5, 0.5))

    # Create a circular mask for the image
    mask = Image.new('L', template_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((1, 1, template_size[0]-1, template_size[1]-1), fill=255)

    # Apply the circular mask to the image
    img.putalpha(mask)

    # Composite the image onto the template
    image_path = f"temp/{name}.png"
    final_image = Image.alpha_composite(img, template)
    final_image.save(image_path)
    return image_path


utc = datetime.timezone.utc
times = [
    datetime.time(hour=0, tzinfo=utc),
    datetime.time(hour=12, tzinfo=utc)
]


@tasks.loop(time=times)
async def check_timestamps():
    channel_calendar = bot.get_channel(1265647805867888741)
    # channel_ooc = bot.get_channel(939933100752924693)
    start_date = datetime.datetime(2024, 8, 17, 0, 0, 0, tzinfo=utc)
    now = datetime.datetime.now(utc)
    delta = now - start_date
    total_sessions = int(1 + delta.total_seconds() // (60 * 60 * 12))
    start_month = 2
    month_number = int((start_month + ((total_sessions-1) // 7)) % 12)
    chapter_number = total_sessions // 15 + 1
    # month_list = [
    #     "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    #     "Juli", "Agustus", "September", "Oktober", "November",
    #     "Desember"
    # ]
    # month = month_list[month_number]
    month = f"月 {month_number+1:02}"
    month_season_dict = {
        3: "🌸", 4: "🌸", 5: "🌸",
        6: "🌞", 7: "🌞", 8: "🌞",
        9: "🍁", 10: "🍁", 11: "🍁",
        12: "❄️", 1: "❄️", 2: "❄️"
    }
    season = month_season_dict[month_number+1]
    session_number = two_digit(total_sessions)
    channel_name = f"📅 {month} {season} - {chapter_number}.{session_number}"
    # await channel_ooc.send("Ganti Tanggal")
    try:
        await channel_calendar.edit(name=channel_name)
    except Exception as e:
        print(e, traceback.format_exc())    


def two_digit(number):
    if number < 10:
        return f"0{number}"
    return str(number)


def main():
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
    # bot.run(TOKEN)
    pass


if __name__ == "__main__":
    main()
