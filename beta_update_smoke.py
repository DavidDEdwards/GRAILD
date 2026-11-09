"""Opt-in isolated beta update diagnostic; never changes a normal installation.

No signing keys are loaded here. Local fixtures must pass the real updater's
compiled publisher signature, repository, version and checksum validation.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit


def write_json(path, value):
    from update_security import atomic_json
    atomic_json(path, value)


def read_context(filename):
    path = Path(filename).resolve()
    data = json.loads(path.read_text(encoding='utf-8'))
    root = path.parent
    if root.parent.name != 'GRAILD-BetaValidation' or not re.fullmatch('[0-9a-f]{32}', root.name):
        raise RuntimeError('This diagnostic requires an isolated beta-validation directory.')
    if (root/'ISOLATED_TEST_ONLY').read_text(encoding='utf-8') != data['nonce']:
        raise RuntimeError('The isolated test marker is missing.')
    expected = root/'install'/'GRAILD.exe'
    import sys
    if Path(sys.executable).resolve() != expected.resolve():
        raise RuntimeError('Diagnostic refused: this is not the isolated test installation.')
    return root,data


def profile_snapshot(directory):
    directory = Path(directory)
    tables = {}
    for filename in ('accounts.sqlite3','canary_api.sqlite3','canary_matches.sqlite3'):
        path=directory/filename
        if not path.exists(): continue
        connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                digest=hashlib.sha256()
                rows=connection.execute('SELECT * FROM "'+table.replace('"','""')+'"').fetchall()
                normalized=[]
                for row in rows:
                    normalized.append(json.dumps([{'bytes':base64.b64encode(v).decode()} if isinstance(v,bytes) else v for v in row],sort_keys=True,ensure_ascii=False))
                for row in sorted(normalized):digest.update(row.encode())
                tables[filename+':'+table]=digest.hexdigest()
        finally:connection.close()
    files={}
    for name in ('session.dat','juicespot_config.json','song_stats.json'):
        path=directory/name
        if path.exists():files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'tables':tables,'files':files}


class LocalReleaseResponse:
    status_code=200
    headers={}
    def __init__(self, content=None, filename=None):self.content=content;self.filename=filename
    def iter_content(self,size):
        if self.filename:
            with open(self.filename,'rb') as file:
                while True:
                    chunk=file.read(size)
                    if not chunk:break
                    time.sleep(.006)
                    yield chunk
        else:yield self.content
    def close(self):pass


class LocalReleaseTransport:
    def __init__(self,context):self.context=context;self.headers={}
    def get(self,url,**kwargs):
        from update_trust import DEFAULT_REPOSITORY
        context=self.context
        manifest=json.loads(Path(context['manifest']).read_text(encoding='utf-8'))['manifest']
        prefix='https://github.com/'+DEFAULT_REPOSITORY+'/releases/download/'+manifest['tag']+'/'
        if url.startswith('https://api.github.com/repos/'+DEFAULT_REPOSITORY+'/releases?'):
            release={'tag_name':manifest['tag'],'draft':False,'prerelease':True,
                     'assets':[{'name':name,'browser_download_url':prefix+name} for name in ('graild-update.json',manifest['asset'])]}
            return LocalReleaseResponse(json.dumps([release]).encode())
        if url==prefix+'graild-update.json':return LocalReleaseResponse(Path(context['manifest']).read_bytes())
        if url==prefix+manifest['asset']:return LocalReleaseResponse(filename=context['asset'])
        raise RuntimeError('Unexpected URL in isolated release-feed simulation.')


def run(filename, post_update=False):
    root,context=read_context(filename)
    os.environ['APPDATA']=str(root/'roaming')
    os.environ['LOCALAPPDATA']=str(root/'local')
    os.environ['SDL_AUDIODRIVER']='dummy'
    os.environ['GRAILD_BETA_TEST_CONTEXT']=str(root/'context.json')
    import webview
    from app_version import APP_VERSION
    from web_app import JuiceSpotApp,resource_path
    from canary_integration import CanaryIntegration
    # Keep this updater-only diagnostic from changing caches or scanning music.
    original_scan=CanaryIntegration.start_era_scan
    original_load=JuiceSpotApp.load_tracks
    CanaryIntegration.start_era_scan=lambda *args,**kwargs:{'status':'idle'}
    def no_music_scan(self):self.tracks=[];self.current_track=None;self.library_error=None
    JuiceSpotApp.load_tracks=no_music_scan
    try:app=JuiceSpotApp()
    finally:
        CanaryIntegration.start_era_scan=original_scan
        JuiceSpotApp.load_tracks=original_load
    app._canary.start=lambda *args,**kwargs:{'status':'failed','message':'Canary network disabled in isolated updater test.'}
    app._updates.session=LocalReleaseTransport(context)
    app._updates.save_settings('DavidDEdwards/GRAILD-Releases','beta',True)
    account=app.get_account_state()
    if not account.get('authenticated'):
        raise RuntimeError('The copied persistent session did not restore; no update test was started.')
    auth={'authenticated':True,'discord_linked':'discord' in account['profile']['linked_providers']}
    profile=Path(os.environ['APPDATA'])/'JuiceSpot'
    baseline_file=root/'baseline.json'
    rollback=(root/'update-started.json').exists() and not post_update
    role='post-update' if post_update else 'rollback' if rollback else 'initial'
    window=webview.create_window('GRAILD isolated beta update validation',resource_path('index.html'),js_api=app,hidden=True)
    app._window=window
    window.events.loaded+=app._on_window_loaded
    def loaded():
        try:
            if role=='initial':
                baseline={'profile':profile_snapshot(profile),'auth':auth}
                write_json(baseline_file,baseline)
                deadline=time.monotonic()+50
                while time.monotonic()<deadline:
                    state=app.get_update_state()
                    if state['status']=='available':break
                    if state['status']=='error':raise RuntimeError(state['message'])
                    time.sleep(.1)
                else:raise RuntimeError('v0.8.1 was not detected in the simulated release feed.')
                window.evaluate_js('renderUpdateState('+json.dumps(state)+')')
                notification=window.evaluate_js("!document.getElementById('update-notification').classList.contains('hidden') && document.getElementById('update-version').textContent === '0.8.1' && document.getElementById('update-notes').textContent.length > 0")
                if context.get('expected_failure'):
                    notification=window.evaluate_js("!document.getElementById('update-notification').classList.contains('hidden')")
                if not notification:raise RuntimeError('Native update notification did not display correctly.')
                write_json(root/'update-started.json',{'started':True})
                window.evaluate_js('updateNow(); true')
                progress=False
                deadline=time.monotonic()+100
                while time.monotonic()<deadline:
                    state=app.get_update_state()
                    if state['status']=='downloading' and state.get('downloaded',0)>0:progress=True
                    if state['status']=='installing':
                        write_json(root/'initial-report.json',{'passed':True,'version':APP_VERSION,'notification':True,'progress_observed':progress,'verified_download':True,'job':str(app._updates.ready_job),'auth':auth})
                        return
                    if state['status']=='error':raise RuntimeError(state['message'])
                    time.sleep(.1)
                raise RuntimeError('The updater did not reach installation.')
            baseline=json.loads(baseline_file.read_text(encoding='utf-8'))
            after=profile_snapshot(profile)
            if after!=baseline['profile']:raise RuntimeError('The copied profile/settings/cache changed during update.')
            if auth!=baseline['auth']:raise RuntimeError('Persistent authentication did not survive update.')
            result={'passed':True,'role':role,'version':APP_VERSION,'discord_session_retained':auth['discord_linked'],
                    'persistent_login_retained':True,'settings_and_cache_retained':True}
            write_json(root/(role+'-report.json'),result)
            # Give the real helper time to observe the native startup health signal.
            threading.Timer(2,window.destroy).start()
        except Exception as error:
            write_json(root/'diagnostic-error.json',{'error':str(error),'role':role,'version':APP_VERSION})
            window.destroy()
    window.events.loaded+=loaded
    watchdog=threading.Timer(150,window.destroy);watchdog.daemon=True;watchdog.start()
    try:webview.start()
    finally:watchdog.cancel()
    return 1 if (root/'diagnostic-error.json').exists() else 0
