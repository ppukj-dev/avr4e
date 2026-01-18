import random
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
# import uvicorn
import requests
import traceback
from discord.ext import commands, tasks
from discord.ui import View, Button
from view import generator
import datetime
from repository import CharacterUserMapRepository, GachaMapRepository
from repository import DowntimeMapRepository
from repository import MonsterListRepository
from repository import MonstersUserMapRepository
from repository import BetaEventMapRepository
from repository import InitiativeRepository
from dnd_xml_parser import read_character_file, character_to_excel
import constant
from pagination import Paginator
from pydantic import BaseModel
from pydantic.dataclasses import dataclass, Field
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List
from PIL import Image, ImageOps, ImageDraw
from beta import BetaChoice
from services.initiative import register_initiative_commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
bot = commands.Bot(
    command_prefix=";;",
    intents=discord.Intents.all(),
    help_command=None
)
charaRepo = None
gachaRepo = None
downtimeRepo = None
monsterRepo = None
betaEventMapRepo = None
initRepo = None
initiative_service = None


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
    level: int = 0
    is_init: bool = False
    name_override: str = ""


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


def get_server_id(url: str):
    pattern = r"https://discord.com/channels/(\d+)/(\d+)"
    match = re.search(pattern, url)

    if match:
        return match.group(1)
    else:
        return None


def get_channel_id(url: str):
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
    daily_task_run.start()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)
    print("We have logged in as {0.user}".format(bot))


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command()
async def help(ctx):
    embed = discord.Embed()
    embed.title = "Avr4e Commands"
    prefix = bot.command_prefix if isinstance(bot.command_prefix, str) else ";;"
    desc = ""
    desc += "## Commands List\n"
    desc += f"- Add to Discord: `{prefix}add <link to sheet>`\n"
    desc += f"- Update: `{prefix}update`\n"
    desc += "\n"
    desc += "### Actions\n"
    desc += f"- List: `{prefix}a`\n"
    desc += f"  - Filter (case-insensitive, partial): `{prefix}a -l <type>`\n"
    desc += f"- Do action: `{prefix}a <action name>`\n"
    desc += f"- Checks: `{prefix}c <skill name>`\n"
    desc += "- Action & Check Modifiers:\n"
    desc += f"  - Adv/Dis: `{prefix}a <action> adv/dis` `{prefix}c <skill> adv/dis`\n"
    desc += f"  - Situational Modifier: `{prefix}a <action> -b <amount>` "
    desc += f"`{prefix}c <skill> -b <amount>`\n"
    desc += f"  - Human Mode: `{prefix}a <action> -h` `{prefix}c <skill> -h`\n"
    desc += f"  - Multiroll X times: `{prefix}a <action> -rr X` `{prefix}c <skill> -rr X`\n"
    desc += f"  - Check Level DC: `{prefix}c <skill> -l X`\n"
    desc += f"  - Initiative via Check: `{prefix}c Initiative` or `{prefix}c <skill> -init`\n"
    desc += "  - Action Only:\n"
    desc += f"    - Situational Damage: `{prefix}a <action> -d <amount>`\n"
    desc += f"    - Multi Target: `{prefix}a <action> -t <target1> -t <target2>`\n"
    desc += f"    - Use X Power Point: `{prefix}action <action_name> -u X`\n"
    desc += f"    - Autocrit: `{prefix}a <action_name> crit`\n"
    desc += "\n"
    desc += "### Initiative\n"
    desc += f"- Begin tracker: `{prefix}i begin`\n"
    desc += f"- Join with sheet: `{prefix}i join`\n"
    desc += "  - Can also join using check roll for both monster and player.\n"
    desc += f"- Add manual: `{prefix}i add <name> <mod>` or `{prefix}i add <name> -p <value>`\n"
    desc += f"- Edit initiative position: `{prefix}i edit <name>`\n"
    desc += f"- Next turn: `{prefix}i next`\n"
    desc += f"- End tracker: `{prefix}i end`\n"
    desc += f"- Monster check name override: `{prefix}mc <check> -name <name>`\n"
    desc += "\n"
    desc += "### Monsters\n"
    desc += f"- Add monster sheet: `{prefix}madd <sheet url>`\n"
    desc += f"- Update monster sheet: `{prefix}mupdate <sheet url>`\n"
    desc += f"- View monster sheet: `{prefix}msheet <monster name>`\n"
    desc += f"- Reset monster usages: `{prefix}mreset`\n"
    desc += f"- Monster action: `{prefix}ma <action name>`\n"
    desc += f"- Monster check: `{prefix}mc <check name>`\n"
    desc += "\n"
    desc += "**Taking Rest**\n"
    desc += f"- Short Rest: `{prefix}reset sr`\n"
    desc += f"- Extended Rest: `{prefix}reset`"
    embed.description = desc

    await ctx.send(embed=embed)


@bot.command(aliases=["add"])
async def add_sheet(ctx: commands.Context, url=""):
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
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0, )
        actions_data['Usages'] = actions_data['Usages'].replace('', 0, )
        actions_data = actions_data.replace('#REF!', None, )
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        name = df_data[df_data['field_name'] == 'Name']['value'].iloc[0]
        charaRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            actions_data.to_json(),
            sheet_url=url
            )
        await ctx.send(f"Sheet `{name}` is added.", embed=embed)
    except PermissionError:
        await ctx.send("Error. Please check your sheet permission.")
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["update"])
async def update_sheet(ctx: commands.Context, url=""):
    try:
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
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0)
        actions_data['Usages'] = actions_data['Usages'].replace('', 0)
        actions_data = actions_data.replace('#REF!', None)
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        old_actions_data['Usages_numeric'] = pd.to_numeric(
            old_actions_data['Usages'], errors='coerce').fillna(0)
        madf = pd.merge(
            actions_data,
            old_actions_data[['Name', 'Usages_numeric']],
            on='Name',
            how='left'
        )
        madf['Usages'] = madf['Usages_numeric'].combine_first(
            madf['Usages']
        )
        madf = madf.drop(columns=['Usages_numeric'])

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
async def char(ctx: commands.Context):
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(io.StringIO(character[2]))
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)


@bot.command()
async def reset(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
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
async def action(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        name = character[1]
        data = pd.read_json(io.StringIO(character[2]))
        actions = pd.read_json(io.StringIO(character[3]))

        filter_type = None
        if args is None:
            filter_type = ""
        else:
            try:
                parsed_args = shlex.split(args)
            except ValueError:
                parsed_args = args.split()
            if parsed_args and parsed_args[0].lower() in ("-l", "-list"):
                filter_type = " ".join(parsed_args[1:]).strip()
            if filter_type is None:
                args = translate_cvar(args, data)
                ap = parse_command(args)
                if ap.targets:
                    for target in ap.targets:
                        if not target.name or target.name in ("Meta",) or target.name.startswith("Attack "):
                            continue
                        resolved = await resolve_initiative_target(ctx, target.name)
                        if resolved is None:
                            return
                        target.name = resolved
                embed = await handle_action(args, actions, ctx, data, sheet_id, ap=ap)
                if embed is None:
                    return
                await ctx.send(embed=embed)
                return

        if filter_type is not None:
            filter_type = filter_type or ""
            embeds = create_action_list_embed(name, actions, filter_type)
            view = Paginator(ctx.author, embeds)
            if len(embeds) <= 1:
                view = None
            await ctx.send(embed=embeds[0], view=view)
            return
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again. " + str(e))


@bot.command()
async def token(ctx: commands.Context, *, args=None):
    try:
        if args is None:
            await ctx.message.delete()
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


def create_action_list_embed(name: str, df: pd.DataFrame, filter_type=""):
    max_length_description = 2500
    field_dict = {}
    embeds = []
    description = ""
    # embed.title = f"{name}'s Actions"
    try:
        if filter_type != "":
            filter_value = filter_type.strip()
            df = df[
                df['Type1']
                .fillna('')
                .astype(str)
                .str.contains(filter_value, case=False, regex=False)
            ]
            if df.empty:
                embed = discord.Embed()
                embed.title = f"{name}'s Actions"
                embed.description = (
                    f"No actions found for `{filter_type}`."
                )
                return [embed]
        for type1 in df['Type1'].unique().tolist():
            field_dict[type1] = ""
            for _, row in df[df['Type1'] == type1].iterrows():
                action_name = row['Name']
                usages = ""
                if row['MaxUsages'] > 0:
                    usages = f" ({row['Usages']}/{row['MaxUsages']})"
                type2 = ""
                if row['Type2']:
                    type2 = f" ({row['Type2']})"
                field_dict[type1] += f"- **{row['Name']}**{type2}."
                field_dict[type1] += f" {row['ShortDesc']}{usages}\n"
    except Exception:
        raise ValueError(f"Error Here: {action_name}")

    for key, value in field_dict.items():
        if key != "":
            description += f"### {key}\n"
        description += value

    i = 1
    while len(description) > max_length_description:
        embed = discord.Embed()
        embed.title = f"{name}'s Actions"
        newline_index = description[:max_length_description].rfind("\n")
        embed.description = description[:newline_index]
        embed.set_footer(text=f"Page {i}")
        embeds.append(embed)
        description = description[newline_index:]
        i += 1

    embed = discord.Embed()
    embed.title = f"{name}'s Actions"
    embed.description = description
    if i > 1:
        embed.set_footer(text=f"Page {i}")
    embeds.append(embed)

    return embeds


async def handle_action(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context,
        data: pd.DataFrame,
        sheet_id: str,
        ap: ActionParam = None):
    if ap is None:
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
    embed = create_action_result_embed(possible_action, choosen, name, ap, ctx)
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
        charaRepo.update_character(sheet_id, None, df.to_json())
    return embed


def parse_command(message: str) -> ActionParam:
    appended_args = [
        "-b", "-d", "adv", "dis", "-adv", "-dis"
    ]
    general_args = [
        "-h", "-crit", "-u", "crit", "-rr", "-l", "-init", "-name"
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
        elif key == "-l":
            param.level = int(splitted_message[value+1])
        elif key == "-init":
            param.is_init = True
        elif key == "-name":
            if value + 1 < len(splitted_message):
                param.name_override = " ".join(
                    splitted_message[value+1:value+2])

    for idx, target_string in enumerate(targets_string):
        target = parse_target_param(target_string)
        target.d20_bonus = param.d20_bonus + target.d20_bonus
        target.damage_bonus = param.damage_bonus + target.damage_bonus
        target.is_adv = param.is_adv or target.is_adv
        target.is_dis = param.is_dis or target.is_dis
        param.targets.append(target)

    if len(param.targets) == 0:
        if param.multiroll > 1:
            for i in range(param.multiroll):
                param.targets.append(
                    TargetParam(
                        name=f"Attack {i+1}",
                        damage_bonus=param.damage_bonus,
                        d20_bonus=param.d20_bonus,
                        is_adv=param.is_adv,
                        is_dis=param.is_dis
                    )
                )
        else:
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


def parse_target_param(message: str) -> TargetParam:
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


async def get_user_choice(
        choices: pd.DataFrame,
        column_name: str,
        ctx: commands.Context):
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

    def followup(message: discord.Message):
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
        await followup_message.delete()
        if followup_message.content == "c":
            await option_message.edit(content="Cancelled", embed=None)
            return None
        choosen = int(followup_message.content) - 1
        await option_message.delete()
        return choosen


async def resolve_initiative_target(
        ctx: commands.Context,
        target_name: str):
    if not initiative_service:
        return target_name
    state = initiative_service.load_state(ctx)
    if not state.get("active"):
        return target_name
    matches = initiative_service.find_matching_combatants(
        state["combatants"], target_name)
    if not matches:
        return target_name
    if len(matches) == 1:
        resolved_name = matches[0][1]
        return resolved_name

    limited_matches = matches[:10]
    choices = "\n".join(
        f"{i}. {name}" for i, (_, name) in enumerate(limited_matches, 1)
    )
    embed = discord.Embed(
        title="Multiple matches found",
        description="Which combatant are you targeting?\n" + choices,
        color=discord.Color.red()
    )
    embed.set_footer(text="Reply with the number of the combatant you want to target.")
    prompt_message = await ctx.send(embed=embed)

    def check(m):
        return (
            m.author.id == ctx.author.id
            and m.channel.id == ctx.channel.id
            and m.content.isdigit()
        )

    try:
        msg = await bot.wait_for("message", check=check, timeout=30.0)
        index = int(msg.content) - 1
        if index < 0 or index >= len(limited_matches):
            await ctx.send("Invalid selection number. Targeting cancelled.")
            await prompt_message.delete()
            await msg.delete()
            return None
        selected_name = limited_matches[index][1]
        await prompt_message.delete()
        await msg.delete()
        return selected_name
    except asyncio.TimeoutError:
        await ctx.send("No response received. Targeting cancelled.")
        await prompt_message.delete()
        return None


def create_action_result_embed(
        possible_action: pd.DataFrame,
        choosen: int,
        name: str,
        ap: ActionParam,
        ctx: commands.Context = None):
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

    def is_aoe(range: str):
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
            suffix = ""
            if def_target and ctx:
                defense_value = get_initiative_defense(
                    ctx, target.name, def_target)
                if defense_value is not None:
                    kept_values = get_kept_d20_values(hit_result)
                    if kept_values and 1 in kept_values:
                        status = "**MISS** (natural 1)"
                        suffix = f" ({status})"
                    else:
                        if defense_value == 0 or hit_result.total >= defense_value:
                            status = "**HIT**"
                        else:
                            status = "**MISS**"
                        suffix = f" ({status} vs {defense_value})"
            meta += f"**{hit_description}**: {hit_result}{suffix}\n"
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
async def check(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        if args is None:
            await ctx.send("Please specify check to roll.")
            return
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        # sheet_id = character[0]
        name = character[1]
        data = pd.read_json(io.StringIO(character[2]))
        result = await handle_check(args, data, ctx, name)
        if result is None:
            return
        embed, check_name, results, modifier_value, ap = result
        if check_name.casefold() == "initiative":
            ap.is_init = True
        if ap.is_init and initiative_service:
            def _stat_value(key: str):
                value = initiative_service.find_field_value(data, key)
                if value is None or pd.isna(value):
                    return "?"
                return value
            stats = {
                "ac": _stat_value("AC"),
                "fort": _stat_value("FORT"),
                "ref": _stat_value("REF"),
                "will": _stat_value("WILL")
            }
            footer = await initiative_service.maybe_join_from_check(
                ctx, name, results, modifier_value, source="player", stats=stats)
            embed.set_footer(
                text=footer or "No Initiative Tracker Set")
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def perform_check_roll(
        possible_check: pd.DataFrame,
        chosen: int,
        ap: ActionParam):
    if ap.is_adv and ap.is_dis:
        dice_expr = "1d20"
    elif ap.is_adv:
        dice_expr = "2d20kh1"
    elif ap.is_dis:
        dice_expr = "2d20kl1"
    else:
        dice_expr = "1d20"

    base_modifier = int(possible_check['value'].iloc[chosen])
    modifier = format_number(base_modifier)
    check_name = possible_check['field_name'].iloc[chosen]

    base_expr = f"{dice_expr}{modifier}{ap.d20_bonus}"
    if ap.is_halved:
        base_expr = halve_flat_modifiers(base_expr)

    results = [d20.roll(base_expr) for _ in range(ap.multiroll)]
    total_modifier = base_modifier + parse_bonus_to_int(ap.d20_bonus)
    return str(check_name), results, total_modifier


def create_check_result_embed(
        possible_check: pd.DataFrame,
        choosen: int,
        name: str,
        ap: ActionParam,
        level: int = 0
):
    embed = discord.Embed()
    results = []
    check_name, results, total_modifier = perform_check_roll(
        possible_check, choosen, ap)
    embed.title = f"{name} makes {check_name} check!"
    if len(results) <= 0:
        embed.description = "No such check found."
        return embed, check_name, results, total_modifier
    if len(results) == 1:
        embed.description = f"{results[0]}"
    else:
        for i in range(len(results)):
            embed.add_field(
                name=f"Check {i+1}",
                value=results[i],
                inline=True
        )
    if ap.thumbnail:
        embed.set_thumbnail(url=ap.thumbnail)
    if ap.level > 0:
        level = ap.level
    if level > 0:
        emoji = {
            "Easy": "🟢ᴇᴀꜱʏ",
            "Moderate": "🟡ᴍᴏᴅᴇʀᴀᴛᴇ",
            "Hard": "🔴ʜᴀʀᴅ",
        }
        dc = (
            " | ".join(f"{emoji[difficulty]} {value}"
                       for difficulty, value
                       in constant.LEVEL_SKILL_DC[level].items())
        )
        embed.set_footer(
            text=dc
        )
    return embed, check_name, results, total_modifier


async def handle_check(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context,
        name: str):
    ap = parse_command(command)
    rollable_check = df[df['is_rollable'] == 'TRUE']
    possible_check = rollable_check[rollable_check['field_name'].str.contains(
        ap.name, case=False
    )]
    ap.thumbnail = df[df['field_name'] == 'Thumbnail']['value'].iloc[0]
    level = df[df['field_name'] == 'Level']['value'].values
    if len(level) > 0:
        level = parse_value(level[0])
    else:
        level = 0
    if len(possible_check) <= 0:
        await ctx.send("No such check found.")
        return None
    elif len(possible_check) > 1:
        choosen = await get_user_choice(possible_check, 'field_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    embed, check_name, results, total_modifier = create_check_result_embed(
        possible_check, choosen, name, ap, level)
    return embed, check_name, results, total_modifier, ap


def parse_value(value) -> int:
    try:
        if type(value) is int:
            return value
        if type(value) is str:
            match = re.search(r'\d+', value)
            return int(match.group()) if match else 0
        else:
            int(value)
    except Exception:
        return 0


def parse_defense_value(value) -> int:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r'\d+', value)
        return int(match.group()) if match else None
    try:
        return int(value)
    except Exception:
        return None


def get_kept_d20_values(hit_result) -> list:
    try:
        text = str(hit_result)
        match = re.search(r"\(([^)]*)\)", text)
        if not match:
            return []
        inside = match.group(1)
        inside = inside.replace("**", "")
        dropped = set(int(x) for x in re.findall(r"~~(\d+)~~", inside))
        nums = [int(x) for x in re.findall(r"\d+", inside)]
        kept = [n for n in nums if n not in dropped]
        return kept
    except Exception:
        return []


def get_initiative_defense(
        ctx: commands.Context,
        target_name: str,
        def_target: str):
    if not initiative_service or not ctx:
        return None
    state = initiative_service.load_state(ctx)
    if not state.get("active"):
        return None
    name_key = initiative_service.normalize_name(target_name)
    combatant = state["combatants"].get(name_key)
    if not combatant:
        return None
    def_key = def_target.casefold()
    if "ac" in def_key:
        return parse_defense_value(combatant.get("ac"))
    if "fort" in def_key:
        return parse_defense_value(combatant.get("fort"))
    if "ref" in def_key:
        return parse_defense_value(combatant.get("ref"))
    if "will" in def_key:
        return parse_defense_value(combatant.get("will"))
    return None


def get_spreadsheet_id(url: str):
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


def get_all_sheets(spreadsheet_id: str) -> list:
    creds = None
    with open("credentials.json") as f:
        creds = json.load(f)
    gc = gspread.service_account_from_dict(creds)
    sheet = gc.open_by_key(spreadsheet_id)
    return sheet.worksheets()


def create_data_dict(df: pd.DataFrame) -> dict:
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
            if field_name:
                field_value = field_value + f"**{field_name}**: {value}\n"
            else:
                field_value = field_value + f"{value}\n"
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


def is_formatted_number(string: str):
    pattern = r'^[+-]\d+$'
    return bool(re.match(pattern, string))


def parse_bonus_to_int(value: str) -> int:
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0




def draw_quota(max_usages: int, usages: int) -> str:
    if max_usages >= 10:
        return f"{usages}/{max_usages}"
    used = max_usages - usages
    if usages <= 0:
        return max_usages * "〇"
    return usages * "◉" + used * "〇"


def halve_flat_modifiers(expression: str):
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


def add_border_template(url: str, template_path: str, name=""):
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
    datetime.time(hour=1, tzinfo=utc)
]


def get_calendar_name() -> str:
    start_date = datetime.datetime(2026, 1, 3, 1, 0, 0, tzinfo=utc)
    now = datetime.datetime.now(utc)
    if now < start_date:
        now = start_date - datetime.timedelta(days=1)
    delta = now - start_date
    total_sessions = 1 + int(delta.total_seconds() // (60 * 60 * 24))
    date = get_in_game_date(total_sessions)
    chapter_number = max(total_sessions - 1, 0) // 7 + 1
    session_number = f"{total_sessions:02}"
    calendar_name = f"{chapter_number}.{session_number} - {date}"
    return calendar_name


async def update_calendar():
    channel_calendar = bot.get_channel(1446506930976723095)
    channel_name = f"📅 {get_calendar_name()}"
    print(channel_name)
    try:
        await channel_calendar.edit(name=channel_name)
    except Exception as e:
        print(e, traceback.format_exc())


async def update_ds(guild_id: int):
    try:
        data = downtimeRepo.get_gacha(guild_id=guild_id)
        if data is None:
            print("No downtime sheet found")
            return
        url = data[4]
        if url == "":
            print("No downtime sheet found")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            print("No downtime sheet found")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            print("No downtime sheet found")
            return
        df_dict = {}
        for sheet in sheets:
            if sheet.title not in ['start', 'downtime']:
                continue
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "start":
                temp_df = temp_df.sort_values(by="maxDice", ascending=True)
                start = temp_df.to_dict()
                continue
            if sheet.title == "downtime":
                temp_df = temp_df.applymap(
                    lambda x: x.strip() if isinstance(x, str) else x)
                temp_df['char'] = temp_df['char'].replace('', pd.NA)
                temp_df = temp_df.dropna(subset=['char'])
            df_dict[sheet.title] = temp_df.to_dict()
        downtimeRepo.set_gacha(
            guild_id=guild_id,
            start=json.dumps(start),
            items=json.dumps(df_dict),
            sheet_url=url
        )
        print("Downtime sheet is updated.")
    except Exception as e:
        print(e, traceback.format_exc())
    return


@tasks.loop(time=times)
async def daily_task_run():
    await update_calendar()
    bot_dump_channel = bot.get_channel(1443893527636348958)
    try:
        await update_ds(1443823337980563507)
    except Exception:
        await bot_dump_channel.send(
            "Error updating downtime. Please check the downtime sheet."
        )
    await bot_dump_channel.send(
        "Done updating calendar and downtime.")


def get_in_game_date(week_number):
    months = [
        "Uno", "Tweyen", "Threo", "Quatro",
        "Fif", "Seox", "Siete", "Eachta",
        "Niyon", "Tien"
    ]

    season_emojis = {
        "Fif": "☀️", "Seox": "☀️",
        "Siete": "🍂", "Echta": "🍂", "Niyon": "🍂",
        "Tien": "❄️", "Uno": "❄️", "Tweyen": "❄️",
        "Threo": "🌸", "Quatro": "🌸"
    }

    month_index = (week_number - 1) // 4 % 10
    week_label = f"Week {((week_number - 1) % 4) + 1}"
    month = months[month_index]
    emoji = season_emojis.get(month, "")
    return f"{week_label} {month} {emoji}"


def two_digit(number: int):
    if number < 10:
        return f"0{number}"
    return str(number)


def main():
    # uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
    bot.run(TOKEN)
    pass


def _looks_like_echo(ctx: commands.Context, m: discord.Message) -> bool:
    content = m.content.strip()
    starts_like_cmd = content.startswith(
        f"{ctx.prefix}{ctx.command.qualified_name}"
    )
    is_proxyish = (m.author.bot) or (m.webhook_id is not None)
    return m.channel.id == ctx.channel.id and starts_like_cmd and is_proxyish


async def _cleanup_proxy_echo(bot: commands.Bot, ctx: commands.Context):
    await asyncio.sleep(0.02)
    try:
        echo = await bot.wait_for(
            "message",
            timeout=1,
            check=lambda m: _looks_like_echo(ctx, m))
        try:
            await echo.delete()
        except discord.Forbidden:
            pass
    except asyncio.TimeoutError:
        pass


@bot.command()
async def gacha(ctx: commands.Context):
    try:
        asyncio.create_task(_cleanup_proxy_echo(bot, ctx))
        try:
            await ctx.message.delete()
        except Exception:
            pass

        data = gachaRepo.get_gacha(ctx.guild.id)
        if data is None:
            await ctx.send("No gacha sheet is found.")
            return
        start = json.loads(data[2])
        df_dict = json.loads(data[3])
        url = data[4]
        spreadsheet_id = get_spreadsheet_id(url)
        sheet = get_sheet_to_roll(start)
        if sheet == "":
            await ctx.send("No sheet found.")
            return
        sheet_dict = df_dict[sheet]
        result = get_random_from_sheet(sheet_dict)
        sheet_df = pd.DataFrame(start)
        image = None
        try:
            image = sheet_df.loc[sheet_df['sheet'] == sheet, 'image'].values[0]
        except Exception as e:
            print(e)
        embed = discord.Embed()
        embed.title = "Gacha Result"
        embed.description = f"{result}"
        avatar_url = ""
        if ctx.author.avatar:
            avatar_url = ctx.author.avatar.url
        embed.set_image(url=image)
        embed.set_author(name=ctx.author.name, icon_url=avatar_url)
        # TODO: Hardcoded for now
        if ctx.guild.id == 1396768475850211339:
            current_channel = ctx.channel
            channel_gacha = ctx.guild.get_channel(1409570843490783397)
            content = f"{ctx.author.mention} in {current_channel.mention}"
            await channel_gacha.send(content=content, embed=embed)
        else:
            await ctx.send(embed=embed)
        try:
            create_gacha_log_df(
                spreadsheet_id,
                ctx.channel.id,
                ctx.channel.name,
                ctx.author.id,
                ctx.author.name,
                result
            )
        except Exception as e:
            print(e)
            return
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def get_sheet_to_roll(start: dict) -> str:
    thresholds = list(start['maxDice'].values())
    results = list(start['sheet'].values())
    max_value = max(thresholds)
    roll = random.randint(1, max_value)
    for i in range(len(thresholds)):
        if roll <= thresholds[i]:
            return results[i]
    return ""


def get_random_from_sheet(sheet_dict: dict, column_name: str = "value") -> str:
    random_value = random.choice(list(sheet_dict[column_name].values()))
    return random_value


@bot.command(aliases=["gs"])
async def gacha_sheet(ctx: commands.Context, url: str = ""):
    try:
        await ctx.message.delete()
        if url == "":
            await ctx.send("Please provide a url")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            await ctx.send("No sheets found")
            return
        df_dict = {}
        for sheet in sheets:
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "log":
                continue
            if sheet.title == "start":
                temp_df = temp_df.sort_values(by="maxDice", ascending=True)
                start = temp_df.to_dict()
                print(start)
                continue
            df_dict[sheet.title] = temp_df.to_dict()
        gachaRepo.set_gacha(
            guild_id=ctx.guild.id,
            start=json.dumps(start),
            items=json.dumps(df_dict),
            sheet_url=url
        )
        chances = calculate_gacha_chance(start)
        embed = discord.Embed()
        embed.title = "Gacha"
        embed.description = "Chances of getting each sheet are:"
        for sheet, chance in chances:
            embed.add_field(name=sheet, value=f"{chance} %", inline=False)
        await ctx.send(
                content=f"New Gacha [Spreadsheet]({url}) is added.",
                embed=embed
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")
    return


@bot.command(aliases=["ds"])
async def downtime_sheet(ctx: commands.Context, url: str = ""):
    try:
        await ctx.message.delete()
        if url == "":
            await ctx.send("Please provide a url")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            await ctx.send("No sheets found")
            return
        df_dict = {}
        for sheet in sheets:
            if sheet.title not in ['start', 'downtime']:
                continue
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "start":
                temp_df = temp_df.sort_values(by="maxDice", ascending=True)
                start = temp_df.to_dict()
                print(start)
                continue
            if sheet.title == "downtime":
                temp_df = temp_df.applymap(
                    lambda x: x.strip() if isinstance(x, str) else x)
                temp_df['char'] = temp_df['char'].replace('', pd.NA)
                temp_df = temp_df.dropna(subset=['char'])
            df_dict[sheet.title] = temp_df.to_dict()
        downtimeRepo.set_gacha(
            guild_id=ctx.guild.id,
            start=json.dumps(start),
            items=json.dumps(df_dict),
            sheet_url=url
        )
        embed = discord.Embed()
        embed.title = "Downtime Gacha"
        embed.description = ". . ."
        await ctx.send(
                content=f"New Gacha [Spreadsheet]({url}) is added.",
                embed=embed
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")
    return


@bot.command(aliases=["dt"])
async def downtime(ctx: commands.Context, *, args=None):
    try:
        try:
            await ctx.message.delete()
        except Exception:
            pass
        data = downtimeRepo.get_gacha(ctx.guild.id)
        if data is None:
            await ctx.send("No downtime sheet is found.")
            return
        start = json.loads(data[2])
        df_dict = json.loads(data[3])
        url = data[4]
        spreadsheet_id = get_spreadsheet_id(url)
        sheet = get_sheet_to_roll(start)
        if sheet == "":
            await ctx.send("No sheet found.")
            return
        if sheet == "none":
            await none_meet(ctx)
            return
        filter_by_user_id: str = None
        filter_by_location: str = None

        sheet_dict = df_dict[sheet]
        sheet_df = pd.DataFrame(sheet_dict)

        # remove the userID of the person who called the command
        if 'userID' in sheet_df.columns:
            sheet_df = sheet_df[sheet_df['userID'] != f"<@{ctx.author.id}>"]

        if args is None:
            await multi_downtime(
                ctx,
                sheet_df,
                url,
                spreadsheet_id
            )
            return
        else:
            if re.search(r'<@\d+>', args):
                filter_by_user_id = args
            else:
                filter_by_location = args

        if filter_by_user_id is not None:
            sheet_df = sheet_df[sheet_df['userID'].str.contains(
                filter_by_user_id, case=False
            )]
        if filter_by_location is not None:
            sheet_df = sheet_df[
                sheet_df['where'].isna() |
                (sheet_df['where'] == '') |
                sheet_df['where'].str.contains(
                    filter_by_location, case=False, na=False)
            ]
            unique_location = sheet_df['where'].unique().tolist()
            if len(unique_location) <= 1 and unique_location[0] == "":
                await none_meet(ctx, filter_by_location)
                return
            filter_by_location = unique_location[0]
        image = None
        character = "no one"
        location = "nowhere in particular"
        event = "No event described."
        user_id = None
        if sheet_df.empty:
            await none_meet(ctx)
            return
        try:
            random_row = sheet_df.sample(n=1).iloc[0]
            character = random_row['char']
            if random_row['where']:
                location = random_row['where']
            else:
                location = filter_by_location
            if random_row['event']:
                event = random_row['event']
            if random_row['image/gif embed']:
                image = random_row['image/gif embed']
            if random_row['userID']:
                user_id = random_row['userID']
        except Exception as e:
            print("error: ", e)
        embed = discord.Embed()
        embed.title = f"You meet with {character} at {location}!"
        if filter_by_user_id is not None:
            event = (
                f"*Fancy seeing you here… or was "
                f"this part of someone’s master plan?* 😏🕵️‍♀️\n\n{event}"
            )
        if filter_by_location is not None:
            event = (
                f"*Going to {location}, eh? "
                f"👀📍*\n\n{event}"
            )
        embed.description = (
            f"{event}\n\n"
            f"-# [*Want to add events of your character? Click this.*]({url})"
        )
        avatar_url = ""
        if ctx.author.avatar:
            avatar_url = ctx.author.avatar.url
        embed.set_image(url=image)
        embed.set_author(name=ctx.author.name, icon_url=avatar_url)
        embed.set_footer(
            text=f"DT {get_calendar_name()}"
        )
        await ctx.send(content=user_id, embed=embed)
        try:
            create_gacha_log_df(
                spreadsheet_id,
                ctx.channel.id,
                ctx.channel.name,
                ctx.author.id,
                ctx.author.name,
                character,
                event
            )
        except Exception as e:
            print(e)
            return
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


async def multi_downtime(
        ctx: commands.Context,
        sheet_df: pd.DataFrame,
        url: str,
        spreadsheet_id
):
    try:

        # pick 3 random rows
        try:
            choices_df = sheet_df.sample(n=min(2, len(sheet_df)))
        except Exception as e:
            print("error: ", e)
            await none_meet(ctx)
            return

        # build temporary embeds for preview
        embeds = []
        choice_embed = discord.Embed(
            title="Your Downtime Choices",
            description="Choose one of the following options:"
        )
        for i, (idx, row) in enumerate(choices_df.iterrows(), start=1):
            char = (row.get('char') or 'no one')
            location = (row.get('where') or 'nowhere in particular')
            event = (row.get('event') or 'No event described.')
            image = row.get('image/gif embed')

            embed = discord.Embed(title=f"You meet with {char} at {location}!")
            embed.description = (
                f"{event}\n\n"
                f"-# [*Want to add events of your character? Click this.*]"
                f"({url})"
            )
            choice_embed.add_field(
                name=f"{i}️⃣: Meet {char} at {location}",
                value=event,
                inline=False
            )
            if isinstance(image, str) and image.strip():
                embed.set_image(url=image)

            embeds.append((embed, {"index": idx, **row.to_dict()}))

        # add a none option
        choice_embed.add_field(
            name="🚫: Meet No One",
            value=(
                "Fate has decided that this time you continue your life "
                "without encountering anyone else."
            ),
            inline=False
        )

        class ChoiceView(View):
            def __init__(self, embeds, rows):
                super().__init__(timeout=None)
                self.result = None
                self.rows = rows
                # "3️⃣"
                emojis = ["1️⃣", "2️⃣"]
                for idx in range(len(embeds)):
                    btn = Button(
                        label="",
                        style=discord.ButtonStyle.primary,
                        emoji=emojis[idx],
                        custom_id=str(idx)
                    )
                    btn.callback = self.make_callback(idx)
                    self.add_item(btn)

                none_btn = Button(
                    label="None",
                    style=discord.ButtonStyle.danger,
                    emoji="🚫",
                    custom_id="none"
                )
                none_btn.callback = self.make_callback("none")
                self.add_item(none_btn)

            def make_callback(self, choice):
                async def callback(interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        await interaction.response.send_message(
                            "You can't choose for someone else!",
                            ephemeral=True
                        )
                        return
                    self.result = choice
                    await interaction.response.defer()
                    self.stop()
                return callback

            async def on_timeout(self):
                if self.message:
                    await self.message.edit(
                        content="⏳ Selection timed out.", view=None
                    )

        view = ChoiceView([e for e, _ in embeds], [r for _, r in embeds])
        preview_msg = await ctx.send(
            content=f"{ctx.author.mention} Choose your downtime:",
            embed=choice_embed, view=view
        )
        view.message = preview_msg

        await view.wait()

        # after choice
        if view.result is None:
            return

        if view.result == "none":
            avatar_url = ctx.author.avatar.url if ctx.author.avatar else ""
            none_embed = discord.Embed(
                    title="You meet no one.",
                    description=(
                        "Fate has decided that this time you continue your "
                        "life without encountering anyone else."
                    )
                )
            none_embed.set_author(name=ctx.author.name, icon_url=avatar_url)
            await preview_msg.edit(
                content="You chose to meet no one.",
                embed=none_embed,
                view=None
            )
            return

        try:
            idx = int(view.result)
            chosen_embed, chosen_row = embeds[idx]
            user_id = (chosen_row.get('userID') or None)

            avatar_url = ctx.author.avatar.url if ctx.author.avatar else ""
            chosen_embed.set_author(name=ctx.author.name, icon_url=avatar_url)
            chosen_embed.set_footer(text=f"DT {get_calendar_name()}")

            await preview_msg.delete()
            await ctx.send(
                content=user_id,
                embeds=[chosen_embed],
                view=None
            )

            try:
                create_gacha_log_df(
                    spreadsheet_id,
                    ctx.channel.id,
                    ctx.channel.name,
                    ctx.author.id,
                    ctx.author.name,
                    getattr(chosen_row, 'char', 'no one'),
                    getattr(chosen_row, 'event', 'No event described.')
                )
            except Exception as e:
                print(e)
        except Exception as e:
            print(e)

    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


async def none_meet(ctx: commands.Context, location: str = ""):
    embed = discord.Embed()
    avatar_url = ""
    if ctx.author.avatar:
        avatar_url = ctx.author.avatar.url
    embed.set_author(name=ctx.author.name, icon_url=avatar_url)
    embed.title = "You meet no one."
    if location:
        embed.description = (
            f"*You are looking for someone at {location}…* "
            f"but no one is there.\n\n"
            f"*Maybe, try another place or people?*"
        )
    else:
        embed.description = (
            "Better luck next time.\n\nMaybe, try another place or people?"
        )
    await ctx.send(embed=embed)


def calculate_gacha_chance(data: dict):
    chances = []
    thresholds = list(data["maxDice"].values())
    sheets = list(data['sheet'].values())
    chances = []
    max_value = max(thresholds)
    for i in range(len(thresholds)):
        if i == 0:
            chance = thresholds[0]
        else:
            chance = thresholds[i] - thresholds[i - 1]
        percentage = (chance / max_value) * 100
        chances.append((sheets[i], round(percentage, 2)))

    return chances


def log_result_to_sheet(spreadsheet_id: str, df: pd.DataFrame):
    creds = None
    with open("credentials.json") as f:
        creds = json.load(f)
    gc = gspread.service_account_from_dict(creds)
    sheet = gc.open_by_key(spreadsheet_id)

    try:
        worksheet = sheet.worksheet("log")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title="log", rows="100", cols="10")
        worksheet.append_rows([df.columns.values.tolist()])
    worksheet.append_rows(df.values.tolist())

    return


def create_gacha_log_df(
            spreadsheet_id: str,
            channel_id: int,
            channel_name: str,
            user_id: int,
            user_name: str,
            result: str,
            details: str = None
        ) -> bool:
    try:
        data = {
            "timestamp":
                [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            "channel_id": [str(channel_id)],
            "channel_name": [channel_name],
            "user_id": [str(user_id)],
            "user_name": [user_name],
            "result": [result]
        }
        if details:
            data["details"] = [details]
        log_df = pd.DataFrame(data=data)
        log_result_to_sheet(spreadsheet_id, log_df)
        return True
    except Exception as e:
        print(e, traceback.format_exc())
        return False


@bot.command(aliases=["budget"])
async def budget_calc(ctx: commands.Context, party_level: int, chara: int):
    await ctx.message.delete()
    embed = discord.Embed()
    embed.title = "XP Calculation"
    embed.url = "https://iws.mx/dnd/?view=glossary672"
    embed.description = (
        f"**Party Level**: {party_level}\n"
        f"**Character Count**: {chara}\n"
        "\n"
    )
    # easy_budget_floor = get_budget(avg_level-2, chara)
    easy_budget_ceil = get_budget(party_level-1, chara)
    # normal_budget_floor = get_budget(avg_level, chara)
    normal_budget_ceil = get_budget(party_level+1, chara)
    # hard_budget_floor = get_budget(avg_level+2, chara)
    hard_budget_ceil = get_budget(party_level+4, chara)
    embed.description += (
        f"**Easy**: {easy_budget_ceil}\n"
        f"**Normal**: {normal_budget_ceil}\n"
        f"**Hard**: {hard_budget_ceil}\n"
    )
    embed.set_footer(
        text="Rules Compendium, page(s) 285."
    )
    await ctx.send(embed=embed)


@bot.command(aliases=["generate", "gen"])
async def generate_random_encounter(
        ctx: commands.Context,
        private: str = "false",):
    is_private = private == "true"

    async def generate_callback(
            party_level: int = 1,
            chara: int = 5,
            difficulty: str = "normal",
            role: list = None,
            interaction: discord.Interaction = None):
        channel = interaction.channel
        user = interaction.user
        keywords = []
        max_budget = {}
        min_budget = {}
        floor = {}
        ceil = {}
        floor["easy"] = party_level - 2
        ceil["easy"] = party_level - 1
        min_budget["easy"] = get_budget(floor["easy"], chara)
        max_budget["easy"] = get_budget(ceil["easy"], chara)
        floor["normal"] = party_level
        ceil["normal"] = party_level + 1
        min_budget["normal"] = get_budget(floor["normal"], chara)
        max_budget["normal"] = get_budget(ceil["normal"], chara)
        floor["hard"] = party_level + 2
        ceil["hard"] = party_level + 4
        min_budget["hard"] = get_budget(floor["hard"], chara)
        max_budget["hard"] = get_budget(ceil["hard"], chara)
        floor["custom"] = party_level
        ceil["custom"] = party_level
        if difficulty == "custom":
            budget_embed = discord.Embed()
            budget_embed.title = "XP Budget for Reference"
            budget_embed.description = (
                f"**Easy**: {max_budget['easy']}\n"
                f"**Normal**: {max_budget['normal']}\n"
                f"**Hard**: {max_budget['hard']}\n"
            )
            message = await channel.send(
                content=(
                    f"Please input XP budget value. <@{user.id}>\n"
                    f"If you have any keyword you want to use, please "
                    f"add it together after a space.\nYou can add few, "
                    f"separated by space.\n"
                    f"e.g. `10000 prone slide`"
                ),
                embed=budget_embed
            )
            try:
                reply = await bot.wait_for(
                    "message",
                    timeout=60.0,
                    check=lambda m: m.author == interaction.user
                )
                custom_budget = reply.content.split()[0]
                if len(reply.content.split()) > 1:
                    keywords = reply.content.split()[1:]
                if custom_budget.isnumeric():
                    max_budget["custom"] = int(custom_budget)
                    min_budget["custom"] = 0.9 * int(custom_budget)
                else:
                    await channel.send("Invalid input.")
                    await reply.delete()
                    await message.delete()
                    return
                try:
                    await reply.delete()
                    await message.delete()
                except Exception as e:
                    print(e, traceback.format_exc())
            except asyncio.TimeoutError:
                await message.delete()
                await channel.send("Time Out")
                return
        floor[difficulty] = max(floor[difficulty]-3, 1)
        ceil[difficulty] = min(ceil[difficulty]+3, 32)
        levels = list(range(floor[difficulty], ceil[difficulty]+1))
        monster_list = monsterRepo.get_monsters_by_levels_and_roles(
            levels=levels,
            roles=role
        )
        if monster_list is None:
            await channel.send("No monsters found.")
            return None
        encounter, total_xp = generate_encounter(
            min_xp=min_budget[difficulty],
            max_xp=max_budget[difficulty],
            monster_list=monster_list,
            keywords=keywords
            )
        embed = discord.Embed()
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        embed.title = "Encounter Generation"
        embed.description = (
            f"**Party Level**: {party_level}\n"
            f"**Character Count**: {chara}\n"
            "\n"
        )
        for monster_id, (monster_data, count) in encounter.items():
            monster_name = monster_data[1]
            monster_level = monster_data[2]
            monster_xp = monster_data[-1]
            monster_group = monster_data[4]
            monster_role = monster_data[3]
            url = f"https://iws.mx/dnd/?view={monster_data[0]}"
            embed.description += (
                f"**{count}x "
                f"[{monster_name}]({url})**:  "
                f"L{monster_level} {monster_group} "
                f"{monster_role} ({monster_xp} XP)\n"
            )
        embed.description += (
            f"\n**Total XP**: {total_xp}\n"
            f"**Budget**: {max_budget[difficulty]}\n"
        )
        if is_private:
            await interaction.user.send(embed=embed)
            return
        await channel.send(embed=embed)

    view = generator.SelectionView(ctx.author, generate_callback)
    await ctx.send(
        content=f"<@{ctx.author.id}> Select an option below to continue:",
        view=view
    )
    return


def generate_encounter(min_xp, max_xp, monster_list, keywords=[]):
    encounter = {}  # key: monster_id, value: (monster_data, count)
    total_xp = 0

    while total_xp < min_xp:
        # Filter for monsters that can fit within remaining XP
        possible_monsters = [m for m in monster_list if m[-1] > 0 and
                             total_xp + m[-1] <= max_xp]
        if not possible_monsters:
            break  # No valid monsters to add

        chosen_monster = random.choice(possible_monsters)
        monster_id = chosen_monster[0]
        monster_xp = chosen_monster[-1]
        description = chosen_monster[8]

        if keywords:
            if not any(keyword.lower() in description.lower()
                       for keyword in keywords):
                if random.random() < 0.60:
                    possible_monsters.remove(chosen_monster)
                    continue

        max_count = (max_xp - total_xp) // monster_xp
        if max_count == 0:
            continue  # Can't add even one of this monster

        monster_group = chosen_monster[4]
        if monster_group.lower() == "solo":
            max_count = min(max_count, 1)
            possible_monsters.remove(chosen_monster)
        else:
            max_count = min(max_count, 16)
        count = random.randint(1, max_count)

        if monster_id in encounter:
            encounter[monster_id] = (chosen_monster, encounter[monster_id][1]
                                     + count)
        else:
            encounter[monster_id] = (chosen_monster, count)

        total_xp += monster_xp * count

    return encounter, total_xp


def get_budget(avg_level: int, chara: int) -> int:
    if avg_level < 0 or avg_level >= len(constant.XP_LEVEL_LIST):
        return 0
    return constant.XP_LEVEL_LIST[avg_level] * chara


@bot.tree.command(name="generate", description="Random Encounter Generator")
async def random_generator_ui(
        interaction: discord.Interaction,
        private: bool = False
        ):
    async def generate_callback(
            party_level: int = 1,
            chara: int = 5,
            difficulty: str = "normal",
            role: list = None,
            interaction: discord.Interaction = None):
        channel = interaction.channel
        user = interaction.user
        keywords = []
        max_budget = {}
        min_budget = {}
        floor = {}
        ceil = {}
        floor["easy"] = party_level - 2
        ceil["easy"] = party_level - 1
        min_budget["easy"] = get_budget(floor["easy"], chara)
        max_budget["easy"] = get_budget(ceil["easy"], chara)
        floor["normal"] = party_level
        ceil["normal"] = party_level + 1
        min_budget["normal"] = get_budget(floor["normal"], chara)
        max_budget["normal"] = get_budget(ceil["normal"], chara)
        floor["hard"] = party_level + 2
        ceil["hard"] = party_level + 4
        min_budget["hard"] = get_budget(floor["hard"], chara)
        max_budget["hard"] = get_budget(ceil["hard"], chara)
        floor["custom"] = party_level
        ceil["custom"] = party_level
        if difficulty == "custom":
            budget_embed = discord.Embed()
            budget_embed.title = "XP Budget for Reference"
            budget_embed.description = (
                f"**Easy**: {max_budget['easy']}\n"
                f"**Normal**: {max_budget['normal']}\n"
                f"**Hard**: {max_budget['hard']}\n"
            )
            message = await channel.send(
                content=(
                    f"Please input XP budget value. <@{user.id}>\n"
                    f"If you have any keyword you want to use, please "
                    f"add it together after a space.\nYou can add few, "
                    f"separated by space.\n"
                    f"e.g. `10000 prone slide`"
                ),
                embed=budget_embed
            )
            try:
                reply = await bot.wait_for(
                    "message",
                    timeout=60.0,
                    check=lambda m: m.author == interaction.user
                )
                custom_budget = reply.content.split()[0]
                if len(reply.content.split()) > 1:
                    keywords = reply.content.split()[1:]
                if custom_budget.isnumeric():
                    max_budget["custom"] = int(custom_budget)
                    min_budget["custom"] = 0.9 * int(custom_budget)
                else:
                    await channel.send("Invalid input.")
                    await reply.delete()
                    await message.delete()
                    return
                try:
                    await reply.delete()
                    await message.delete()
                except Exception as e:
                    print(e, traceback.format_exc())
            except asyncio.TimeoutError:
                await message.delete()
                await channel.send("Time Out")
                return
        floor[difficulty] = max(floor[difficulty]-3, 1)
        ceil[difficulty] = min(ceil[difficulty]+3, 32)
        levels = list(range(floor[difficulty], ceil[difficulty]+1))
        monster_list = monsterRepo.get_monsters_by_levels_and_roles(
            levels=levels,
            roles=role
        )
        if monster_list is None:
            await channel.send("No monsters found.")
            return None
        encounter, total_xp = generate_encounter(
            min_xp=min_budget[difficulty],
            max_xp=max_budget[difficulty],
            monster_list=monster_list,
            keywords=keywords
            )
        embed = discord.Embed()
        embed.set_author(
            name=interaction.user.display_name,
            icon_url=interaction.user.display_avatar.url
        )
        embed.title = "Encounter Generation"
        embed.description = (
            f"**Party Level**: {party_level}\n"
            f"**Character Count**: {chara}\n"
            "\n"
        )
        for monster_id, (monster_data, count) in encounter.items():
            monster_name = monster_data[1]
            monster_level = monster_data[2]
            monster_xp = monster_data[-1]
            monster_group = monster_data[4]
            monster_role = monster_data[3]
            url = f"https://iws.mx/dnd/?view={monster_data[0]}"
            embed.description += (
                f"**{count}x "
                f"[{monster_name}]({url})**:  "
                f"L{monster_level} {monster_group} "
                f"{monster_role} ({monster_xp} XP)\n"
            )
        embed.description += (
            f"\n**Total XP**: {total_xp}\n"
            f"**Budget**: {max_budget[difficulty]}\n"
        )
        if private:
            await interaction.user.send(embed=embed)
            return
        await channel.send(embed=embed)

    view = generator.SelectionView(interaction.user, generate_callback)
    await interaction.response.send_message(
        content="Select an option below to continue:",
        view=view,
        ephemeral=True
    )


@bot.command(aliases=["madd"])
async def add_monster_sheet(ctx: commands.Context, url=""):
    try:
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")

        # clean empty cells
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0, )
        actions_data['Usages'] = actions_data['Usages'].replace('', 0, )
        actions_data = actions_data.replace('#REF!', None, )
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        name = "Monsters"
        monsterMapRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            actions_data.to_json(),
            sheet_url=url
            )
        await ctx.send(f"Sheet `{name}` is added.")
    except PermissionError:
        await ctx.send("Error. Please check your sheet permission.")
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["mupdate"])
async def monster_update_sheet(ctx: commands.Context, url=""):
    try:
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        old_actions_data = pd.read_json(io.StringIO(character[3]))
        url = character[4]
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        df_data = get_df(spreadsheet_id, "data")
        actions_data = get_df(spreadsheet_id, "actions")

        # clean empty cells
        actions_data = actions_data.applymap(
            lambda x: x.strip() if isinstance(x, str) else x)
        actions_data['MaxUsages'] = actions_data['MaxUsages'].replace('', 0)
        actions_data['Usages'] = actions_data['Usages'].replace('', 0)
        actions_data = actions_data.replace('#REF!', None)
        actions_data = actions_data[
            actions_data['Name'].str.strip().astype(bool)
        ]
        actions_data = actions_data.dropna()
        df_data = df_data.replace('#REF!', None)
        df_data = df_data.dropna()

        old_actions_data['Usages_numeric'] = pd.to_numeric(
            old_actions_data['Usages'], errors='coerce').fillna(0)
        madf = pd.merge(
            actions_data,
            old_actions_data[['Name', 'Usages_numeric']],
            on='Name',
            how='left'
        )
        madf['Usages'] = madf['Usages_numeric'].combine_first(
            madf['Usages']
        )
        madf = madf.drop(columns=['Usages_numeric'])

        name = "Monsters"
        monsterMapRepo.set_character(
            ctx.guild.id,
            ctx.author.id,
            name,
            df_data.to_json(),
            madf.to_json(),
            sheet_url=url)
        await ctx.send(f"Sheet `{name}` is updated.")
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["msheet"])
async def monster_sheet(ctx: commands.Context, *, args: str = ""):
    character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(io.StringIO(character[2]))
    df_actions = pd.read_json(io.StringIO(character[3]))
    possible_monster = df_data[df_data['monster_name'].str.contains(
        args,
        na=False,
        case=False
        )].drop_duplicates(subset='monster_name')
    if len(possible_monster) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_monster) > 1:
        choosen = await get_user_choice(possible_monster, 'monster_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    monster_name = possible_monster['monster_name'].iloc[choosen]
    monster = df_data[df_data['monster_name'] == monster_name]
    monster_action = df_actions[df_actions['MonsterName'] == monster_name]

    data_dict = create_data_dict(monster)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)
    await monster_action_list(ctx, monster_action, monster_name)


async def monster_action_list(
        ctx: commands.Context,
        actions: pd.DataFrame,
        monster_name: str
):
    if actions.empty:
        await ctx.send("No actions found for this monster.")
        return None
    embeds = create_action_list_embed(monster_name, actions)
    view = Paginator(ctx.author, embeds)
    if len(embeds) <= 1:
        view = None
    await ctx.send(embed=embeds[0], view=view)


@bot.command(aliases=["mreset"])
async def monster_reset(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            actions['Usages'] = actions['MaxUsages']
            message = "All actions are reset."
        else:
            max_usages = actions['MaxUsages']
            actions.loc[actions['ResetOn'] == args, 'Usages'] = max_usages
            message = f"`{args}` actions are reset."
        monsterMapRepo.update_character(character[0], None, actions.to_json())
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


@bot.command(aliases=["ma"])
async def monster_action(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        data = pd.read_json(io.StringIO(character[2]))
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            await ctx.send(
                "Please specify action to roll.\n"
                "Use ;;msheet to see available actions.")
            return
        args = translate_cvar(args, data)
        ap = parse_command(args)
        if ap.targets:
            for target in ap.targets:
                if not target.name or target.name in ("Meta",) or target.name.startswith("Attack "):
                    continue
                resolved = await resolve_initiative_target(ctx, target.name)
                if resolved is None:
                    return
                target.name = resolved
        embed = await handle_action_monster(args, actions, ctx, data, sheet_id, ap=ap)
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again. " + str(e))


async def handle_action_monster(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context,
        data: pd.DataFrame,
        sheet_id: str,
        ap: ActionParam = None):
    if ap is None:
        ap = parse_command(command)
    df['ActionName'] = df['MonsterName'] + ": " + df['Name']
    possible_action = df[df['Name'].str.contains(
        ap.name,
        na=False,
        case=False
        )]
    if len(possible_action) <= 0:
        await ctx.send("No actions found")
        return None
    elif len(possible_action) > 1:
        choosen = await get_user_choice(possible_action, 'ActionName', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    name = possible_action['MonsterName'].iloc[choosen]
    embed = create_action_result_embed(possible_action, choosen, name, ap, ctx)
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
        charaRepo.update_character(sheet_id, None, df.to_json())
    return embed


@bot.command(aliases=["mc"])
async def monster_check(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        if args is None:
            await ctx.send("Please specify check to roll.")
            return
        character = monsterMapRepo.get_character(ctx.guild.id, ctx.author.id)
        data = pd.read_json(io.StringIO(character[2]))
        result = await handle_check_monster(args, data, ctx)
        if result is None:
            return
        embed, check_name, results, modifier_value, ap, monster_name = result
        if check_name.casefold() == "initiative":
            ap.is_init = True
        if ap.is_init and initiative_service:
            def _stat_value(key: str):
                value = initiative_service.find_field_value(data, key)
                if value is None or pd.isna(value):
                    return "?"
                return value
            stats = {
                "ac": _stat_value("AC"),
                "fort": _stat_value("FORT"),
                "ref": _stat_value("REF"),
                "will": _stat_value("WILL")
            }
            base_name = ap.name_override or monster_name
            footer = await initiative_service.maybe_join_from_check(
                ctx,
                base_name,
                results,
                modifier_value,
                source="monster",
                stats=stats,
                multi_name=True
            )
            embed.set_footer(
                text=footer or "No Initiative Tracker Set")
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command(aliases=["cbload"])
async def cb_generate(ctx: commands.Context):
    attachment = (
        ctx.message.attachments[0] if ctx.message.attachments else None
    )
    if attachment is None:
        await ctx.send("Please provide a file.")
        return
    file = await attachment.read()
    try:
        await ctx.message.delete()
        async with ctx.typing():
            character = await read_character_file(file)
            if character is None:
                await ctx.send("Invalid character file.")
                return
            buffer = await character_to_excel(character)
            buffer.seek(0)
            await ctx.send(
                content=(
                    f"`{character.characterName}` sheet is generated."
                ),
                file=discord.File(buffer, filename="character.xlsx")
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error loading cbloader save file.")


async def handle_check_monster(
        command: str,
        df: pd.DataFrame,
        ctx: commands.Context):
    ap = parse_command(command)
    rollable_check = df[df['is_rollable'] == 'TRUE'].copy()
    rollable_check.loc[:, 'monster_field_name'] = (
        rollable_check['monster_name'] + ": " + rollable_check['field_name']
    )
    possible_check = rollable_check[
        rollable_check['monster_field_name'].str.contains(
            ap.name, case=False
        )
    ]
    # ap.thumbnail = df[df['field_name'] == 'Thumbnail']['value'].iloc[0]
    if len(possible_check) <= 0:
        await ctx.send("No such check found.")
        return None
    elif len(possible_check) > 1:
        choosen = await get_user_choice(
            possible_check, 'monster_field_name', ctx)
        if choosen is None:
            return None
    else:
        choosen = 0
    name = possible_check['monster_name'].iloc[choosen]
    embed, check_name, results, total_modifier = create_check_result_embed(
        possible_check, choosen, name, ap)
    return embed, check_name, results, total_modifier, ap, name


@bot.command(name="beta")
async def beta(ctx: commands.Context, opponent: discord.Member):
    if not opponent:
        await ctx.send("Please mention an opponent.")
        return
    await ctx.message.delete()
    if opponent.bot or ctx.author == opponent:
        raise commands.BadArgument(
            "You cannot play against a bot or yourself."
        )

    data = betaEventMapRepo.get_gacha(ctx.guild.id)
    df_dict = json.loads(data[2])
    sheet_df = pd.DataFrame(df_dict)
    random_row = sheet_df.sample(n=min(2, len(sheet_df)))
    event1 = random_row.iloc[0]['Event']
    event2 = random_row.iloc[1]['Event']

    description = f"🅰️ {event1}\n\n🅱️ {event2}"
    description += "\n\n"
    description += f"{ctx.author.mention}: ❓ vs {opponent.mention}: ❓"
    embed = discord.Embed(
        title="Shared Experience in Closed Beta",
        description=description,
        color=discord.Color.blurple()
    )
    choice_view = BetaChoice(
        ctx, ctx.author, opponent, 0,
        event1=event1, event2=event2,
        logger_callable=create_beta_log_df,
        spreadsheet_id=get_spreadsheet_id(data[3])
    )
    content = (
        f"What is Beta-Test for both "
        f"{ctx.author.mention} and {opponent.mention}?\n"
    )
    msg = await ctx.send(content=content, embed=embed, view=choice_view)
    choice_view.message_id = msg.id


@bot.command(aliases=["bs"])
async def beta_sheet(ctx: commands.Context, url: str = ""):
    try:
        await ctx.message.delete()
        if url == "":
            await ctx.send("Please provide a url")
            return
        spreadsheet_id = get_spreadsheet_id(url)
        if spreadsheet_id == "":
            await ctx.send("Please provide a url")
            return
        sheets = get_all_sheets(spreadsheet_id)
        if len(sheets) == 0:
            await ctx.send("No sheets found")
            return
        df_dict = {}
        for sheet in sheets:
            temp_df = get_df(spreadsheet_id, sheet.title)
            temp_df = temp_df.replace('#REF!', None, )
            temp_df = temp_df.dropna()
            if sheet.title == "log":
                continue
            if sheet.title == "ClosedBetaGacha":
                df_dict = temp_df.to_dict()
        betaEventMapRepo.set_gacha(
            guild_id=ctx.guild.id,
            items=json.dumps(df_dict),
            sheet_url=url
        )
        embed = discord.Embed()
        embed.title = "Beta Event"
        embed.description = "Beta Event Sheet is set."
        await ctx.send(
                content=f"New Beta Event [Spreadsheet]({url}) is added.",
                embed=embed
            )
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")
    return


def create_beta_log_df(
            spreadsheet_id: str,
            channel_name: str,
            user_id: int,
            user_name: str,
            target_id: int,
            target_user_name: str,
            event1: str,
            event2: str,
            result: str,
        ) -> bool:
    try:
        data = {
            "Timestamp":
                [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            "InitiatorHandle": [user_name],
            "InitiatorID": [str(user_id)],
            "InitiatorPC": "",
            "TargetHandle": [target_user_name],
            "TargetID": [str(target_id)],
            "TargetPC": "",
            "ChannelName": [channel_name],
            "Event Chosen 1": [event1],
            "Event Chosen 2": [event2],
            "Decision": [result]
        }
        log_df = pd.DataFrame(data=data)
        log_result_to_sheet(spreadsheet_id, log_df)
        return True
    except Exception as e:
        print(e, traceback.format_exc())
        return False



if __name__ == "__main__":
    charaRepo = CharacterUserMapRepository()
    gachaRepo = GachaMapRepository()
    downtimeRepo = DowntimeMapRepository()
    monsterRepo = MonsterListRepository()
    monsterMapRepo = MonstersUserMapRepository()
    betaEventMapRepo = BetaEventMapRepository()
    initRepo = InitiativeRepository()
    initiative_service = register_initiative_commands(
        bot, charaRepo, initRepo)
    main()
