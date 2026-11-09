"""Exercise tag rendering and owner controls in the actual desktop HTML."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class AccountTagUITests(unittest.TestCase):
    def test_profile_tags_tooltips_and_owner_controls(self):
        edge = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
        if not edge.is_file():
            self.skipTest('Microsoft Edge is required for the browser check')
        fixture = r'''<script>
        (async () => { try {
            const assert = (value, message) => { if (!value) throw Error(message); };
            const logo = document.getElementById('app-logo');
            await logo.decode();
            assert(logo.naturalWidth===256 && logo.alt.includes('logo'),'App logo failed to load');
            const profile = {username:'owner', display_name:'Owner', avatar:'*',
                created_at:'2026-11-02', linked_providers:[], is_creator:true,
                tags:[{id:'beta_tester',name:'Beta Tester',kind:'assigned',description:'Awarded for beta testing.'}]};
            const account = {authenticated:true, profile,
                achievements:{entries:[],unlocked:49,total:50}};
            let assigned = false;
            let customTag = null;
            window.pywebview = {api:{
                get_tag_catalog:async()=>({success:true,entries:[{id:'beta_tester',name:'Beta Tester'},...(customTag?[customTag]:[])]}),
                create_custom_tag:async(name,description)=>{
                    customTag={id:'custom_'+'a'.repeat(24),name,description,kind:'assigned'};
                    return {success:true,message:'Custom tag created',tag:customTag};
                },
                sync_global_tags:async()=>({success:true,player_id:'a'.repeat(64),tags:profile.tags,can_manage_tags:profile.is_creator,message:'Tags synced'}),
                get_global_leaderboard:async()=>({success:true,message:'Global scores',entries:[{rank:1,display_name:'Tester',player_id:'b'.repeat(64),points:100,tags:assigned?[{id:'beta_tester',name:'Beta Tester',description:'Beta testing'}]:[]}]}),
                set_discord_account_tag:async(id,tag,value)=>{
                    assert(id==='456789012345678901' && (tag==='beta_tester'||tag===customTag?.id),'Discord assignment arguments');
                    assigned=value;return {success:true,message:'Discord tag saved'};
                },
                get_tag_accounts:async()=>({success:true,accounts:[{player_id:'b'.repeat(64),provider:'discord',display_name:'<img src=x onerror=alert(1)>',beta_tester:assigned}]}),
                set_account_tag:async(user, tag, value)=>{
                    assert(user==='b'.repeat(64) && (tag==='beta_tester'||tag===customTag?.id),'Assignment arguments');
                    assigned=value;return {success:true,message:value?'Tag assigned':'Tag removed'};
                },
                get_account_state:async()=>account
            }};
            renderAccountState(account);
            switchTab('account');
            await new Promise(resolve=>setTimeout(resolve,0));
            const badge = document.querySelector('#profile-tags .profile-tag');
            assert(badge && badge.textContent.includes('Beta Tester'),'Assigned tag missing');
            const tooltip = document.getElementById(badge.getAttribute('aria-describedby'));
            assert(tooltip.textContent==='Awarded for beta testing.','Tooltip description');
            assert(getComputedStyle(tooltip).display==='none','Tooltip should start hidden');
            badge.focus();
            assert(getComputedStyle(tooltip).display!=='none','Keyboard focus should reveal tooltip');
            assert(!document.querySelector('#tag-account-select img'),'Account name rendered as HTML');
            assert(document.getElementById('top-earner-progress').textContent.includes('49/50'),'Locked progress');
            assert(!document.getElementById('tag-management').classList.contains('hidden'),'Owner controls missing');
            document.getElementById('guess-input').value = 'unfinished guess';
            document.getElementById('btn-game').click();
            assert(!document.getElementById('tab-game').classList.contains('hidden'),'Game navigation missing');
            assert(document.getElementById('btn-game').classList.contains('bg-purple-600'),'Game tab not active');
            assert(!document.getElementById('btn-hub').classList.contains('bg-purple-600'),'Hub should not remain active');
            switchTab('catalog');
            document.getElementById('btn-game').click();
            assert(document.getElementById('guess-input').value==='unfinished guess','Navigation reset current input');
            const gameState = {authenticated:true,has_track:true,game_mode:'classic',difficulty:'Easy',
                durations:[1,2,4,7,11,16],attempt:2,score:0,streak:0,correct_guesses:0,wrong_guesses:0,
                game_over:false,track_count:2,eligible_track_count:2,recording_eras:[],recording_era:'',
                library_source:'local',folder:'Test',volume:70};
            let modeChanges = 0;
            window.pywebview.api.set_game_mode = async mode => {
                modeChanges++; gameState.game_mode=mode; gameState.attempt=0; return gameState;
            };
            renderState(gameState);
            assert(!document.getElementById('game-mode-select'),'Mode picker should not be inside game');
            assert(document.getElementById('nav-mode-classic').getAttribute('aria-checked')==='true','Menu initial mode');
            document.getElementById('game-nav').dispatchEvent(new MouseEvent('mouseenter'));
            assert(!document.getElementById('game-mode-menu').hidden,'Hover should open Game menu');
            await chooseNavGameMode('random');
            assert(document.getElementById('game-mode-menu').hidden,'Selection should close menu');
            assert(document.getElementById('nav-mode-random').getAttribute('aria-checked')==='true','Menu mode change');
            assert(document.getElementById('game-mode-title').textContent==='Random Drop','Mode heading');
            assert(document.getElementById('guess-input').value==='','Old guess not cleared');
            await chooseNavGameMode('random');
            assert(modeChanges===1,'Same mode restarted game');
            await chooseNavGameMode('classic');
            assert(modeChanges===2 && document.getElementById('current-attempt').textContent==='1','Switch back did not reset');
            window.pywebview.api.set_game_mode = async () => { throw Error('Test failure'); };
            await chooseNavGameMode('random');
            assert(document.getElementById('nav-mode-classic').getAttribute('aria-checked')==='true','Failed change left wrong mode selected');
            assert(!document.getElementById('nav-mode-random').disabled,'Failed change left menu disabled');
            document.getElementById('game-menu-toggle').focus();
            document.getElementById('game-menu-toggle').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
            assert(document.activeElement.id==='nav-mode-classic','Keyboard should enter menu');
            document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
            assert(document.getElementById('game-mode-menu').hidden,'Escape should close menu');
            switchTab('account');
            await assignTesterTag(true);
            await new Promise(resolve=>setTimeout(resolve,0));
            assert(assigned,'Assign action');
            assert(document.getElementById('tag-account-select').textContent.includes('Beta Tester'),'Assignment label');
            await assignTesterTag(false);
            await new Promise(resolve=>setTimeout(resolve,0));
            assert(!assigned,'Remove action');
            document.getElementById('tag-discord-id').value='456789012345678901';
            await assignDiscordTesterTag(true);
            assert(assigned,'Assign by Discord action');
            await refreshGlobalLeaderboard();
            let tagButton=document.querySelector('#global-leaderboard button');
            assert(tagButton && tagButton.textContent==='Remove Beta Tester','Owner leaderboard controls missing');
            await assignLeaderboardTag(tagButton,'b'.repeat(64),false);
            assert(!assigned,'Leaderboard removal');
            tagButton=document.querySelector('#global-leaderboard button');
            assert(tagButton.textContent==='Assign Beta Tester','Leaderboard assignment control missing');
            document.getElementById('custom-tag-name').value='Contributor';
            document.getElementById('custom-tag-description').value='Helped improve the game';
            await createCustomTag();
            assert(document.getElementById('tag-definition-select').value===customTag.id,'New custom tag not selected');
            await assignDiscordTesterTag(true);
            await refreshGlobalLeaderboard();
            const selector=document.querySelector('#global-leaderboard select');
            assert(selector.value===customTag.id,'Custom leaderboard tag missing');
            await assignLeaderboardTag(document.querySelector('#global-leaderboard button'),'b'.repeat(64),false,customTag.id);
            renderProfileTags([customTag]);
            assert(document.querySelector('#profile-tags .tag-tooltip').textContent==='Helped improve the game','Custom hover description');
            profile.is_creator=false;
            await refreshGlobalLeaderboard();
            assert(!document.querySelector('#global-leaderboard button'),'Non-owner leaderboard controls visible');
            profile.tags=[{id:'top_earner',name:'Top earner',kind:'earned',description:'Unlocked all 50 achievements.'}];
            account.achievements.unlocked=50;
            renderAccountState(account);
            assert(document.getElementById('tag-management').classList.contains('hidden'),'Non-owner controls visible');
            assert(document.getElementById('top-earner-progress').textContent.includes('unlocked'),'Earned state');
            assert(document.querySelector('#profile-tags .profile-tag').textContent.includes('Top earner'),'Earned badge');
            renderAccountState({authenticated:false});
            assert(!document.getElementById('profile-tags').children.length,'Tags leaked on sign-out');
            assert(!document.getElementById('tag-account-select').children.length,'Accounts leaked on sign-out');
            document.body.setAttribute('data-tag-test','passed');
        } catch(error) { document.body.setAttribute('data-tag-test','failed: '+error.message); }})();
        </script>'''
        with tempfile.TemporaryDirectory(prefix='graild-tag-ui-') as temporary:
            folder = Path(temporary)
            html = Path('index.html').read_text(encoding='utf-8')
            html = html.replace('<head>', '<head><base href="' + Path.cwd().as_uri() + '/">', 1)
            page = folder / 'preview.html'
            page.write_text(html.replace('</body>', fixture + '</body>'), encoding='utf-8')
            result = subprocess.run([
                str(edge), '--headless', '--disable-gpu', '--in-process-gpu', '--no-first-run',
                '--user-data-dir=' + str(folder / 'profile'), '--virtual-time-budget=3000',
                '--dump-dom', page.as_uri()], capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=40)
            match = re.search(r'data-tag-test="([^"]*)"', result.stdout)
            self.assertTrue(match and match[1] == 'passed', match[1] if match else result.stderr[-1000:])


if __name__ == '__main__':
    unittest.main()
