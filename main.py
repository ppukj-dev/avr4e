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
from view import generator
import datetime
from repository import CharacterUserMapRepository, GachaMapRepository
from repository import MonsterListRepository
import constant
from pagination import Paginator
from pydantic import BaseModel
from pydantic.dataclasses import dataclass, Field
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from typing import List
from PIL import Image, ImageOps, ImageDraw

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
bot = commands.Bot(
    command_prefix=";;",
    intents=discord.Intents.all(),
    help_command=None
)

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
    # check_timestamps.start()
    await bot.tree.sync()
    print("We have logged in as {0.user}".format(bot))


@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")


@bot.command()
async def help(ctx):
    embed = discord.Embed()
    embed.title = "Avr4e Commands"
    desc = ""
    desc += "## Commands List\n"
    desc += "- Add to Discord: `;;add <link to sheet>`\n"
    desc += "- Update: `;;update`\n"
    desc += "\n"
    desc += "### Actions\n"
    desc += "- List: `;;a`\n"
    desc += "- Do action: `;;a <action name>`\n"
    desc += "- Checks: `;;c <skill name>`\n"
    desc += "- Action & Check Modifiers:\n"
    desc += "  - Adv/Dis: `;;a <action> adv/dis` `;;c <skill> adv/dis`\n"
    desc += "  - Situational Modifier: `;;a <action> -b <amount>` "
    desc += "`;;c <skill> -b <amount>`\n"
    desc += "  - Human Mode: `;;a <action> -h` `;;c <skill> -h`\n"
    desc += "  - Multiroll X times: `;;a <action> -rr X` `;;c <skill> -rr X`\n"
    desc += "  - Action Only:\n"
    desc += "    - Situational Damage: `;;a <action> -d <amount>`\n"
    desc += "    - Multi Target: `;;a <action> -t <target1> -t <target2>`\n"
    desc += "    - Use X Power Point: `;;action <action_name> -u X`\n"
    desc += "    - Autocrit: `;;a <action_name> crit`\n"
    desc += "\n"
    desc += "**Taking Rest**\n"
    desc += "- Short Rest: `;;reset sr`\n"
    desc += "- Extended Rest: `;;reset`"
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
async def update_sheet(ctx: commands.Context, url=""):
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
    charaRepo = CharacterUserMapRepository()
    character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
    df_data = pd.read_json(io.StringIO(character[2]))
    data_dict = create_data_dict(df_data)
    embed = create_embed(data_dict)

    await ctx.send(embed=embed)


@bot.command()
async def reset(ctx: commands.Context, *, args=None):
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
async def action(ctx: commands.Context, *, args=None):
    try:
        await ctx.message.delete()
        charaRepo = CharacterUserMapRepository()
        character = charaRepo.get_character(ctx.guild.id, ctx.author.id)
        sheet_id = character[0]
        name = character[1]
        data = pd.read_json(io.StringIO(character[2]))
        actions = pd.read_json(io.StringIO(character[3]))
        if args is None:
            embeds = create_action_list_embed(name, actions)
            view = Paginator(ctx.author, embeds)
            if len(embeds) <= 1:
                view = None
            await ctx.send(embed=embeds[0], view=view)
            return
        else:
            args = translate_cvar(args, data)
            embed = await handle_action(args, actions, ctx, data, sheet_id)
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


@bot.command()
async def token(ctx: commands.Context, *, args=None):
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


def create_action_list_embed(name: str, df: pd.DataFrame):
    max_length_description = 2500
    field_dict = {}
    embeds = []
    description = ""
    # embed.title = f"{name}'s Actions"
    for type1 in df['Type1'].unique().tolist():
        field_dict[type1] = ""
        for _, row in df[df['Type1'] == type1].iterrows():
            usages = ""
            if row['MaxUsages'] > 0:
                usages = f" ({row['Usages']}/{row['MaxUsages']})"
            type2 = ""
            if row['Type2']:
                type2 = f" ({row['Type2']})"
            field_dict[type1] += f"- **{row['Name']}**{type2}."
            field_dict[type1] += f" {row['ShortDesc']}{usages}\n"

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
        sheet_id: str):
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


def parse_command(message: str) -> ActionParam:
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


def create_action_result_embed(
        possible_action: pd.DataFrame,
        choosen: int,
        name: str,
        ap: ActionParam):
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
async def check(ctx: commands.Context, *, args=None):
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
        if embed is None:
            return
        await ctx.send(embed=embed)
    except Exception as e:
        print(e, traceback.format_exc())
        await ctx.send("Error. Please check input again.")


def create_check_result_embed(
        possible_check: pd.DataFrame,
        choosen: int,
        name: str,
        ap: ActionParam):
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


def draw_quota(max_usages: int, usages: int) -> str:
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
    datetime.time(hour=0, tzinfo=utc),
    datetime.time(hour=12, tzinfo=utc)
]


@tasks.loop(time=times)
async def check_timestamps():
    channel_calendar = bot.get_channel(1265647805867888741)
    start_date = datetime.datetime(2024, 8, 17, 0, 0, 0, tzinfo=utc)
    now = datetime.datetime.now(utc)
    delta = now - start_date
    total_sessions = int(delta.total_seconds() // (60 * 60 * 12))
    start_month = 2
    month_number = int((start_month + (total_sessions // 7)) % 12)
    chapter_number = total_sessions // 14 + 1
    month = f"月 {month_number+1:02}"
    session_number = f"{total_sessions+1:02}"
    month_season_dict = {
        3: "🌸", 4: "🌸", 5: "🌸",
        6: "🌞", 7: "🌞", 8: "🌞",
        9: "🍁", 10: "🍁", 11: "🍁",
        12: "❄️", 1: "❄️", 2: "❄️"
    }
    season = month_season_dict[month_number+1]
    channel_name = f"📅 {month} {season} - {chapter_number}.{session_number}"
    try:
        await channel_calendar.edit(name=channel_name)
    except Exception as e:
        print(e, traceback.format_exc())


def two_digit(number: int):
    if number < 10:
        return f"0{number}"
    return str(number)


def main():
    # uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('APP_PORT')))
    bot.run(TOKEN)
    pass


@bot.command()
async def gacha(ctx: commands.Context):
    try:
        await ctx.message.delete()
        gachaRepo = GachaMapRepository()
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
        embed = discord.Embed()
        embed.title = "Gacha Result"
        embed.description = f"**{sheet.title()}**: {result}"
        embed.set_author(name=ctx.author.name, icon_url=ctx.author.avatar.url)
        await ctx.send(embed=embed)
        create_gacha_log_df(
            spreadsheet_id,
            ctx.channel.id,
            ctx.channel.name,
            ctx.author.id,
            ctx.author.name,
            result
        )
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


def get_random_from_sheet(sheet_dict: dict) -> str:
    random_value = random.choice(list(sheet_dict["value"].values()))
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
        gachaRepo = GachaMapRepository()
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
            result: str
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


@bot.command(aliases=["generate", "gen_enc"])
async def generate_random_encounter(
        ctx: commands.Context,
        party_level: int = 1,
        chara: int = 5,
        difficulty: str = "normal"):
    if (
            difficulty not in ["easy", "normal", "hard"] and
            not difficulty.isnumeric()):
        await ctx.send("Difficulty must be easy/normal/hard/number.")
        return
    if difficulty == "easy":
        floor, ceil = party_level-2, party_level-1
        min_xp, max_xp = get_budget(floor, chara), get_budget(ceil, chara)
    elif difficulty == "normal":
        floor, ceil = party_level, party_level+1
        min_xp, max_xp = get_budget(floor, chara), get_budget(ceil, chara)
    elif difficulty == "hard":
        floor, ceil = party_level+2, party_level+4
        min_xp, max_xp = get_budget(floor, chara), get_budget(ceil, chara)
    else:
        floor, ceil = party_level, party_level
        min_xp, max_xp = 0.9 * int(difficulty), int(difficulty)
    floor = max(floor-3, 1)
    ceil = min(ceil+3, 32)
    levels = list(range(floor, ceil+1))
    monsterRepo = MonsterListRepository()
    monster_list = monsterRepo.get_monsters_by_levels(levels)
    if monster_list is None:
        await ctx.send("No monsters found.")
        return None
    encounter, total_xp = generate_encounter(min_xp, max_xp, monster_list)
    embed = discord.Embed()
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
        f"**Budget**: {difficulty.title()}\n"
    )
    await ctx.send(embed=embed)
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
        monsterRepo = MonsterListRepository()
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


if __name__ == "__main__":
    main()
