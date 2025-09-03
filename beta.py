import discord
from discord.ext import commands
from discord.ui import View, Button, button


class BetaChoice(View):
    def __init__(
        self, ctx: commands.Context,
        player1: discord.Member,
        player2: discord.Member,
        message_id: int,
        event1: str,
        event2: str,
        spreadsheet_id: str,
        logger_callable: callable
    ):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.player1 = player1
        self.player2 = player2
        self.message_id = message_id
        self.event1 = event1
        self.event2 = event2
        self.choices = {}
        self.spreadsheet_id = spreadsheet_id
        self.logger_callable = logger_callable

    async def interaction_check(
            self, interaction: discord.Interaction) -> bool:
        return interaction.user.id in (self.player1.id, self.player2.id)

    async def on_timeout(self):
        msg = await self.ctx.channel.fetch_message(self.message_id)
        await msg.edit(content="⏰ Game timed out.", view=None)

    async def button_click(
        self,
        interaction: discord.Interaction,
        choice: str,
        emoji: str
    ):
        self.choices[interaction.user.id] = choice
        await interaction.response.send_message(
            content=f"You chose {emoji} **{choice.capitalize()}**!",
            ephemeral=True,
            delete_after=2
        )

        msg = await self.ctx.channel.fetch_message(self.message_id)
        embed = msg.embeds[0]
        content = embed.description

        if interaction.user.id == self.player1.id:
            content = content.replace(
                f"{self.player1.mention}: ❓", f"{self.player1.mention}: ✅")
        else:
            content = content.replace(
                f"{self.player2.mention}: ❓", f"{self.player2.mention}: ✅")
        embed.description = content
        await msg.edit(embed=embed)
        if len(self.choices) == 2:
            await self.resolve_game()

    async def resolve_game(self):
        p1_choice = self.choices[self.player1.id]
        p2_choice = self.choices[self.player2.id]

        emoji_map = {"both": "🤝", "a": "🅰️", "b": "🅱️", "none": "🚫"}
        msg = await self.ctx.channel.fetch_message(self.message_id)

        result_text = (
            f"{self.player1.mention} {emoji_map[p1_choice]} vs "
            f"{emoji_map[p2_choice]} {self.player2.mention}\n\n"
            f"{self.get_result(p1_choice, p2_choice)}"
        )
        embed = discord.Embed(
            title="Canon Event in Beta",
            description=result_text,
            color=discord.Color.blurple()
        )
        embed.set_footer(
            text=(
                "Please open a thread to this message "
                "for discussing the detail of the shared experience (if any)."
            )
        )
        await msg.channel.send(
            content=f"{self.player1.mention} and {self.player2.mention}",
            embed=embed
        )
        self.logger_callable(
            spreadsheet_id=self.spreadsheet_id,
            channel_name=self.ctx.channel.name,
            user_id=self.player1.id,
            user_name=self.player1.name,
            target_id=self.player2.id,
            target_user_name=self.player2.name,
            event1=self.event1,
            event2=self.event2,
            result=result_text
        )
        await msg.delete()
        self.stop()

    def get_result(self, c1: str, c2: str):
        meet_none = "Both characters do not meet, or forget each other."
        if c1 == "none" or c2 == "none":
            return meet_none

        pair = tuple(sorted([c1, c2]))

        if pair == ("a", "a") or pair == ("a", "both"):
            return f"🅰️ {self.event1}"
        if pair == ("b", "b") or pair == ("b", "both"):
            return f"🅱️ {self.event2}"
        if pair == ("both", "both"):
            return f"🅰️ {self.event1}\n\n🅱️ {self.event2}"
        if pair == ("a", "b"):
            return meet_none
        return meet_none

    @button(label="Both", style=discord.ButtonStyle.secondary, emoji="🤝")
    async def both(self, interaction: discord.Interaction, button: Button):
        await self.button_click(interaction, "both", "🤝")

    @button(label="", style=discord.ButtonStyle.secondary, emoji="🅰️")
    async def _a(self, interaction: discord.Interaction, button: Button):
        await self.button_click(interaction, "a", "🅰️")

    @button(label="", style=discord.ButtonStyle.secondary, emoji="🅱️")
    async def _b(self, interaction: discord.Interaction, button: Button):
        await self.button_click(interaction, "b", "🅱️")

    @button(label="None", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def none(self, interaction: discord.Interaction, button: Button):
        await self.button_click(interaction, "none", "🚫")
