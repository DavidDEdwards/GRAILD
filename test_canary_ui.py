"""Headless browser checks for the actual desktop HTML and Canary UI script."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


class CanaryUITests(unittest.TestCase):
    def test_catalogue_matching_information_and_error_states(self):
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        if not edge.exists():
            self.skipTest("Microsoft Edge is required for the browser check")
        folder = Path("build/canary-ui-tests").resolve()
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile("canary_ui.js", folder / "canary_ui.js")
        fixture = r"""<script>
(async () => {
try {
    const filename = 'Rental (Session Edit).mp3';
    const song = {id:'rental',title:'Rental',artist:'Juice WRLD',era:'DRFL',category:'Songs',duration_str:'4:13',page_url:'https://canary.best/song/rental',tracker:{producers:'Seezyn',record_date:'November 10, 2018',alt_names:['Alias']}};
    let confirmations = 0;
    let unavailable = false;
    const calls = [];
    const state = {authenticated:true,has_track:true,durations:[1,2,4,7,11,16],attempt:0,score:0,streak:0,correct_guesses:0,wrong_guesses:0,game_over:false,track_count:1,eligible_track_count:1,recording_eras:['DRFL'],recording_era:'',folder:'Test',difficulty:'Easy',game_mode:'classic',volume:70};
    window.pywebview = {api:{get_catalog:async()=>[{filename,title:'Rental (Session Edit)',format:'MP3',canary:confirmations ? song : null}],get_state:async()=>state,get_canary_era_scan:async()=>({status:'complete',resolved:1,total:1,review:0}),set_library_source:async source=>{state.library_source=source;return {success:true,state};},open_canary_page:async url=>{window.openedCanaryPage=url;return {success:true};}}};
    canaryRequest = async (operation, options={}) => {
        calls.push({operation, options});
        if (unavailable && operation === 'search') throw Error('Canary is offline');
        if (operation === 'eras') return {eras:['DRFL','WOD']};
        if (operation === 'random') return {song};
        if (operation === 'catalog') return {categories:['Songs','Sessions','Masters']};
        if (operation === 'search') return {songs:options.page ? [{...song,title:'Second page'}] : [song],total:21};
        if (operation === 'local') return {confirmed:false,candidates:[{...song,match_reason:'Verify this recording version.'}],message:'Choose a recording explicitly.'};
        if (operation === 'confirm') { confirmations++; return {song,artwork:'',confirmed:true}; }
        if (operation === 'info') return {song,artwork:''};
    };
    renderState(state);
    await loadCanaryManifest();
    document.getElementById('canary-search').value = 'Rental';
    document.getElementById('canary-era').value = 'DRFL';
    document.getElementById('canary-category').value = 'Sessions';
    await searchCanary(0);
    const query = calls.filter(call=>call.operation==='search').at(-1).options;
    if (query.query !== 'Rental' || query.era !== 'DRFL' || query.category !== 'Sessions') throw Error('Search filters');
    if (document.getElementById('canary-next').disabled) throw Error('Next page disabled');
    await searchCanary(1);
    if (!document.getElementById('canary-results').textContent.includes('Second page')) throw Error('Pagination');
    await openLocalCanary(filename);
    if (confirmations !== 0) throw Error('Automatic matching');
    if (!document.getElementById('song-info-content').textContent.includes('Verify this recording')) throw Error('Uncertain match warning');
    await openCanarySong('rental',filename);
    const details = document.getElementById('song-info-content').textContent;
    if (!details.includes('Seezyn') || !details.includes('November 10, 2018') || !details.includes('4:13')) throw Error('Information fields');
    const button = [...document.querySelectorAll('#song-info-content button')].find(item=>item.textContent==='Confirm this recording');
    await confirmLocalCanary(button,filename,'rental');
    if (confirmations !== 1) throw Error('Explicit confirmation');
    if (!document.getElementById('catalog-grid').textContent.includes('Canary: Rental')) throw Error('Confirmed metadata card');
    if (!document.querySelector('#recording-era-select option[value="DRFL"]')) throw Error('Local era filter');
    await refreshCanaryEraList();
    await changeLibrarySource('canary');
    if (document.getElementById('hub-library-source').value !== 'canary' || document.getElementById('account-library-source').value !== 'canary') throw Error('Saved source synchronization');
    await playRandomCanarySong();
    if (window.openedCanaryPage !== 'https://canary.best/song/rental') throw Error('Canary public page launcher');
    if (!document.getElementById('canary-random-status').textContent.includes('Press Play there')) throw Error('Website playback instructions');
    await changeLibrarySource('local');
    await watchAutomaticEraScan();
    if (!document.getElementById('automatic-era-status').textContent.includes('1 / 1 songs have Canary eras')) throw Error('Automatic scan progress');
    unavailable = true;
    await searchCanary(0);
    if (!document.getElementById('canary-browser-status').textContent.includes('offline')) throw Error('Offline message');
    document.body.setAttribute('data-canary-test','passed');
} catch(error) { document.body.setAttribute('data-canary-test','failed: '+error.message); }
})();
</script>"""
        html = Path("index.html").read_text(encoding="utf-8")
        html = re.sub(r'<script src="https://[^"]+"></script>', '', html)
        html = re.sub(r'<link href="https://[^>]+>', '', html)
        preview = folder / "preview.html"
        preview.write_text(html.replace("</body>", fixture + "</body>"), encoding="utf-8")
        result = subprocess.run([str(edge), "--headless", "--disable-gpu", "--no-first-run", "--user-data-dir=" + str(folder / "browser-profile"), "--virtual-time-budget=1000", "--dump-dom", preview.as_uri()], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        (folder / "rendered.html").write_text(result.stdout, encoding="utf-8")
        self.assertIn('data-canary-test="passed"', result.stdout)


if __name__ == "__main__":
    unittest.main()
