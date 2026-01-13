import asyncio
import datetime
import io
import d20
import pandas as pd
import discord
from discord.ext import commands


class InitiativeService:
    def __init__(self, bot: commands.Bot, init_repo):
        self.bot = bot
        self.init_repo = init_repo

    @staticmethod
    def format_number(value: int) -> str:
        if int(value) >= 0:
            return f"+{value}"
        return f"{value}"

    @staticmethod
    def normalize_name(name: str) -> str:
        return " ".join(name.split()).casefold()

    @staticmethod
    def init_state_default() -> dict:
        return {
            "combatants": {},
            "current_turn": 0,
            "round": 0,
            "active": False,
            "started": False,
            "pinned_message_id": None,
            "next_join_order": 1,
            "manual_order_override": False
        }

    def load_state(self, ctx: commands.Context) -> dict:
        channel_id = ctx.channel.id
        if not hasattr(self.bot, 'init_lists'):
            self.bot.init_lists = {}
        if channel_id not in self.bot.init_lists:
            state = self.init_state_default()
            guild_id = str(ctx.guild.id) if ctx.guild else None
            if guild_id and self.init_repo:
                db_state = self.init_repo.get_state(guild_id, str(channel_id))
                if db_state:
                    (
                        _id,
                        _guild_id,
                        _channel_id,
                        current_turn,
                        round_value,
                        active,
                        started,
                        pinned_message_id,
                        manual_order_override,
                        _updated_at
                    ) = db_state
                    state["current_turn"] = current_turn
                    state["round"] = round_value
                    state["active"] = bool(active)
                    state["started"] = bool(started)
                    state["pinned_message_id"] = pinned_message_id
                    state["manual_order_override"] = bool(manual_order_override)
                    combatants = self.init_repo.list_combatants(
                        guild_id, str(channel_id))
                    for row in combatants:
                        (
                            name,
                            name_key,
                            initiative,
                            modifier,
                            ac,
                            fort,
                            ref,
                            will,
                            author_id,
                            source,
                            join_order,
                            created_at
                        ) = row
                        state["combatants"][name_key] = {
                            "name": name,
                            "initiative": initiative,
                            "modifier": modifier,
                            "ac": ac,
                            "fort": fort,
                            "ref": ref,
                            "will": will,
                            "author_id": author_id,
                            "source": source,
                            "join_order": join_order,
                            "created_at": created_at
                        }
                    state["next_join_order"] = self.init_repo.get_next_join_order(
                        guild_id, str(channel_id))
            self.bot.init_lists[channel_id] = state
        return self.bot.init_lists[channel_id]

    def save_state(self, ctx: commands.Context, state: dict) -> None:
        if not ctx.guild or not self.init_repo:
            return
        self.init_repo.upsert_state(
            str(ctx.guild.id),
            str(ctx.channel.id),
            int(state["current_turn"]),
            int(state["round"]),
            1 if state["active"] else 0,
            1 if state["started"] else 0,
            state.get("pinned_message_id"),
            1 if state.get("manual_order_override") else 0
        )

    def save_combatant(self, ctx: commands.Context, name_key: str, data: dict) -> None:
        if not ctx.guild or not self.init_repo:
            return
        self.init_repo.upsert_combatant(
            str(ctx.guild.id),
            str(ctx.channel.id),
            data["name"],
            name_key,
            int(data["initiative"]),
            int(data.get("modifier", 0)),
            str(data.get("ac", "?")),
            str(data.get("fort", "?")),
            str(data.get("ref", "?")),
            str(data.get("will", "?")),
            str(data.get("author_id", "")),
            data.get("source", "manual"),
            int(data.get("join_order", 0))
        )

    def delete_combatant(self, ctx: commands.Context, name_key: str) -> None:
        if not ctx.guild or not self.init_repo:
            return
        self.init_repo.delete_combatant(
            str(ctx.guild.id), str(ctx.channel.id), name_key)

    def clear_combatants(self, ctx: commands.Context) -> None:
        if not ctx.guild or not self.init_repo:
            return
        self.init_repo.delete_all_combatants(
            str(ctx.guild.id), str(ctx.channel.id))

    def sort_key(self, state: dict):
        manual_override = state.get("manual_order_override", False)

        def key_fn(item):
            _name_key, data = item
            initiative = int(data.get("initiative", 0))
            modifier = int(data.get("modifier", 0))
            source = data.get("source", "manual")
            priority = 1 if source == "player" else 0
            join_order = int(data.get("join_order", 0))
            if manual_override:
                return (join_order,)
            return (-initiative, -modifier, -priority, join_order)

        return key_fn

    @staticmethod
    def parse_initiative_flags(args: list) -> tuple:
        flags = {
            "p": None,
            "ac": None,
            "fort": None,
            "ref": None,
            "will": None,
            "b": None
        }
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ("-p", "-ac", "-fort", "-ref", "-will", "-b"):
                if i + 1 >= len(args):
                    return None, f"Missing value for {arg}"
                try:
                    flags[arg.lstrip("-")] = int(args[i + 1])
                except ValueError:
                    return None, f"Invalid value for {arg}. Must be an integer."
                i += 2
            else:
                i += 1
        return flags, None

    def find_matching_combatants(self, combatants: dict, partial: str) -> list:
        partial_key = self.normalize_name(partial)
        matches = []
        for name_key, data in combatants.items():
            if partial_key in name_key:
                matches.append((name_key, data["name"]))
        return matches

    def upsert_combatant_state(
            self,
            ctx: commands.Context,
            state: dict,
            name: str,
            initiative: int,
            modifier: int,
            ac: str,
            fort: str,
            ref: str,
            will: str,
            author_id: str,
            source: str
            ) -> dict:
        name_key = self.normalize_name(name)
        existing = state["combatants"].get(name_key)
        if existing:
            join_order = existing.get("join_order", 0)
        else:
            join_order = state["next_join_order"]
            state["next_join_order"] += 1
        data = {
            "name": name,
            "initiative": int(initiative),
            "modifier": int(modifier),
            "ac": ac,
            "fort": fort,
            "ref": ref,
            "will": will,
            "author_id": author_id,
            "source": source,
            "join_order": join_order,
            "created_at": (
                existing.get("created_at") if existing else
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        }
        state["combatants"][name_key] = data
        self.save_combatant(ctx, name_key, data)
        return data

    def render_message(self, state: dict) -> str:
        combatants = state["combatants"]
        if not combatants:
            return (
                "```diff\n"
                f"Current initiative: Round {state['round']}\n"
                "===============================\n"
                "No combatants have joined yet```\n"
            )
        sorted_init = sorted(combatants.items(), key=self.sort_key(state))
        current_label = f"Round {state['round']}"
        current_name_key = None
        if state["started"] and state["current_turn"] < len(sorted_init):
            current_name_key = sorted_init[state["current_turn"]][0]
            current_label = (
                f"{sorted_init[state['current_turn']][1]['name']} "
                f"(round {state['round']})"
            )
        lines = [
            "```diff",
            f"Current initiative: {current_label}",
            "==============================="
        ]
        max_init_width = max(
            (len(str(data.get("initiative", 0))) for _, data in sorted_init),
            default=1
        )
        for name_key, combatant in sorted_init:
            prefix = "+" if combatant.get("source") == "player" else "-"
            display_name = combatant["name"]
            mod = self.format_number(int(combatant.get("modifier", 0)))
            ac = combatant.get("ac", "?")
            fort = combatant.get("fort", "?")
            ref = combatant.get("ref", "?")
            will = combatant.get("will", "?")
            initiative_score = str(combatant["initiative"]).rjust(max_init_width)
            core = (
                f"{initiative_score} : {display_name} "
                f"(AC{ac} F{fort} R{ref} W{will})"
            )
            if current_name_key == name_key:
                lines.append(f"> {core}")
            else:
                lines.append(f"{prefix} {core}")
        lines.append("```")
        return "\n".join(lines)

    async def update_pinned_message(
            self,
            ctx: commands.Context,
            state: dict,
            message: str
            ) -> None:
        pinned_id = state.get("pinned_message_id")
        if pinned_id:
            try:
                message_obj = await ctx.channel.fetch_message(pinned_id)
                await message_obj.edit(content=message)
                return
            except Exception:
                pass
        sent_message = await ctx.send(message)
        try:
            await sent_message.pin()
        except Exception:
            await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")
        state["pinned_message_id"] = sent_message.id
        self.save_state(ctx, state)

    async def maybe_join_from_check(
            self,
            ctx: commands.Context,
            base_name: str,
            results: list,
            modifier_value: int,
            source: str,
            stats: dict = None,
            multi_name: bool = False
            ) -> str:
        state = self.load_state(ctx)
        if not state["active"]:
            return "No Initiative Tracker Set"
        if not results:
            return None
        stats = stats or {}
        joined = []
        if source == "player" or not multi_name or len(results) == 1:
            result = results[-1]
            self.upsert_combatant_state(
                ctx,
                state,
                base_name,
                result.total,
                modifier_value,
                stats.get("ac", "?"),
                stats.get("fort", "?"),
                stats.get("ref", "?"),
                stats.get("will", "?"),
                str(ctx.author.id),
                source
            )
            joined.append(f"{base_name} {result.total}")
        else:
            for idx, result in enumerate(results, 1):
                name = f"{base_name} {idx}"
                self.upsert_combatant_state(
                    ctx,
                    state,
                    name,
                    result.total,
                    modifier_value,
                    stats.get("ac", "?"),
                    stats.get("fort", "?"),
                    stats.get("ref", "?"),
                    stats.get("will", "?"),
                    str(ctx.author.id),
                    source
                )
                joined.append(f"{name} {result.total}")
        message = self.render_message(state)
        await self.update_pinned_message(ctx, state, message)
        self.save_state(ctx, state)
        if not joined:
            return None
        if len(joined) == 1:
            parts = joined[0].split()
            return f"Added {parts[0]} to Initiative {parts[-1]}"
        return "Added to Initiative: " + ", ".join(
            f"Added {name} to Initiative {total}"
            for name, total in (item.rsplit(" ", 1) for item in joined)
        )

    def find_field_value(self, data: pd.DataFrame, key: str):
        if data is None or data.empty:
            return None
        if 'field_name' not in data.columns or 'value' not in data.columns:
            return None
        exact = data[data['field_name'].str.casefold() == key.casefold()]
        if len(exact.index) > 0:
            return exact['value'].iloc[0]
        matches = data[data['field_name'].str.contains(key, case=False, na=False)]
        if len(matches.index) > 0:
            return matches['value'].iloc[0]
        return None


def register_initiative_commands(
        bot: commands.Bot,
        chara_repo,
        init_repo
        ) -> InitiativeService:
    service = InitiativeService(bot, init_repo)

    async def prompt_reorder_position(
            ctx: commands.Context,
            service: InitiativeService,
            state: dict,
            target_key: str,
            updated_text: str
            ) -> None:
        combatants = state["combatants"]
        if target_key not in combatants:
            return
        ordered = sorted(combatants.items(), key=service.sort_key(state))
        ordered = [(key, data) for key, data in ordered if key != target_key]
        options = [
            discord.SelectOption(
                label="The beginning of the initiative",
                value="__begin__"
            )
        ]
        for name_key, data in ordered:
            options.append(
                discord.SelectOption(label=data["name"], value=name_key)
            )
        if len(options) == 1:
            await ctx.send(updated_text)
            return

        select = discord.ui.Select(
            placeholder="After which combatant?",
            options=options
        )

        async def on_select(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message(
                    "You cannot use this selection.", ephemeral=True)
                return
            selection = select.values[0]
            target_data = combatants[target_key]
            new_order = []
            if selection == "__begin__":
                highest = max(
                    (data["initiative"] for _, data in ordered),
                    default=target_data["initiative"]
                )
                target_data["initiative"] = highest
                new_order.append(target_key)
                new_order.extend([key for key, _ in ordered])
            else:
                for key, _ in ordered:
                    new_order.append(key)
                    if key == selection:
                        target_data["initiative"] = combatants[key]["initiative"]
                        new_order.append(target_key)
            if target_key not in new_order:
                new_order.append(target_key)
            for idx, key in enumerate(new_order, 1):
                combatants[key]["join_order"] = idx
                service.save_combatant(ctx, key, combatants[key])
            state["next_join_order"] = len(new_order) + 1
            state["manual_order_override"] = True
            message = service.render_message(state)
            await service.update_pinned_message(ctx, state, message)
            service.save_state(ctx, state)
            refreshed_text = (
                f"{ctx.author.mention} updated **{target_data['name']}** → "
                f"Initiative: {target_data['initiative']}, AC: {target_data['ac']}, "
                f"Fort: {target_data['fort']}, Ref: {target_data['ref']}, "
                f"Will: {target_data['will']}"
            )
            await interaction.response.edit_message(
                content=refreshed_text, view=None, embed=None)

        select.callback = on_select
        view = discord.ui.View()
        view.add_item(select)
        await ctx.send(
            f"{ctx.author.mention} reordering **{combatants[target_key]['name']}**. "
            "After which combatant?",
            view=view
        )

    @bot.command(aliases=["i", "initiative"])
    async def init(ctx: commands.Context, *args: str):
        channel_id = ctx.channel.id
        state = service.load_state(ctx)
        prompt_message = None
        try:
            if not args:
                if not state["active"]:
                    await ctx.send(f"Initiative tracking has not started. Use {ctx.prefix}i begin to start tracking initiative.")
                    return
                pinned_id = state.get("pinned_message_id")
                if pinned_id:
                    try:
                        message_obj = await ctx.channel.fetch_message(pinned_id)
                        if message_obj.content:
                            await ctx.send(message_obj.content)
                            return
                    except Exception:
                        pass
                message = service.render_message(state)
                await ctx.send(message)
                return

            if args[0] == "begin":
                state = service.init_state_default()
                state["active"] = True
                bot.init_lists[channel_id] = state
                service.clear_combatants(ctx)
                message = service.render_message(state)
                sent_message = await ctx.send(message)
                await ctx.send(
                    f"Initiative tracker started. Use {ctx.prefix}c init or "
                    f"{ctx.prefix}c <skill> -init to join the initiative."
                )

                # Unpin any previously pinned initiative message
                try:
                    pins = await ctx.channel.pins()
                    for pin in pins:
                        if pin.author == bot.user and pin.id != sent_message.id:
                            if "Current initiative" in pin.content:
                                await pin.unpin()
                except Exception:
                    pass

                try:
                    await sent_message.pin()
                except Exception:
                    await ctx.send("⚠️ I couldn’t pin the initiative message. Please check my permissions.")

                # Store pinned message ID
                state["pinned_message_id"] = sent_message.id
                service.save_state(ctx, state)
                return

            if not state["active"]:
                await ctx.send(f"Initiative tracking has not started. Use {ctx.prefix}i begin to start tracking initiative.")
                return

            if args[0] == "join":
                character = chara_repo.get_character(ctx.guild.id, ctx.author.id)
                if character is None:
                    await ctx.send("Please add your character sheet first using !add")
                    return

                data = pd.read_json(io.StringIO(character[2]))
                name = service.find_field_value(data, "Name")
                init_bonus = service.find_field_value(data, "Initiative")
                ac = service.find_field_value(data, "AC")
                fort = service.find_field_value(data, "FORT")
                ref = service.find_field_value(data, "REF")
                will = service.find_field_value(data, "WILL")

                if any(pd.isna(val) for val in (name, init_bonus, ac, fort, ref, will)):
                    await ctx.send(
                        "Failed to fetch all required stats for initiative. Please check your character sheet contains Name, Initiative, AC, Fort, Reflex and Will.")
                    return

                name_key = service.normalize_name(name)
                if name_key in state["combatants"]:
                    await ctx.send(f"{name} has already joined initiative.")
                    return

                bonus = 0
                manual_initiative = None

                if "-b" in args:
                    try:
                        b_index = args.index("-b")
                        if b_index + 1 < len(args):
                            bonus = int(args[b_index + 1])
                    except ValueError:
                        await ctx.send("Invalid bonus value. Bonus must be an integer.")
                        return

                if "-p" in args:
                    try:
                        p_index = args.index("-p")
                        if p_index + 1 < len(args):
                            manual_initiative = int(args[p_index + 1])
                    except ValueError:
                        await ctx.send("Invalid initiative value. Must be an integer.")
                        return

                try:
                    if manual_initiative is not None:
                        initiative_result = manual_initiative
                        await ctx.send(f"{name} joins with preset initiative {initiative_result}")
                    else:
                        total_bonus = int(init_bonus) + bonus
                        roll = d20.roll(f"1d20+{total_bonus}")
                        initiative_result = roll.total
                        await ctx.send(f"{name} rolled {roll} for initiative")

                    service.upsert_combatant_state(
                        ctx,
                        state,
                        name,
                        initiative_result,
                        int(init_bonus) + bonus,
                        ac,
                        fort,
                        ref,
                        will,
                        str(ctx.author.id),
                        "player"
                    )
                    message = service.render_message(state)
                    await service.update_pinned_message(ctx, state, message)
                    service.save_state(ctx, state)
                except Exception as e:
                    await ctx.send(f"Error when rolling initiative: {str(e)}")

            elif args[0] == "add":
                if len(args) < 3:
                    await ctx.send(
                        "Usage: \n"
                        f" • {ctx.prefix}i add <combatant name> -p <target initiative> "
                        "[-ac <AC>] [-fort <Fort>] [-ref <Ref>] [-will <Will>]\n"
                        f" • {ctx.prefix}i add <combatant name> <initiative modifier> "
                        "[-ac <AC>] [-fort <Fort>] [-ref <Ref>] [-will <Will>]"
                    )
                    return
                try:
                    name = args[1]
                    flags, error = service.parse_initiative_flags(args[2:])
                    if error:
                        await ctx.send(error)
                        return

                    ac = "?" if flags["ac"] is None else flags["ac"]
                    fort = "?" if flags["fort"] is None else flags["fort"]
                    ref = "?" if flags["ref"] is None else flags["ref"]
                    will = "?" if flags["will"] is None else flags["will"]
                    author_id = ctx.author.id

                    initiative = None
                    modifier = 0
                    if args[2] != "-p":
                        if args[2].replace('-', '').replace('+', '').isdigit():
                            modifier = int(args[2])
                            initiative = d20.roll(f"1d20+{args[2]}").total
                        else:
                            initiative = d20.roll("1d20").total

                    if flags["p"] is not None:
                        initiative = int(flags["p"])

                    if initiative is None:
                        initiative = d20.roll("1d20").total

                    service.upsert_combatant_state(
                        ctx,
                        state,
                        name,
                        initiative,
                        modifier,
                        ac,
                        fort,
                        ref,
                        will,
                        str(author_id),
                        "manual"
                    )
                    await ctx.send(f"Added {name} with initiative {initiative}")
                    message = service.render_message(state)
                    await service.update_pinned_message(ctx, state, message)
                    service.save_state(ctx, state)
                except ValueError:
                    await ctx.send("Initiative must be a number")

            elif args[0] == "edit":
                if len(args) < 2:
                    await ctx.send(
                        f"Usage: {ctx.prefix}i edit <combatant name> "
                        "[-p <initiative>] [-ac <AC>] [-fort <Fort>] "
                        "[-ref <Ref>] [-will <Will>]"
                    )
                    return
                if state.get("pending_edit"):
                    await ctx.send("An edit is already in progress. Please finish it first.")
                    return

                partial_name = args[1]
                combatants = state["combatants"]
                matches = service.find_matching_combatants(combatants, partial_name)
                if not matches:
                    await ctx.send(
                        f"No combatant matching '{partial_name}' found in the initiative tracker.")
                    return

                matched_key = None
                prompt_message = None
                if len(matches) == 1:
                    matched_key = matches[0][0]
                else:
                    state["pending_edit"] = {
                        "user_id": ctx.author.id,
                        "candidates": matches[:10]
                    }

                    embed = discord.Embed(
                        title="Multiple matches found",
                        description="Which combatant are you trying to edit?",
                        color=discord.Color.red()
                    )
                    limited_matches = matches[:10]
                    choices = "\n".join(
                        f"{i}. {combatant_name}"
                        for i, (_, combatant_name) in enumerate(limited_matches, 1)
                    )
                    embed.description = (
                        "Which combatant are you trying to edit?\n" + choices
                    )

                    embed.set_footer(
                        text="Reply with the number of the combatant you want to edit.")
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
                        candidates = state["pending_edit"]["candidates"][:10]
                        if index < 0 or index >= len(candidates):
                            await ctx.send("Invalid selection number. Edit cancelled.")
                            if prompt_message:
                                await prompt_message.delete()
                            await msg.delete()
                            del state["pending_edit"]
                            return
                        matched_key = candidates[index][0]
                        if prompt_message:
                            await prompt_message.delete()
                        await msg.delete()
                        del state["pending_edit"]
                    except asyncio.TimeoutError:
                        await ctx.send("No response received. Edit cancelled.")
                        if prompt_message:
                            await prompt_message.delete()
                        del state["pending_edit"]
                        return

                current_data = combatants[matched_key]
                flags, error = service.parse_initiative_flags(args[2:])
                if error:
                    await ctx.send(error)
                    return

                initiative = current_data["initiative"]
                ac = current_data["ac"]
                fort = current_data["fort"]
                ref = current_data["ref"]
                will = current_data["will"]
                author_id = current_data["author_id"]
                modifier = current_data.get("modifier", 0)
                source = current_data.get("source", "manual")

                if flags["p"] is not None:
                    initiative = int(flags["p"])
                if flags["ac"] is not None:
                    ac = flags["ac"]
                if flags["fort"] is not None:
                    fort = flags["fort"]
                if flags["ref"] is not None:
                    ref = flags["ref"]
                if flags["will"] is not None:
                    will = flags["will"]

                service.upsert_combatant_state(
                    ctx,
                    state,
                    current_data["name"],
                    initiative,
                    modifier,
                    ac,
                    fort,
                    ref,
                    will,
                    author_id,
                    source
                )
                updated_text = (
                    f"{ctx.author.mention} updated **{current_data['name']}** → "
                    f"Initiative: {initiative}, "
                    f"AC: {ac}, Fort: {fort}, Ref: {ref}, Will: {will}"
                )
                await prompt_reorder_position(
                    ctx, service, state, matched_key, updated_text
                )
                message = service.render_message(state)
                await service.update_pinned_message(ctx, state, message)
                service.save_state(ctx, state)

            elif args[0] == "end":
                confirm_view = discord.ui.View()
                confirm_button = discord.ui.Button(
                    label="Confirm", style=discord.ButtonStyle.danger)
                cancel_button = discord.ui.Button(
                    label="Cancel", style=discord.ButtonStyle.secondary)

                async def confirm_callback(interaction):
                    if interaction.user != ctx.author:
                        await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                        return
                    cleared_state = service.init_state_default()
                    bot.init_lists[channel_id] = cleared_state
                    cleared_state["active"] = False
                    service.clear_combatants(ctx)
                    pinned_id = state.get("pinned_message_id")
                    if pinned_id:
                        try:
                            message_obj = await ctx.channel.fetch_message(pinned_id)
                            await message_obj.delete()
                        except Exception:
                            pass
                    cleared_state["pinned_message_id"] = None
                    service.save_state(ctx, cleared_state)
                    await interaction.message.edit(content="Initiative tracker cleared.", view=None)

                async def cancel_callback(interaction):
                    if interaction.user != ctx.author:
                        await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                        return

                    await interaction.message.edit(content="Initiative tracker was not cleared.", view=None)

                confirm_button.callback = confirm_callback
                cancel_button.callback = cancel_callback
                confirm_view.add_item(confirm_button)
                confirm_view.add_item(cancel_button)
                await ctx.send("**Are you sure you want to end the initiative tracker?**", view=confirm_view)

            elif args[0] == "remove":
                if len(args) < 2:
                    await ctx.send(f"Usage: {ctx.prefix}i remove <combatant name>")
                    return

                partial = args[1]
                combatants = state["combatants"]

                matches = service.find_matching_combatants(combatants, partial)
                if not matches:
                    await ctx.send(f"No combatants matching '{partial}' found.")
                    return

                prompt_message = None
                if len(matches) == 1:
                    target_key, target_name = matches[0]

                    confirm_view = discord.ui.View()
                    confirm_button = discord.ui.Button(
                        label="Confirm", style=discord.ButtonStyle.danger)
                    cancel_button = discord.ui.Button(
                        label="Cancel", style=discord.ButtonStyle.secondary)

                    async def confirm_callback(interaction):
                        if interaction.user != ctx.author:
                            await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                            return
                        del combatants[target_key]
                        service.delete_combatant(ctx, target_key)
                        await interaction.message.edit(content=f"Removed **{target_name}** from initiative.", view=None)
                        message = service.render_message(state)
                        await service.update_pinned_message(ctx, state, message)

                    async def cancel_callback(interaction):
                        if interaction.user != ctx.author:
                            await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                            return
                        await interaction.message.edit(content="Removal cancelled.", view=None)

                    confirm_button.callback = confirm_callback
                    cancel_button.callback = cancel_callback
                    confirm_view.add_item(confirm_button)
                    confirm_view.add_item(cancel_button)

                    await ctx.send(f"Are you sure you want to remove **{target_name}** from initiative?", view=confirm_view)
                else:
                    state["pending_remove"] = {
                        "user_id": ctx.author.id,
                        "candidates": matches[:10]
                    }

                    embed = discord.Embed(
                        title="Multiple matches found",
                        description="Which combatant are you trying to remove?",
                        color=discord.Color.red()
                    )
                    limited_matches = matches[:10]
                    choices = "\n".join(
                        f"{i}. {name}"
                        for i, (_, name) in enumerate(limited_matches, 1)
                    )
                    embed.description = (
                        "Which combatant are you trying to remove?\n" + choices
                    )

                    embed.set_footer(
                        text="Reply with the number of the combatant you want to remove.")
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
                        candidates = state["pending_remove"]["candidates"][:10]
                        if index < 0 or index >= len(candidates):
                            await ctx.send("Invalid selection number. Removal cancelled.")
                            if prompt_message:
                                await prompt_message.delete()
                            await msg.delete()
                            del state["pending_remove"]
                            return

                        target_key, target_name = candidates[index]
                        if prompt_message:
                            await prompt_message.delete()
                        await msg.delete()

                        # Confirm removal
                        confirm_view = discord.ui.View()
                        confirm_button = discord.ui.Button(
                            label="Confirm", style=discord.ButtonStyle.danger)
                        cancel_button = discord.ui.Button(
                            label="Cancel", style=discord.ButtonStyle.secondary)

                        async def confirm_callback(interaction):
                            if interaction.user != ctx.author:
                                await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                                return
                            del combatants[target_key]
                            service.delete_combatant(ctx, target_key)
                            await interaction.message.edit(content=f"Removed **{target_name}** from initiative.", view=None)
                            message = service.render_message(state)
                            await service.update_pinned_message(ctx, state, message)
                            del state["pending_remove"]

                        async def cancel_callback(interaction):
                            if interaction.user != ctx.author:
                                await interaction.response.send_message("You cannot use this button.", ephemeral=True)
                                return
                            await interaction.message.edit(content="Removal cancelled.", view=None)
                            del state["pending_remove"]

                        confirm_button.callback = confirm_callback
                        cancel_button.callback = cancel_callback
                        confirm_view.add_item(confirm_button)
                        confirm_view.add_item(cancel_button)

                        await ctx.send(f"Are you sure you want to remove **{target_name}** from initiative?", view=confirm_view)

                    except asyncio.TimeoutError:
                        await ctx.send("No response received. Removal cancelled.")
                        if prompt_message:
                            await prompt_message.delete()
                        del state["pending_remove"]

            elif args[0] == "next":
                if not state["combatants"]:
                    await ctx.send("No active combat.")
                    return

                sorted_init = sorted(
                    state["combatants"].items(), key=service.sort_key(state))

                if state["current_turn"] >= len(sorted_init):
                    state["current_turn"] = 0

                if not state.get("started", False):
                    state["started"] = True
                    state["current_turn"] = 0
                    state["round"] = 1
                else:
                    state["current_turn"] += 1
                    if state["current_turn"] >= len(sorted_init):
                        state["current_turn"] = 0
                        state["round"] += 1

                current = sorted_init[state["current_turn"]]
                combatant_name = current[1]["name"]
                initiative = current[1]["initiative"]
                author_id = current[1]["author_id"]

                message_lines = [
                    f"**Initiative {initiative} (round {state['round']})**: {combatant_name} (<@{str(author_id)}>)",
                    f"```md\n{combatant_name} <None>\n```"
                ]

                try:
                    if state["current_turn"] < len(sorted_init) - 1:
                        next_combatant = sorted_init[state["current_turn"] + 1]
                    else:
                        next_combatant = sorted_init[0]
                    next_name = next_combatant[1]["name"]
                    next_init = next_combatant[1]["initiative"]
                    next_author_id = next_combatant[1]["author_id"]
                    # message_lines.append(
                    #     f"Next: **Initiative {next_init} (round {state['round']})**: {next_name} (<@{str(next_author_id)}>)"
                    # )
                    # message_lines.append(f"```md\n{next_name} <None>\n```")
                except Exception as e:
                    await ctx.send(e)

                await ctx.send("\n".join(message_lines))

                message = service.render_message(state)
                await service.update_pinned_message(ctx, state, message)
                service.save_state(ctx, state)
            elif args[0] == "prev":
                if not state["combatants"]:
                    await ctx.send("No active combat.")
                    return

                sorted_init = sorted(
                    state["combatants"].items(), key=service.sort_key(state))

                if state["current_turn"] >= len(sorted_init):
                    state["current_turn"] = 0

                if not state.get("started", False):
                    state["started"] = True
                    state["current_turn"] = 0
                    state["round"] = 1
                else:
                    if state["round"] <= 1 and state["current_turn"] <= 0:
                        await ctx.send("Already at the first turn of round 1.")
                        return
                    state["current_turn"] -= 1
                    if state["current_turn"] < 0:
                        state["current_turn"] = len(sorted_init) - 1
                        state["round"] = max(1, state["round"] - 1)

                current = sorted_init[state["current_turn"]]
                combatant_name = current[1]["name"]
                initiative = current[1]["initiative"]
                author_id = current[1]["author_id"]

                message_lines = [
                    f"**Initiative {initiative} (round {state['round']})**: {combatant_name} (<@{str(author_id)}>)",
                    f"```md\n{combatant_name} <None>\n```"
                ]

                try:
                    if state["current_turn"] < len(sorted_init) - 1:
                        next_combatant = sorted_init[state["current_turn"] + 1]
                    else:
                        next_combatant = sorted_init[0]
                    next_name = next_combatant[1]["name"]
                    next_init = next_combatant[1]["initiative"]
                    next_author_id = next_combatant[1]["author_id"]
                    # message_lines.append(
                    #     f"Next: **Initiative {next_init} (round {state['round']})**: {next_name} (<@{str(next_author_id)}>)"
                    # )
                    # message_lines.append(f"```md\n{next_name} <None>\n```")
                except Exception as e:
                    await ctx.send(e)

                await ctx.send("\n".join(message_lines))

                message = service.render_message(state)
                await service.update_pinned_message(ctx, state, message)
                service.save_state(ctx, state)
            else:
                await ctx.send(f"Unrecognized subcommand: {args[0]}.")

        finally:
            try:
                await ctx.message.delete()
            except Exception:
                pass

    return service
