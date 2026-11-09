import asyncio
import os
import unittest
import discord
from unittest.mock import AsyncMock, Mock, patch

from bot import GraildBot, GraildCommands, Settings
from github_releases import GitHubReleases, platform_for, REPOSITORY
from graild_api import GraildAPI, ProfileUnavailable
from http_client import APIError, JSONClient, https_origin


def release(tag='v0.9.0', date='2026-11-01T12:00:00Z', **changes):
    value={'tag_name':tag,'published_at':date,'draft':False,'prerelease':True,'assets':[], 'body':'Notes'}
    value.update(changes);return value


def asset(name,tag='v0.9.0'):
    return {'name':name,'state':'uploaded','size':100,
            'browser_download_url':f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'}


class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_published_app_assets_with_platform_versions(self):
        latest=release(assets=[asset('GRAILD-0.9.0-macOS-arm64.zip'),asset('GRAILD-0.9.0-macOS-arm64-build-kit.zip'),asset('GRAILD-GitHub-Mac-Build.zip')])
        old=release('v0.8.0','2026-10-31T12:00:00Z',assets=[asset('GRAILD.exe','v0.8.0')])
        client=Mock();client.get=AsyncMock(return_value=[old,latest,release('v9.0.0',draft=True)])
        api=GitHubReleases(client)
        result=await api.downloads()
        self.assertEqual(set(result),{'Windows','Apple Silicon Mac'})
        self.assertEqual(result['Windows']['version'],'v0.8.0')
        self.assertEqual((await api.latest())['tag_name'],'v0.9.0')

    async def test_current_published_versionless_mac_packages(self):
        data=release('v0.9.0_MAC',assets=[asset('GRAILD-macOS-arm64.zip','v0.9.0_MAC'),asset('GRAILD-macOS-x86_64.zip','v0.9.0_MAC')])
        client=Mock();client.get=AsyncMock(return_value=[data])
        result=await GitHubReleases(client).downloads()
        self.assertEqual(set(result),{'Apple Silicon Mac','Intel Mac'})
        self.assertEqual(result['Intel Mac']['version'],'v0.9.0_MAC')

    async def test_wrong_origin_and_upload_state_excluded(self):
        bad=asset('GRAILD.exe');bad['browser_download_url']='https://evil.example/GRAILD.exe'
        unfinished=asset('GRAILD-0.9.0-macOS-arm64.zip');unfinished['state']='new'
        client=Mock();client.get=AsyncMock(return_value=[release(assets=[bad,unfinished])])
        self.assertEqual(await GitHubReleases(client).downloads(),{})

    async def test_no_betas_and_bad_payload_fail(self):
        for response in ([],{},[release(prerelease=False)]):
            client=Mock();client.get=AsyncMock(return_value=response)
            with self.assertRaises(APIError):await GitHubReleases(client).latest()

    def test_platform_names(self):
        self.assertEqual(platform_for('GRAILD-0.9.0-macOS-x86_64.zip'),'Intel Mac')
        for value in ['GRAILDUpdater.exe','GRAILD-GitHub-Mac-Build.zip','GRAILD-0.9.0-macOS-arm64-build-kit.zip','Source code.zip']:
            self.assertIsNone(platform_for(value))


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_ten_public_allowlist(self):
        data={'entries':[{'rank':i+1,'display_name':'name','points':12,'correct':2,'wrong':1,'email':'private','token':'secret'} for i in range(15)]}
        client=Mock();client.get=AsyncMock(return_value=data)
        api=GraildAPI(client)
        entries=await api.leaderboard()
        self.assertEqual(len(entries),10)
        self.assertNotIn('email',entries[0]);self.assertNotIn('token',entries[0])
        client.get.assert_awaited_once_with(api.base_url+'/leaderboard')

    async def test_invalid_totals_are_not_invented(self):
        client=Mock();client.get=AsyncMock(return_value={'entries':[{'display_name':'name','rank':1,'points':2}]})
        with self.assertRaises(APIError):await GraildAPI(client).leaderboard()

    async def test_profile_never_guesses_endpoint(self):
        client=Mock();client.get=AsyncMock()
        with self.assertRaises(ProfileUnavailable):await GraildAPI(client).profile(123456789)
        client.get.assert_not_called()


class Response:
    def __init__(self,status=200,data=b'{"ok":true}'):
        self.status=status;self.data=data;self.content=self
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def iter_chunked(self,size):yield self.data


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_and_redirects_disabled(self):
        session=Mock();session.get.return_value=Response()
        api=JSONClient(session)
        self.assertEqual(await api.get('https://example.test'),{'ok':True})
        await api.get('https://example.test')
        session.get.assert_called_once_with('https://example.test',allow_redirects=False)

    async def test_errors_and_limits(self):
        for response in [Response(429),Response(503),Response(302),Response(data=b'invalid'),Response(data=b'x'*100)]:
            session=Mock();session.get.return_value=response
            with self.assertRaises(APIError):await JSONClient(session,max_bytes=50).get('https://example.test')

    async def test_timeout_is_safe(self):
        session=Mock();session.get.side_effect=asyncio.TimeoutError
        with self.assertRaisesRegex(APIError,'timed out'):await JSONClient(session).get('https://example.test')


class ConfigTests(unittest.TestCase):
    def test_defaults_to_global_without_test_server(self):
        with patch.dict(os.environ,{'DISCORD_BOT_TOKEN':'fake-for-unit-test'},clear=True):
            self.assertEqual(Settings.from_env().scope, 'global')

    def test_no_privileged_intents_and_exact_group(self):
        settings=Settings('fake','guild',123,None,'https://example.test')
        bot=GraildBot(settings)
        group=GraildCommands(bot)
        self.assertEqual({c.name for c in group.commands},{'download','updates','leaderboard','profile','help'})
        self.assertFalse(bot.intents.members);self.assertFalse(bot.intents.presences);self.assertFalse(bot.intents.message_content)

    def test_invalid_origins_and_scope(self):
        for value in ['http://example.test','https://user:secret@example.test','https://example.test/path']:
            with self.assertRaises(ValueError):https_origin(value)
        with patch.dict(os.environ,{'DISCORD_BOT_TOKEN':'fake','DISCORD_COMMAND_SCOPE':'invalid'},clear=True):
            with self.assertRaises(ValueError):Settings.from_env()


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_defer_before_backend_and_no_mentions(self):
        sequence=[]
        async def defer(**kwargs):sequence.append('defer')
        async def request():sequence.append('request');return []
        fake=Mock();fake.api.leaderboard=AsyncMock(side_effect=request)
        interaction=Mock();interaction.response.defer=AsyncMock(side_effect=defer);interaction.followup.send=AsyncMock()
        group=GraildCommands(fake)
        await group.leaderboard.callback(group,interaction)
        self.assertEqual(sequence,['defer','request'])
        self.assertFalse(interaction.followup.send.call_args.kwargs['allowed_mentions'].everyone)

    async def test_profile_uses_only_invoker_and_ephemeral(self):
        fake=Mock();fake.api.profile=AsyncMock(side_effect=ProfileUnavailable('Pending'))
        interaction=Mock();interaction.user.id=123;interaction.response.defer=AsyncMock();interaction.followup.send=AsyncMock()
        group=GraildCommands(fake)
        await group.profile.callback(group,interaction)
        fake.api.profile.assert_awaited_once_with(123)
        self.assertTrue(interaction.response.defer.call_args.kwargs['ephemeral'])
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])

    async def test_legacy_guild_setting_syncs_global_and_removes_only_old_group(self):
        settings=Settings('fake','guild',123,None,'https://example.test')
        bot=GraildBot(settings)
        bot.tree.sync=AsyncMock(return_value=[])
        legacy=Mock(name='legacy');legacy.name='graild';legacy.type=discord.AppCommandType.chat_input
        legacy.delete=AsyncMock()
        other=Mock();other.name='other';other.delete=AsyncMock()
        bot.tree.fetch_commands=AsyncMock(return_value=[legacy,other])
        try:
            await bot.setup_hook()
            bot.tree.sync.assert_awaited_once_with()
            self.assertEqual(bot.tree.fetch_commands.call_args.kwargs['guild'].id,123)
            legacy.delete.assert_awaited_once_with()
            other.delete.assert_not_awaited()
            self.assertEqual([c.name for c in bot.tree.get_commands()],['graild'])
            await bot.sync_public_commands()
            bot.tree.sync.assert_awaited_once_with()
        finally:await bot.close()



class GlobalRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_global_scope(self):
        bot=GraildBot(Settings('fake','global',None,None,'https://example.test'))
        bot.tree.sync=AsyncMock(return_value=[])
        try:
            await bot.setup_hook()
            bot.tree.sync.assert_awaited_once_with()
            self.assertEqual([c.name for c in bot.tree.get_commands()],['graild'])
        finally:await bot.close()

    async def test_sync_failure_stops_startup_without_deleting_guild_commands(self):
        bot=GraildBot(Settings('fake','guild',123,None,'https://example.test'))
        bot.tree.sync=AsyncMock(side_effect=discord.Forbidden(
            Mock(status=403,reason='Forbidden'), {'code':50001,'message':'Missing Access'}))
        bot.tree.fetch_commands=AsyncMock()
        try:
            with self.assertRaisesRegex(RuntimeError,'synchronization failed'):
                await bot.setup_hook()
            bot.tree.fetch_commands.assert_not_awaited()
            self.assertFalse(bot._commands_synced)
        finally:await bot.close()

    async def test_commands_loaded_before_sync_and_success_log_lists_subcommands(self):
        bot=GraildBot(Settings('fake','global',None,None,'https://example.test'))
        from types import SimpleNamespace
        group=bot.tree.get_command('graild')
        remote=SimpleNamespace(name='graild', options=[SimpleNamespace(
            name=c.name,type=discord.AppCommandOptionType.subcommand,options=[]) for c in group.commands])
        bot.tree.sync=AsyncMock(return_value=[remote])
        try:
            with self.assertLogs('graild.bot',level='INFO') as logs:
                await bot.setup_hook()
            for command in group.commands:
                self.assertIn('/graild '+command.name, '\n'.join(logs.output))
        finally:await bot.close()


if __name__=='__main__':unittest.main()
