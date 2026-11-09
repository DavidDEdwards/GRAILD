"""Validate real signed beta builds in fresh per-user test installations."""
import argparse
import base64
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from publisher_keys import load_key,restrict_permissions
from update_security import atomic_json,canonical,sha256_file,verify_manifest,strict_json
from update_trust import DEFAULT_REPOSITORY,TRUSTED_PUBLIC_KEYS


def clone_profile(destination):
    original=Path(os.environ['APPDATA'])/'JuiceSpot'
    destination.mkdir(parents=True)
    if not (original/'session.dat').is_file() or not (original/'accounts.sqlite3').is_file():
        raise RuntimeError('No saved profile/session is available; sign into the existing app before validating login persistence.')
    for path in original.iterdir():
        if not path.is_file() or path.name.endswith(('-wal','-shm','.tmp')):continue
        target=destination/path.name
        if path.suffix=='.sqlite3':
            incoming=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
            outgoing=sqlite3.connect(target)
            try:incoming.backup(outgoing)
            finally:outgoing.close();incoming.close()
        else:shutil.copyfile(path,target)


def wait_for(path,seconds=180,process=None):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if path.is_file():return json.loads(path.read_text(encoding='utf-8'))
        error_file=path.parent/'diagnostic-error.json'
        if error_file.exists():raise RuntimeError(json.loads(error_file.read_text(encoding='utf-8'))['error'])
        if process is not None and process.poll() is not None:
            raise RuntimeError('The isolated app exited before writing its test report.')
        time.sleep(.2)
    raise RuntimeError('Timed out waiting for '+path.name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-key',required=True)
    args=parser.parse_args()
    project=Path(__file__).resolve().parent
    first=project/'dist/releases/v0.8.0/GRAILD.exe'
    second=project/'dist/releases/v0.8.1/GRAILD.exe'
    manifest=project/'dist/releases/v0.8.1/graild-update.json'
    for file in (first,second,manifest):
        if not file.is_file():raise RuntimeError('Prepare both release builds before testing.')
    verify_manifest(strict_json(manifest.read_bytes()),TRUSTED_PUBLIC_KEYS,DEFAULT_REPOSITORY,'beta','0.8.0')
    original_hashes={str(path):sha256_file(path) for path in (first,second)}
    base=Path(os.environ['LOCALAPPDATA'])/'GRAILD-BetaValidation'
    base.mkdir(exist_ok=True);restrict_permissions(base)
    results=[]
    for failure in (False,True):
        root=base/uuid.uuid4().hex;root.mkdir();restrict_permissions(root)
        nonce=uuid.uuid4().hex
        (root/'ISOLATED_TEST_ONLY').write_text(nonce,encoding='utf-8')
        install=root/'install';install.mkdir()
        target=install/'GRAILD.exe'
        if target.exists():raise RuntimeError('Refusing to overwrite an existing test installation.')
        shutil.copyfile(first,target)
        clone_profile(root/'roaming'/'JuiceSpot')
        (root/'local').mkdir()
        selected_manifest=manifest;selected_asset=second
        if failure:
            selected_asset=root/'BadGRAILD.exe';selected_asset.write_bytes(b'MZ - deliberately invalid signed test executable')
            original=json.loads(manifest.read_text(encoding='utf-8'))
            now=datetime.now(timezone.utc)
            data=dict(original['manifest'],version='0.8.2',tag='v0.8.2',asset=selected_asset.name,
                      size=selected_asset.stat().st_size,sha256=sha256_file(selected_asset),issued_at=now.isoformat(),expires_at=(now+timedelta(days=10)).isoformat(),notes='LOCAL FAILURE TEST ONLY - DO NOT PUBLISH')
            private=load_key(args.private_key)
            envelope={'manifest':data,'key_id':original['key_id'],'signature':base64.b64encode(private.sign(canonical(data))).decode()}
            selected_manifest=root/'failure-manifest.json';atomic_json(selected_manifest,envelope)
            del private
        context={'nonce':nonce,'asset':str(selected_asset),'manifest':str(selected_manifest),'expected_failure':failure}
        atomic_json(root/'context.json',context)
        environment=dict(os.environ,APPDATA=str(root/'roaming'),LOCALAPPDATA=str(root/'local'),
                         SDL_AUDIODRIVER='dummy')
        print('Testing isolated '+('rollback' if failure else '0.8.0 -> 0.8.1')+' case.',flush=True)
        process=subprocess.Popen([str(target),'--beta-update-smoke-test',str(root/'context.json')],env=environment)
        initial=wait_for(root/'initial-report.json',process=process)
        if not initial.get('passed'):raise RuntimeError('Initial update check failed.')
        process.wait(timeout=100)
        job=Path(initial['job'])
        outcome=wait_for(job/'result.json')
        expected='rolled_back' if failure else 'installed'
        if outcome['status']!=expected:raise RuntimeError(outcome['message'])
        final=wait_for(root/('rollback-report.json' if failure else 'post-update-report.json'))
        if not final.get('passed'):raise RuntimeError('Persistent data check failed.')
        digest=sha256_file(first if failure else second)
        if sha256_file(target)!=digest:raise RuntimeError('Final installed executable does not match the expected build.')
        result={'case':'rollback' if failure else '0.8.0-to-0.8.1','passed':True,'release_feed':'local simulation of GitHub Releases',
                'notification':initial['notification'],'download_progress':initial['progress_observed'],'signed_download_verified':initial['verified_download'],
                'installer_status':outcome['status'],'new_version':final['version'],
                'persistent_login_retained':final['persistent_login_retained'],'discord_link_retained':final['discord_session_retained'],
                'settings_and_cache_retained':final['settings_and_cache_retained'],'test_directory':str(root)}
        # The test profile contains a copy of real user data. Remove only that
        # protected copy after the hidden test app has closed; keep binaries/logs.
        time.sleep(5)
        copied_profile=(root/'roaming').resolve()
        if root.parent.resolve()!=base.resolve() or not copied_profile.is_relative_to(base.resolve()):
            raise RuntimeError('Unsafe test-profile cleanup path.')
        try:
            shutil.rmtree(copied_profile)
            result['copied_profile_removed']=True
        except OSError:
            result['copied_profile_removed']=False
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k!='test_directory'}),flush=True)
    for filename,digest in original_hashes.items():
        if sha256_file(filename)!=digest:raise RuntimeError('A release artifact changed during testing.')
    report={'passed':True,'repository':DEFAULT_REPOSITORY,'published':False,'original_installations_overwritten':False,'checks':results}
    output=project/'build/beta-validation-results.json';atomic_json(output,report)
    print('Validation report:',output,flush=True)


if __name__=='__main__':main()
