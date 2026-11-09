"""Standalone GRAIL'D community bot. No desktop imports or privileged intents."""
import asyncio
import logging
import os
from dataclasses import dataclass,  field
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from dotenv import load_dotenv

from graild_api import GraildAPI, DEFAULT_BACKEND, ProfileUnavailable
from github_releases import GitHubReleases, RELEASES_URL, release_date
from http_client import APIError, JSONClient, https_origin

PURPLE = 0x8B5CF6
log = logging.getLogger('graild.bot')


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    scope: str
    guild_id: int | None
    application_id: int | None
    backend: str

    @classmethod
    def from_env(cls):
        token = os.environ.get('DISCORD_BOT_TOKEN', '').strip()
        if not token or token.startswith('replace_'):
            raise ValueError('Set DISCORD_BOT_TOKEN in your environment or local .env file.')
        scope = os.environ.get('DISCORD_COMMAND_SCOPE', 'global').strip().lower()
        if scope not in ('guild', 'global'):
            raise ValueError('DISCORD_COMMAND_SCOPE must be guild or global.')
        def snowflake(name, required=False):
            value = os.environ.get(name, '').strip()
            if not value and not required: return None
            if not value.isascii() or not value.isdigit() or not 1 <= int(value) < 2**64:
                raise ValueError(name + ' must be a valid Discord ID.')
            return int(value)
        guild = snowflake('DISCORD_GUILD_ID')
        app = snowflake('DISCORD_APPLICATION_ID')
        backend = https_origin(os.environ.get('GRAILD_BACKEND_URL', DEFAULT_BACKEND).strip())
        return cls(token, scope, guild, app, backend)


def embed(title, description=''):
    result = discord.Embed(title=title[:256], description=description[:3900], colour=PURPLE)
    result.set_footer(text="GRAIL'D • Juice WRLD song guessing")
    return result


def safe_name(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


class GraildCommands(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name='graild', description="GRAIL'D downloads, updates and public stats")
        self.bot = bot

    @app_commands.command(name='download', description="Get published GRAIL'D beta downloads")
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def download(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        downloads = await self.bot.releases.downloads()
        response = embed("Download GRAIL'D beta", 'Only published app assets are listed. Platform versions may differ.')
        for platform, asset in downloads.items():
            response.add_field(name=platform, value=safe_name(asset['version'])[:80] + '\n[Download](' + asset['url'] + ')', inline=False)
        if not downloads:
            response.description = 'Beta releases exist, but no recognised Windows or macOS app downloads are attached. Source/build-kit ZIPs are not playable apps.'
        response.url = RELEASES_URL
        await interaction.followup.send(embed=response, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='updates', description="Read the latest published GRAIL'D beta release notes")
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def updates(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        release = await self.bot.releases.latest()
        notes = release.get('body') or 'No release notes were published.'
        if not isinstance(notes, str): notes = 'No readable release notes were published.'
        notes = discord.utils.escape_mentions(notes)
        if len(notes) > 3500: notes = notes[:3500] + '\n\n… Read the full notes on GitHub.'
        response = embed("GRAIL'D beta updates", notes)
        response.url = self.bot.releases.page_url(release)
        response.add_field(name='Version', value=safe_name(release['tag_name'])[:200], inline=True)
        response.add_field(name='Published (UTC)', value=release_date(release).strftime('%Y-%m-%d %H:%M UTC'), inline=True)
        await interaction.followup.send(embed=response, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='leaderboard', description="Show the top 10 public global GRAIL'D players")
    @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id)
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        entries = await self.bot.api.leaderboard()
        lines = [f"**{entry['rank']}. {safe_name(entry['display_name'])}** — {entry['points']:,} points\n"
                 f"{entry['correct']:,} correct · {entry['wrong']:,} incorrect" for entry in entries]
        response = embed('Global leaderboard — Top 10', '\n\n'.join(lines) or 'No players have been published to the global leaderboard yet.')
        response.set_footer(text='Public backend totals • cached for up to 60 seconds • scores are reported by game clients')
        await interaction.followup.send(embed=response, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name='profile', description="Check your linked GRAIL'D profile availability")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.api.profile(interaction.user.id)
        except ProfileUnavailable as error:
            await interaction.followup.send(embed=embed('Linked profile', str(error)), ephemeral=True)

    @app_commands.command(name='help', description="Show GRAIL'D bot commands")
    async def help(self, interaction: discord.Interaction):
        response = embed("GRAIL'D commands", '\n'.join([
            '**/graild download** — Published Windows, Intel Mac and Apple Silicon app downloads.',
            '**/graild updates** — Latest published beta version, date and notes.',
            '**/graild leaderboard** — Top 10 players from the public global backend.',
            '**/graild profile** — Private profile availability check; backend integration pending.',
            '**/graild help** — This command list.',
        ]))
        await interaction.response.send_message(embed=response, ephemeral=True)

    async def on_error(self, interaction, error):
        cause = getattr(error, 'original', error)
        if isinstance(cause, app_commands.CommandOnCooldown):
            message = f'Please wait {cause.retry_after:.0f} seconds before trying that command again.'
        elif isinstance(cause, APIError):
            message = str(cause)
        else:
            # Log the class, not raw exceptions/headers/URLs that might contain credentials.
            log.error('Command failed (%s).', type(cause).__name__)
            message = 'The command could not be completed. Please try again later.'
        response = embed('GRAIL\'D — request unavailable', message)
        if interaction.response.is_done():
            await interaction.followup.send(embed=response, ephemeral=True)
        else:
            await interaction.response.send_message(embed=response, ephemeral=True)


class GraildBot(discord.Client):
    def __init__(self, settings):
        intents = discord.Intents.none()
        intents.guilds = True  # Non-privileged; no members, presence or message content.
        super().__init__(intents=intents, application_id=settings.application_id,
                         allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        # Load every public command before the one startup synchronization.
        self.tree.add_command(GraildCommands(self))
        self._commands_synced = False
        self.http_session = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15, connect=5),
            headers={'User-Agent': 'GRAILD-Discord-Bot/0.1', 'Accept': 'application/json'})
        self.releases = GitHubReleases(JSONClient(self.http_session, ttl=300))
        self.api = GraildAPI(JSONClient(self.http_session, ttl=60), self.settings.backend)
        await self.sync_public_commands()

    async def sync_public_commands(self):
        if self._commands_synced:
            return
        if self.settings.scope == 'guild':
            log.info('Legacy guild scope setting overridden: public commands now register globally.')
        try:
            synced = await self.tree.sync()
        except (discord.HTTPException, app_commands.AppCommandError) as error:
            log.error('Global command synchronization failed (%s, HTTP %s, Discord code %s). '
                      'Check application ID, installation scopes and connectivity; restart after fixing.',
                      type(error).__name__, getattr(error, 'status', 'n/a'), getattr(error, 'code', 'n/a'))
            raise RuntimeError('Global command synchronization failed; startup stopped.') from None
        self._commands_synced = True
        names = []
        def collect(command, prefix=''):
            name = f'{prefix} {command.name}'.strip()
            children = getattr(command, 'options', [])
            subcommands = [child for child in children if child.type in (
                discord.AppCommandOptionType.subcommand, discord.AppCommandOptionType.subcommand_group)]
            if subcommands:
                for child in subcommands:
                    collect(child, name)
            else:
                names.append('/' + name)
        for command in synced:
            collect(command)
        log.info('Successfully synchronized %d global command group(s), %d commands: %s',
                 len(synced), len(names), ', '.join(names))
        # Remove only our legacy test-guild slash group, after global sync succeeds.
        # Global commands also serve the test server; unrelated commands are untouched.
        if self.settings.guild_id:
            try:
                guild = discord.Object(id=self.settings.guild_id)
                for command in await self.tree.fetch_commands(guild=guild):
                    if command.name == 'graild' and command.type == discord.AppCommandType.chat_input:
                        await command.delete()
                        log.info('Removed legacy test-server /graild registration; global commands serve this server.')
            except discord.HTTPException as error:
                log.warning('Global sync succeeded, but test-server command cleanup failed '
                            '(%s, HTTP %s, Discord code %s). Cleanup will retry next startup.',
                            type(error).__name__, error.status, error.code)

    async def close(self):
        try:
            if self.http_session is not None:
                await self.http_session.close()
        finally:
            await super().close()


def main():
    load_dotenv(Path(__file__).with_name(".env"), encoding="utf-8-sig")
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    try:
        settings = Settings.from_env()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    bot = GraildBot(settings)
    async def run():
        async with bot:
            await bot.start(settings.token)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except discord.LoginFailure:
        raise SystemExit('Discord rejected DISCORD_BOT_TOKEN. Reset it in the Developer Portal and update your environment.') from None
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    except discord.HTTPException as error:
        raise SystemExit(f'Discord API request failed (HTTP {error.status}, code {error.code}). Check connectivity and installation permissions.') from None


if __name__ == '__main__': main()
