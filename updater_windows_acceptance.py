"""Build TEST-ONLY signed Windows fixtures and exercise the real updater EXE."""
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from update_security import canonical, sha256_file, atomic_json


def main():
    project = Path(__file__).resolve().parent
    root = project / 'build' / 'update-acceptance-TEST-ONLY'
    source = root / 'source'; source.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    for name in ('graild_updater.py', 'update_security.py', 'app_version.py'):
        shutil.copyfile(project / name, source / name)
    (source / 'update_trust.py').write_text('TRUSTED_PUBLIC_KEYS = ' + repr({'test-only': public}) + '\n', encoding='utf-8')
    # This ephemeral key is deliberately NOT written to the app's production trust file.
    def build(script, name):
        print('Building test fixture:', name, flush=True)
        with open(root / (name + '.build.log'), 'w', encoding='utf-8') as log:
            subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--noconsole',
                            '--name', name, '--distpath', str(root / 'bin'), '--workpath', str(root / 'work'),
                            '--specpath', str(root / 'spec'), str(script)], cwd=source, check=True, stdout=log, stderr=subprocess.STDOUT)
        return root / 'bin' / (name + '.exe')
    helper = build(source / 'graild_updater.py', 'GRAILDUpdater-TEST-ONLY')
    fixtures = {}
    for version, bad in [('0.8.0', False), ('0.8.1', False), ('0.8.2', True)]:
        script = source / ('fixture_' + version.replace('.', '_') + '.py')
        script.write_text("import json,sys,time\nfrom pathlib import Path\nVERSION = VERSION_LITERAL\nFAIL = FAIL_LITERAL\nif len(sys.argv) == 3 and sys.argv[1] == '--wait':\n    while not Path(sys.argv[2]).exists(): time.sleep(0.05)\nelif len(sys.argv) == 4 and sys.argv[1] == '--post-update':\n    if FAIL: raise SystemExit(2)\n    (Path(sys.argv[2]) / 'health.json').write_text(json.dumps({'token':sys.argv[3],'version':VERSION}),encoding='utf-8')\n    time.sleep(0.5)\n".replace('VERSION_LITERAL',repr(version)).replace('FAIL_LITERAL',repr(bad)), encoding='utf-8')
        existing = root / 'bin' / ('Fixture-' + version + '.exe')
        fixtures[version] = existing if existing.exists() else build(script, 'Fixture-' + version)
    runtime = root / 'runtime'; runtime.mkdir(exist_ok=True)
    environment = dict(os.environ, LOCALAPPDATA=str(runtime / 'local'), APPDATA=str(runtime / 'roaming'))
    user_file = runtime / 'roaming' / 'JuiceSpot' / 'session.dat'
    user_file.parent.mkdir(parents=True, exist_ok=True)
    user_file.write_bytes(b'preserved-user-authentication')
    results = []
    def prepare(label, version):
        folder = runtime / label; folder.mkdir(exist_ok=True)
        target = folder / 'GRAILD.exe'
        shutil.copyfile(fixtures['0.8.0'], target)
        job = runtime / 'local' / 'GRAILD' / 'updates' / 'jobs' / uuid.uuid4().hex
        job.mkdir(parents=True)
        data = fixtures[version].read_bytes()
        now = datetime.now(timezone.utc)
        manifest = {'schema':1,'app':'GRAILD','repository':'example/graild','channel':'beta','version':version,
                    'tag':'v'+version,'asset':'GRAILD.exe','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                    'issued_at':now.isoformat(),'expires_at':(now+timedelta(days=30)).isoformat(),'notes':'TEST ONLY'}
        envelope = {'manifest':manifest,'key_id':'test-only','signature':base64.b64encode(private.sign(canonical(manifest))).decode()}
        atomic_json(job / 'manifest.json', envelope)
        (job / 'payload.exe').write_bytes(data)
        request = {'target':str(target.resolve()),'parent_pid':0,'old_sha256':sha256_file(target),
                   'repository':'example/graild','channel':'beta','current_version':'0.8.0','health_token':uuid.uuid4().hex+uuid.uuid4().hex}
        return target, job, request
    for label, version, expected in [('success','0.8.1','installed'),('failed-startup','0.8.2','rolled_back'),('tampered','0.8.1','failed')]:
        target, job, request = prepare(label, version)
        marker = target.parent / 'close-parent'
        if marker.exists(): marker.unlink()
        parent = subprocess.Popen([str(target),'--wait',str(marker)],env=environment)
        request['parent_pid'] = parent.pid
        atomic_json(job / 'request.json', request)
        if label == 'tampered':
            with open(job / 'payload.exe','ab') as output: output.write(b'tampered')
        installer = subprocess.Popen([str(helper),'--job',str(job)],env=environment)
        try:
            deadline=time.monotonic()+45
            while time.monotonic()<deadline and not (job/'ready.json').exists() and not (job/'result.json').exists(): time.sleep(.1)
            assert sha256_file(target)==request['old_sha256'], 'Running executable was modified'
            if label != 'tampered': assert (job/'ready.json').exists(), 'Updater never became ready'
            marker.write_text('exit',encoding='utf-8')
            parent.wait(timeout=20)
            installer.wait(timeout=120)
            result=json.loads((job/'result.json').read_text(encoding='utf-8'))
            assert result['status']==expected, result
            expected_hash=sha256_file(fixtures[version]) if expected=='installed' else request['old_sha256']
            assert sha256_file(target)==expected_hash
            assert user_file.read_bytes()==b'preserved-user-authentication'
            results.append({'case':label,'passed':True,'status':result['status']})
            print('Passed packaged updater case:',label,flush=True)
        finally:
            marker.write_text('exit',encoding='utf-8')
            if parent.poll() is None: parent.wait(timeout=20)
            if installer.poll() is None: installer.wait(timeout=120)
    target, job, request=prepare('interrupted','0.8.1')
    atomic_json(job/'request.json',request)
    backup=target.parent/('.graild-backup-'+job.name+'.exe')
    shutil.copyfile(target,backup)
    shutil.copyfile(fixtures['0.8.1'],target)
    atomic_json(job/'journal.json',{'phase':'installed'})
    subprocess.run([str(helper),'--job',str(job),'--recover'],env=environment,check=True,timeout=45)
    assert sha256_file(target)==request['old_sha256']
    results.append({'case':'interrupted installation recovery','passed':True})
    report={'passed':True,'production_trust_modified':False,'checks':results}
    (root/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
