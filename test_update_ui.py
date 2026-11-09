from pathlib import Path
import re
import shutil
import subprocess
import unittest


class UpdateUITests(unittest.TestCase):
    def test_notification_progress_later_and_manual_check(self):
        edge=Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        if not edge.exists(): self.skipTest("Microsoft Edge is required")
        folder=Path('build/update-ui-tests').resolve();folder.mkdir(parents=True,exist_ok=True)
        for name in ('canary_ui.js','update_ui.js'): shutil.copyfile(name,folder/name)
        html=Path('index.html').read_text(encoding='utf-8')
        html=re.sub(r'<script src="https://[^"]+"></script>','',html)
        html=re.sub(r'<link href="https://[^>]+>','',html)
        fixture=r"""<script>
(async()=>{try{
 const base={current_version:'0.8.0',repository:'example/graild',channel:'beta',automatic:true,signing_configured:true,status:'available',version:'0.8.1-beta.1',message:'Verified release',notes:'Fix <img src=x onerror=alert(1)>',total:100,downloaded:0};
 let cancelled=0,installs=0;
 window.pywebview={api:{download_update:async()=>({...base,status:'downloading',downloaded:25,success:true}),cancel_update_download:async()=>{cancelled++;return {...base,status:'cancelled'};},check_for_updates:async()=>base,install_update:async()=>{installs++;return {success:false,message:'Isolated test: installation prevented'};},save_update_settings:async()=>({...base,success:true})}};
 renderUpdateState(base);
 if(document.getElementById('update-notification').classList.contains('hidden'))throw Error('Notification missing');
 if(document.getElementById('update-version').textContent!=='0.8.1-beta.1')throw Error('Version display');
 if(document.querySelector('#update-notes img'))throw Error('Release notes interpreted as HTML');
 await updateNow();
 if(document.getElementById('update-progress').value!==25)throw Error('Download progress');
 await cancelUpdateDownload();
 if(cancelled!==1)throw Error('Cancellation');
 renderUpdateState(base);updateLater();
 if(!document.getElementById('update-notification').classList.contains('hidden'))throw Error('Later');
 await manualUpdateCheck();
 if(document.getElementById('update-notification').classList.contains('hidden'))throw Error('Manual update check');
 updateDownloadArmed=true;renderUpdateState({...base,status:'ready'});
 await new Promise(resolve=>setTimeout(resolve,0));
 if(installs!==1)throw Error('Verified install handoff');
 if(document.getElementById('settings-current-version').textContent!=='0.8.0')throw Error('App version');
 document.body.setAttribute('data-update-test','passed');
}catch(error){document.body.setAttribute('data-update-test','failed: '+error.message);}})();
</script>"""
        page=folder/'preview.html';page.write_text(html.replace('</body>',fixture+'</body>'),encoding='utf-8')
        result=subprocess.run([str(edge),'--headless','--disable-gpu','--no-first-run','--user-data-dir='+str(folder/'profile'),'--virtual-time-budget=1000','--dump-dom',page.as_uri()],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
        (folder/'rendered.html').write_text(result.stdout,encoding='utf-8')
        match=re.search(r'data-update-test="([^"]*)"',result.stdout)
        self.assertTrue(match and match[1]=='passed',match[1] if match else result.stderr[-500:])

if __name__=='__main__': unittest.main()
