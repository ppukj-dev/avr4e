import discord
import constant


class NumberInputModal(discord.ui.Modal, title="Enter Numbers"):

    party_level = discord.ui.TextInput(
        label="Party Level", placeholder="e.g. 1", required=True,
        style=discord.TextStyle.short
    )
    chara_count = discord.ui.TextInput(
        label="Character Count", placeholder="e.g. 5", required=True,
        style=discord.TextStyle.short
    )
    budget = discord.ui.TextInput(
        label="Budget",
        placeholder="Only fill if you selected 'Other', e.g. 1000",
        required=False,
        style=discord.TextStyle.short,
    )

    def __init__(self, select_value: str):
        super().__init__()
        self.select_value = select_value

    async def on_submit(self, interaction: discord.Interaction):
        party_level = self.party_level.value
        chara_count = self.chara_count.value
        budget = (
            self.budget.value if self.select_value == "other"
            else self.select_value
        )

        response = (
            f"**Values received:**\n- Number 1: `{party_level}`\n"
            f"- Number 2: `{chara_count}`\n- Selection: `{budget}`"
        )

        await interaction.response.edit_message(content=response, view=None)


class SelectionView(discord.ui.View):
    def __init__(self, user: discord.User, generate_callback: callable):
        super().__init__(timeout=60)
        self.user = user
        self.generate_callback = generate_callback
        self.difficulty = None
        self.party_level = None
        self.chara_count = None
        self.monster_role = constant.MONSTER_ROLE_LIST

    @discord.ui.select(
        placeholder="Select Party Level",
        options=[discord.SelectOption(
            label=str(i), value=str(i)) for i in range(1, 15)]
    )
    async def party_level_callback(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if interaction.user != self.user:
            return await interaction.response.send_message(
                "This UI is not for you!", ephemeral=True
            )
        self.party_level = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Select Character Count",
        options=[discord.SelectOption(
            label=str(i), value=str(i)) for i in range(1, 15)]
    )
    async def chara_count_callback(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if interaction.user != self.user:
            return await interaction.response.send_message(
                "This UI is not for you!", ephemeral=True
            )
        self.chara_count = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Select Difficulty",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Easy", value="easy"),
            discord.SelectOption(label="Normal", value="normal"),
            discord.SelectOption(label="Hard", value="hard"),
            discord.SelectOption(label="Custom", value="custom"),
        ]
    )
    async def diff_callback(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if interaction.user != self.user:
            return await interaction.response.send_message(
                "This UI is not for you!", ephemeral=True
            )
        self.difficulty = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="Select Monster Role",
        min_values=1,
        max_values=len(constant.MONSTER_ROLE_LIST),
        options=[
            discord.SelectOption(label=role, value=role, default=True)
            for role in constant.MONSTER_ROLE_LIST
        ]
    )
    async def monster_role_callback(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if interaction.user != self.user:
            return await interaction.response.send_message(
                "This UI is not for you!", ephemeral=True
            )
        self.monster_role = select.values
        await interaction.response.defer()

    @discord.ui.button(
        label="Submit", style=discord.ButtonStyle.green
    )
    async def submit_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user != self.user:
            return await interaction.response.send_message(
                "This UI is not for you!", ephemeral=True
            )

        if (
            self.party_level is None or
            self.chara_count is None or
            self.difficulty is None or
            self.monster_role is None
        ):
            return await interaction.response.edit_message(
                content="No values selected! Closing...",
                view=None,
            )

        await interaction.response.edit_message(
            content="Success. You can now close this message.",
            view=None,
            delete_after=1,
        )

        await self.generate_callback(
            int(self.party_level),
            int(self.chara_count),
            self.difficulty,
            self.monster_role,
            interaction
        )
