import datetime
import json

import aiohttp
import discord
from discord.ext import commands
from lxml import etree

blacklist = []

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


class CodeBlock:
    missing_error = "Missing code block. Please use the following markdown\n\\`\\`\\`language\ncode here\n\\`\\`\\`"

    def __init__(self, argument):
        try:
            block, code = argument.split("\n", 1)
        except ValueError:
            raise commands.BadArgument(self.missing_error)

        if not block.startswith("```") and not code.endswith("```"):
            raise commands.BadArgument(self.missing_error)

        language = block[3:]
        self.command = self.get_command_from_language(language.lower())
        self.source = code.rstrip("`").replace("```", "")

    def get_command_from_language(self, language):
        cmds = {
            "cpp": "g++ -std=c++1z -O2 -Wall -Wextra -pedantic -pthread main.cpp -lstdc++fs && ./a.out",
            "c": "mv main.cpp main.c && gcc -std=c11 -O2 -Wall -Wextra -pedantic main.c && ./a.out",
            "py": "python3 main.cpp",
            "python": "python3 main.cpp",
            "haskell": "runhaskell main.cpp",
        }

        cpp = cmds["cpp"]
        for alias in ("cc", "h", "c++", "h++", "hpp"):
            cmds[alias] = cpp
        try:
            return cmds[language]
        except KeyError as e:
            if language:
                fmt = f"Unknown language to compile for: {language}"
            else:
                fmt = "Could not find a language to compile with."
            raise commands.BadArgument(fmt) from e


@bot.command()
async def run(ctx, *, code: CodeBlock):
    """Compiles code via Coliru.
    You have to pass in a code block with the language syntax
    either set to one of these:
    - cpp
    - c
    - python
    - py
    - haskell
    Anything else isn't supported. The C++ compiler uses g++ -std=c++14.
    The python support is now 3.5.2.
    Please don't spam this for Stacked's sake.
    """
    payload = {"cmd": code.command, "src": code.source}

    data = json.dumps(payload)

    async with ctx.typing():
        async with bot.session.post(
            "http://coliru.stacked-crooked.com/compile", data=data
        ) as resp:
            if resp.status != 200:
                await ctx.send("Coliru did not respond in time.")
                return

            output = await resp.text(encoding="utf-8")

            if len(output) < 1992:
                await ctx.send(f"```\n{output}\n```")
                return

            # output is too big so post it in gist
            async with bot.session.post(
                "http://coliru.stacked-crooked.com/share", data=data
            ) as r:
                if r.status != 200:
                    await ctx.send("Could not create coliru shared link")
                else:
                    shared_id = await r.text()
                    await ctx.send(
                        f"Output too big. Coliru link: http://coliru.stacked-crooked.com/a/{shared_id}"
                    )


@bot.command()
async def cpp(ctx, *, query: str):
    """Search something on cppreference"""

    url = "http://en.cppreference.com/w/cpp/index.php"
    params = {"title": "Special:Search", "search": query}

    async with bot.session.get(url, params=params) as resp:
        if resp.status != 200:
            return await ctx.send(
                f"An error occurred (status code: {resp.status}). Retry later."
            )

        if resp.url.path != "/w/cpp/index.php":
            return await ctx.send(f"<{resp.url}>")

        e = discord.Embed()
        root = etree.fromstring(await resp.text(), etree.HTMLParser())

        nodes = root.findall(".//div[@class='mw-search-result-heading']/a")

        description = []
        special_pages = []
        for node in nodes:
            href = node.attrib["href"]
            if not href.startswith("/w/cpp"):
                continue

            if href.startswith(("/w/cpp/language", "/w/cpp/concept")):
                # special page
                special_pages.append(f"[{node.text}](http://en.cppreference.com{href})")
            else:
                description.append(f"[`{node.text}`](http://en.cppreference.com{href})")

        if len(special_pages) > 0:
            e.add_field(
                name="Language Results", value="\n".join(special_pages), inline=False
            )
            if len(description):
                e.add_field(
                    name="Library Results",
                    value="\n".join(description[:10]),
                    inline=False,
                )
        else:
            if not len(description):
                return await ctx.send("No results found.")

            e.title = "Search Results"
            e.description = "\n".join(description[:15])

        e.add_field(
            name="See More",
            value=f"[`{discord.utils.escape_markdown(query)}` results]({resp.url})",
        )
        await ctx.send(embed=e)


@bot.event
async def on_raw_reaction_add(payload):
    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel(payload.channel_id)
    msg = await channel.fetch_message(payload.message_id)
    member = guild.get_member(payload.user_id)
    if str(payload.emoji) == "❌" and member.id != bot.user.id:
        if (
            channel.name.startswith("discussion-")
            and msg.author == bot.user
            and msg.embeds[0].description == "React with :x: to close the channel"
        ):
            await channel.delete()
    if str(payload.emoji) != "➡️":
        return
    if payload.user_id in blacklist:
        return await channel.send("You were blacklisted for being bad >:(")
    print(str(payload.emoji))
    old = discord.utils.get(guild.channels, name=f"discussion-{payload.message_id}")
    print(old)
    if old is None:
        categorys = guild.by_category()
        category = None
        for i in categorys:
            if i[0] is None:
                continue
            if i[0].name == "threads":
                category = i[0]
        if category is None:
            category = await guild.create_category("threads")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True),
            member: discord.PermissionOverwrite(send_messages=True),
            member: discord.PermissionOverwrite(read_messages=True),
            msg.author: discord.PermissionOverwrite(send_messages=True),
            msg.author: discord.PermissionOverwrite(read_messages=True),
        }
        created_channel = await guild.create_text_channel(
            f"discussion-{payload.message_id}", overwrites=overwrites, category=category
        )
        embed = discord.Embed(
            title=msg.content,
            url=f"https://discordapp.com/channels/{guild.id}/{channel.id}/{msg.id}",
            description="React with :x: to close the channel",
            timestamp=datetime.datetime.utcnow(),
        )
        embed.set_footer(text=f"origanal message by {msg.author}")
        #     embed.add_field(name = "origanal message",value = msg.content)
        close = await created_channel.send(embed=embed)
        await created_channel.send(
            msg.author.mention + " " + member.mention, delete_after=1
        )
        await close.add_reaction("\U0000274c")

    else:
        await discord.utils.get(
            guild.channels, name=f"discussion-{payload.message_id}"
        ).set_permissions(member, read_messages=True, send_messages=True)
        channel = discord.utils.get(
            guild.channels, name=f"discussion-{payload.message_id}"
        )
        print(channel)
        await channel.send(
            f"{member.mention} has been added to the chat", delete_after=1
        )


@bot.event
async def on_raw_reaction_remove(payload):
    guild = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id)
    channel2 = discord.utils.get(
        guild.channels, name=f"discussion-{payload.message_id}"
    )
    if channel2 is not None:
        await channel2.send(f"{member.mention} has left the channel")
        await channel2.set_permissions(member, read_messages=False, send_messages=False)


@bot.command(help="add a user to your thread, can only be used in threads duh")
async def add_user(ctx, member: discord.Member):
    if ctx.channel.name.startswith("discussion-"):
        await ctx.channel.set_permissions(
            member, read_messages=True, send_messages=True
        )
        await ctx.send("I have added " + member.mention + " to this chat.")


@bot.event
async def on_message(message):
    if message.author.bot and message.webhook_id is None:
        return

    ctx = await bot.get_context(message)
    await ctx.invoke(members, sub="teacher", roles=ctx.message.content[18:])

    if message.channel.name.startswith("discussion-"):
        for i in message.mentions:
            await message.channel.set_permissions(
                i, read_messages=True, send_messages=True
            )
            await message.channel.send("I have added " + i.mention + " to the chat")
    await bot.process_commands(message)


@bot.command(usage="<subcommand> `conditions`")
async def members(ctx, sub, *, roles):
    """Searches for members with certain role conditions
    subcommand of student if you don't wan't to ping them, teacher if you do

    example:
    !members students `( ( @role1 and @role2 ) and not @role3 ) or @role4`
    """
    strings = roles.strip("`")
    lists = strings.split()
    dicts = {}
    for i in lists:
        if not i in ["(", ")", "or", "and", "not"] and not i.startswith("@"):
            await ctx.send("Unrecognized input")
            return
        if i.startswith("@"):
            dicts[str(i[1:])] = 1

    def check(role, author):
        return discord.utils.get(ctx.guild.roles, name=role) in author.roles

    for i in dicts:
        strings = strings.replace(f"@{i}", f"check('{i}',member)")
    out = ""
    for i in ctx.guild.members:
        if eval(strings):
            out += " " + i.mention
        if len(out) > 1950:
            if sub == "student":

                await ctx.send(embed=discord.Embed(description=out))
            elif sub == "teacher" and (
                ctx.message.webhook_id is not None
                or ctx.author.guild_permissions.administrator
                or ctx.author.id == 678401615333556277
            ):
                await ctx.send(out)
            out = ""
    if len(out) != 0:
        if sub == "student":
            await ctx.send(embed=discord.Embed(description=out))
        elif sub == "teacher" and (
            ctx.message.webhook_id is not None
            or ctx.author.guild_permissions.administrator
            or ctx.author.id == 678401615333556277
        ):
            await ctx.send(out)


@bot.event
async def on_ready():
    bot.session = aiohttp.ClientSession(loop=bot.loop)
    print("Logged in as " + bot.user.name)


bot.run("token")
