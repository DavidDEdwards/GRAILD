from pathlib import Path
import re
import subprocess
import tempfile
import unittest


FIXTURE = r'''<script>
(async () => { try {
    const assert = (value, message) => { if (!value) throw Error(message); };
    const $ = id => document.getElementById(id);
    assert(typeof GraildUI === 'object', 'Interface extras did not load');
    let state = {authenticated:true,has_track:true,game_mode:'classic',difficulty:'Easy',durations:[1,2,4,7,11,16],
        attempt:0,score:0,streak:0,correct_guesses:0,wrong_guesses:0,game_over:false,track_count:3,eligible_track_count:3,
        recording_eras:['DRFL','WOD'],recording_era:'',library_source:'local',folder:'Test',volume:70,title:''};
    const songs = [
        {filename:'Beta.mp3',title:'Beta',format:'MP3',canary_era:'DRFL',era_status:'checked',canary:null},
        {filename:'Alpha.flac',title:'Alpha',format:'FLAC',canary_era:'',era_status:'needs_review',canary:null},
        {filename:'<img src=x onerror=alert(1)>.mp3',title:'<img src=x onerror=alert(1)>',format:'MP3',canary_era:'',era_status:'pending',canary:null}];
    const records = [{title:'Beta',correct:5,wrong:1},{title:'Alpha',correct:1,wrong:9},{title:'<img src=x onerror=alert(1)>',correct:0,wrong:0}];
    let leaderboard = async () => ({success:false,entries:[],message:'Global leaderboard unavailable.'});
    const account = {authenticated:true,profile:{username:'u',display_name:'Me',avatar:'🎧',created_at:'2026-11-02',linked_providers:[],is_creator:false,tags:[],
        total_correct:1,total_wrong:1,accuracy:50,current_streak:0,best_streak:1,total_points:10,songs_played:1,grails_collected:0},
        achievements:{unlocked:0,total:50,entries:[{id:'a',name:'First',category:'C',description:'D',target:1,progress:0,unlocked:false}]}};
    window.pywebview = {api:{
        get_catalog:async()=>songs, get_song_leaderboard:async()=>records, get_state:async()=>state, get_account_state:async()=>account,
        sync_global_tags:async()=>({success:true,tags:[],player_id:'me',can_manage_tags:false,message:'ok'}),
        get_global_leaderboard:async()=>leaderboard(),
        play_snippet:async()=>({ok:true,duration:2}),
        submit_guess:async guess=>{ state={...state,attempt:state.attempt+1,wrong_guesses:state.wrong_guesses+1}; return {state,message:'Incorrect guess.'}; },
        skip_attempt:async()=>{ state={...state,attempt:state.attempt+1}; return {state,message:''}; }
    }};
    renderAccountState(account);
    renderState(state);
    await refreshLeaderboard();
    await refreshCatalog();
    assert(document.querySelectorAll('#catalog-grid .song-card').length===3,'All songs shown');
    assert(!document.querySelector('#catalog-grid img'),'Song title rendered as HTML');
    $('catalog-search').value='alp'; renderCatalog('all');
    assert(document.querySelectorAll('#catalog-grid .song-card').length===1,'Search');
    clearCatalogFilters();
    document.querySelector('#catalog-status-chips [data-status="review"]').click();
    assert($('catalog-grid').textContent.includes('Alpha') && !$('catalog-grid').textContent.includes('Beta'),'Status filter');
    clearCatalogFilters();
    $('catalog-sort').value='missed'; renderCatalog('all');
    assert(document.querySelector('.song-title').textContent==='Alpha','Most missed sort');
    $('catalog-sort').value='az'; renderCatalog('all');
    setCatalogLayout('list');
    assert($('catalog-grid').classList.contains('is-list'),'List layout');
    sortSongRecords('correct');
    assert(document.querySelector('.record-row .t').textContent==='Beta','Record sort');
    assert($('song-insights').textContent.includes('Most missed') && !$('song-insights').querySelector('img'),'Insights');
    assert($('round-worth').textContent==='Worth 60 pts','Points preview');
    $('guess-input').value='Wrong answer'; await submitGuess();
    assert($('bar-0').dataset.state==='wrong' && $('bar-1').dataset.state==='current','Timeline after wrong guess');
    assert($('round-log').textContent.includes('Wrong answer'),'Round log');
    await skipAttempt();
    assert($('bar-1').dataset.state==='skipped','Timeline after skip');
    state={...state,attempt:0}; renderState(state);
    assert($('round-log').classList.contains('hidden'),'New round clears the log');
    $('guess-input').value='alp'; handleTyping({target:$('guess-input')});
    handleGuessKey(new KeyboardEvent('keydown',{key:'ArrowDown'}));
    handleGuessKey(new KeyboardEvent('keydown',{key:'Enter'}));
    assert($('guess-input').value==='Alpha' && state.attempt===0,'Suggestion picked with keyboard');
    renderState({...state,authenticated:false,has_track:false});
    assert($('game-blocker').textContent.includes('Sign in') && $('game-play-area').classList.contains('hidden'),'Signed-out blocker');
    renderState({...state,has_track:false,track_count:0,error:'No supported audio files were found in this folder.'});
    assert($('game-blocker').textContent.includes('No supported audio'),'Empty-folder blocker');
    renderState(state);
    assert($('game-blocker').classList.contains('hidden') && !$('game-play-area').classList.contains('hidden'),'Blocker clears');
    assert($('feedback-banner').textContent==='','Solved message clears');
    await refreshGlobalLeaderboard();
    assert($('global-leaderboard').textContent.includes("didn't load") && $('global-leaderboard').querySelector('button'),'Failure state');
    leaderboard = async () => { throw Error('offline'); };
    await refreshGlobalLeaderboard();
    assert($('global-status').textContent==='Could not load rankings. Refresh to retry.','Thrown failure');
    const board = ['One','Two','Me','Four'].map((display_name,index)=>({rank:index+1,display_name,points:10-index,tags:[]}));
    leaderboard = async () => ({success:true,entries:board,message:'Scores'});
    await refreshGlobalLeaderboard();
    assert(document.querySelectorAll('#global-podium .podium-col').length===3,'Podium');
    assert(document.querySelector('.board-row.is-me')?.textContent.includes('Me'),'Your row highlighted');
    leaderboard = async () => ({success:true,entries:[],message:'Scores'});
    await refreshGlobalLeaderboard();
    assert($('global-leaderboard').textContent.includes('No scores yet') && $('global-podium').classList.contains('hidden'),'Empty state');
    assert(!$('toast-region').textContent,'No toast before an unlock');
    account.achievements.entries[0].unlocked=true; account.achievements.entries[0].unlocked_at='2026-11-02';
    renderAccountState(account);
    assert($('toast-region').textContent.includes('Trophy unlocked: First'),'Trophy toast');
    switchTab('hub');
    assert(!$('hero-search-input'),'Hub search removed');
    assert(document.querySelector('#space canvas'),'Star background present');
    assert(document.querySelectorAll('#challenge-section .challenge-card').length===4,'Four challenge cards');
    assert(document.querySelectorAll('#game-mode-menu [data-challenge]').length===4,'Challenges in the Game menu');
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',ctrlKey:true}));
    assert($('command-palette').open,'Palette opens');
    $('palette-input').value='beta'; $('palette-input').dispatchEvent(new Event('input'));
    assert($('palette-list').textContent.includes('Beta'),'Palette finds songs');
    $('palette-input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));
    assert(!$('command-palette').open && !$('tab-catalog').classList.contains('hidden') && $('catalog-search').value==='Beta','Palette result opens the song');
    const password = $('signin-password');
    password.value='secret-value';
    password.parentElement.querySelector('.pw-toggle').click();
    assert(password.type==='text' && password.value==='secret-value','Show password');
    $('sign-in-form').addEventListener('submit',event=>event.preventDefault());
    $('sign-in-form').dispatchEvent(new Event('submit',{cancelable:true}));
    assert(password.type==='password','Password hidden again on submit');
    document.body.setAttribute('data-ui-test','passed');
} catch(error) { document.body.setAttribute('data-ui-test','failed: '+error.message); }})();
</script>'''


CHALLENGE_FIXTURE = r'''<script>
(async () => { try {
    const assert = (value, message) => { if (!value) throw Error(message); };
    const $ = id => document.getElementById(id);
    const wait = async (test, message) => { for (let i = 0; i < 100 && !test(); i += 1) await new Promise(r => setTimeout(r, 20)); assert(test(), message); };
    assert(typeof GraildChallenges === 'object', 'Challenge file did not load');
    const fresh = {authenticated:true,has_track:true,game_mode:'classic',difficulty:'Easy',durations:[1,2,4],attempt:0,score:0,streak:0,
        correct_guesses:0,wrong_guesses:0,game_over:false,track_count:3,eligible_track_count:3,recording_eras:[],recording_era:'',
        library_source:'local',folder:'Test',volume:70,title:''};
    let state = {...fresh};
    const saved = [];
    const account = {authenticated:true,profile:{username:'u',display_name:'Me',avatar:'*',created_at:'2026-11-07',linked_providers:[],is_creator:false,tags:[],
        total_correct:0,total_wrong:0,accuracy:0,current_streak:0,best_streak:0,total_points:0,songs_played:0,grails_collected:0},
        achievements:{unlocked:0,total:0,entries:[]}};
    const end = () => ({...state, game_over:true, title:'Song'});
    window.pywebview = {api:{
        get_catalog:async()=>[{filename:'Song.mp3',title:'Song',format:'MP3',canary_era:'',era_status:'pending',canary:null}],
        get_song_leaderboard:async()=>[], get_account_state:async()=>account, get_state:async()=>state,
        get_global_leaderboard:async()=>({success:true,entries:[],message:''}),
        sync_global_tags:async()=>({success:true,tags:[],player_id:'me',can_manage_tags:false,message:'ok'}),
        play_snippet:async()=>({ok:true,duration:1}),
        next_round:async()=>{ state={...state,attempt:0,game_over:false,title:''}; return state; },
        set_game_mode:async mode=>{ state={...state,game_mode:mode}; return state; },
        submit_guess:async guess=>{
            if (guess==='Right') { state={...end(),score:state.score+30}; return {state,success:true,message:'Correct!',cover:''}; }
            state={...state,attempt:state.attempt+1,wrong_guesses:state.wrong_guesses+1};
            if (state.attempt>=3) state=end();
            return {state,message:'Incorrect guess.',success:false};
        },
        skip_attempt:async()=>{ state={...state,attempt:state.attempt+1}; if (state.attempt>=3) state=end(); return {state,message:'',success:false}; },
        get_challenge_bests:async()=>({}),
        save_challenge_result:async(mode,score,songs)=>{ saved.push([mode,score,songs]); return {success:true,new_best:score>0,bests:{[mode]:{best_score:score,best_songs:songs,runs:1}}}; }
    }};
    renderAccountState(account);
    renderState(state);
    await refreshCatalog();
    const guess = async text => { $('guess-input').value = text; await submitGuess(); };

    await GraildChallenges.start('sudden_death');
    assert(!$('challenge-hud').classList.contains('hidden') && $('challenge-name').textContent==='Sudden Death','HUD shows');
    assert($('reroll-btn').disabled && $('difficulty-select').disabled,'Song-swapping controls locked');
    assert($('game-mode-title').textContent==='Sudden Death','Title shows the challenge');
    await guess('Right');
    assert($('challenge-score').textContent==='1 song','Run score counts the song');
    await startNextRound();
    await guess('Nope');
    await wait(() => saved.length===1, 'Wrong guess should end the run');
    assert(JSON.stringify(saved[0])==='["sudden_death",1,1]','Saved result '+JSON.stringify(saved[0]));
    await wait(() => !$('challenge-summary').classList.contains('hidden'), 'Summary shows');
    assert($('challenge-summary').textContent.includes('wrong guess') && $('challenge-summary').textContent.includes('New best'),'Summary text');
    assert($('challenge-hud').classList.contains('hidden'),'HUD hidden after the run');
    assert(!$('cover-container').classList.contains('hidden'),'Answer revealed');
    await startNextRound();
    assert(!$('reroll-btn').disabled && !$('difficulty-select').disabled,'Controls unlocked after the run');
    assert(document.querySelector('[data-best-for="sudden_death"]').textContent==='Best 1 song','Hub card shows best');

    await GraildChallenges.start('three_lives');
    assert($('challenge-summary').classList.contains('hidden'),'Old summary cleared');
    assert(document.querySelectorAll('#challenge-meter .life.is-on').length===3,'Three lives');
    for (let song = 0; song < 3; song += 1) {
        await skipAttempt(); await skipAttempt();
        assert(document.querySelectorAll('#challenge-meter .life.is-on').length===3-song,'Skips are free');
        await skipAttempt();
        if (song < 2) { assert(document.querySelectorAll('#challenge-meter .life.is-on').length===2-song,'Life lost'); await startNextRound(); }
    }
    await wait(() => saved.length===2, 'Out of lives should end the run');
    assert(JSON.stringify(saved[1])==='["three_lives",0,0]' && $('challenge-summary').textContent.includes('Out of lives'),'Lives result');

    await GraildChallenges.start('sprint');
    for (let song = 0; song < 10; song += 1) {
        assert($('challenge-meter').textContent===`Song ${song+1} / 10`,'Sprint counter '+$('challenge-meter').textContent);
        await guess('Right');
        if (song < 9) await startNextRound();
    }
    await wait(() => saved.length===3, 'Sprint should end after ten songs');
    assert(JSON.stringify(saved[2])==='["sprint",300,10]','Sprint result '+JSON.stringify(saved[2]));

    await GraildChallenges.start('time_attack');
    assert(/^1:(30|29)$/.test($('challenge-meter').textContent),'Clock '+$('challenge-meter').textContent);
    await guess('Right');
    await wait(() => state.attempt===0 && !state.game_over, 'Next song loads by itself');
    $('challenge-quit').click();
    await wait(() => saved.length===4, 'End run saves');
    assert(JSON.stringify(saved[3])==='["time_attack",30,1]' && $('challenge-summary').textContent.includes('You ended the run'),'Time Attack result');

    await GraildChallenges.start('sprint');
    await startGameMode('random');
    await wait(() => $('challenge-hud').classList.contains('hidden'), 'Normal mode ends the run');
    assert($('challenge-summary').classList.contains('hidden') && $('game-mode-title').textContent==='Random Drop','Back to Random Drop');
    document.body.setAttribute('data-ui-test','passed');
} catch(error) { document.body.setAttribute('data-ui-test','failed: '+error.message); }})();
</script>'''


class UIFeatureTests(unittest.TestCase):
    def run_page(self, html, folder, budget=4000):
        edge = Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
        page = folder / 'preview.html'
        page.write_text(html, encoding='utf-8')
        return subprocess.run([
            str(edge), '--headless', '--disable-gpu', '--in-process-gpu', '--no-first-run',
            '--user-data-dir=' + str(folder / 'profile'), '--virtual-time-budget=' + str(budget),
            '--dump-dom', page.as_uri()], capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=40)

    def test_interface_features(self):
        if not Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe').is_file():
            self.skipTest('Microsoft Edge is required for the browser check')
        with tempfile.TemporaryDirectory(prefix='graild-ui-features-') as temporary:
            html = Path('index.html').read_text(encoding='utf-8')
            html = html.replace('<head>', '<head><base href="' + Path.cwd().as_uri() + '/">', 1)
            result = self.run_page(html.replace('</body>', FIXTURE + '</body>'), Path(temporary))
            match = re.search(r'data-ui-test="([^"]*)"', result.stdout)
            self.assertTrue(match and match[1] == 'passed', match[1] if match else result.stderr[-1000:])

    def test_challenge_runs(self):
        if not Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe').is_file():
            self.skipTest('Microsoft Edge is required for the browser check')
        with tempfile.TemporaryDirectory(prefix='graild-ui-features-') as temporary:
            html = Path('index.html').read_text(encoding='utf-8')
            html = html.replace('<head>', '<head><base href="' + Path.cwd().as_uri() + '/">', 1)
            result = self.run_page(html.replace('</body>', CHALLENGE_FIXTURE + '</body>'), Path(temporary), budget=15000)
            match = re.search(r'data-ui-test="([^"]*)"', result.stdout)
            self.assertTrue(match and match[1] == 'passed', match[1] if match else result.stderr[-1000:])

    def test_game_still_works_if_extras_fail_to_load(self):
        if not Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe').is_file():
            self.skipTest('Microsoft Edge is required for the browser check')
        fixture = r'''<script>(async()=>{try{
            if (window.GraildUI) throw Error('Extras should be absent');
            const state={authenticated:true,has_track:true,game_mode:'classic',difficulty:'Easy',durations:[1,2,4],attempt:0,score:0,streak:0,correct_guesses:0,wrong_guesses:0,game_over:false,track_count:1,eligible_track_count:1,recording_eras:[],recording_era:'',library_source:'local',folder:'Test',volume:70};
            window.pywebview={api:{get_catalog:async()=>[{filename:'A.mp3',title:'A',format:'MP3'}],get_song_leaderboard:async()=>[{title:'A',correct:0,wrong:0}],get_account_state:async()=>({authenticated:false}),submit_guess:async()=>({state:{...state,attempt:1},message:'Incorrect guess.'})}};
            renderState(state); await refreshCatalog(); await refreshLeaderboard(); switchTab('game');
            document.getElementById('guess-input').value='x'; await submitGuess();
            if(document.getElementById('feedback-banner').textContent!=='Incorrect guess.') throw Error('Guess flow');
            document.body.setAttribute('data-ui-test','passed');
        }catch(error){document.body.setAttribute('data-ui-test','failed: '+error.message);}})();</script>'''
        with tempfile.TemporaryDirectory(prefix='graild-ui-features-') as temporary:
            html = Path('index.html').read_text(encoding='utf-8')
            html = html.replace('<script src="assets/graild-ui.js"></script>', '')
            html = html.replace('<script src="assets/graild-challenges.js"></script>', '')
            html = html.replace('<head>', '<head><base href="' + Path.cwd().as_uri() + '/">', 1)
            result = self.run_page(html.replace('</body>', fixture + '</body>'), Path(temporary))
            match = re.search(r'data-ui-test="([^"]*)"', result.stdout)
            self.assertTrue(match and match[1] == 'passed', match[1] if match else result.stderr[-1000:])


if __name__ == '__main__':
    unittest.main()
