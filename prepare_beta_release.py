"""Build a versioned beta in isolation, then sign it with the existing signer."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from update_security import SemVer,sha256_file
from update_trust import DEFAULT_REPOSITORY,TRUSTED_PUBLIC_KEYS

SOURCES = ['JuiceGuesserMain.py','web_app.py','app_version.py','update_trust.py','update_security.py',
           'platform_support.py','auto_update.py','graild_updater.py','update_health.py','achievements.py','audio_files.py',
           'random_snippets.py','canary_client.py','canary_integration.py','canary_smoke.py',
           'beta_update_smoke.py','standalone_smoke.py','index.html','canary_ui.js','update_ui.js',
           'mac_updater.py','mac_update_security.py','tls_support.py']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    parser.add_argument('--private-key',required=True)
    parser.add_argument('--key-id',default='graild-beta-2026')
    parser.add_argument('--notes',required=True)
    args=parser.parse_args()
    SemVer.parse(args.version)
    if args.key_id not in TRUSTED_PUBLIC_KEYS or not DEFAULT_REPOSITORY:
        parser.error('Configure the publisher repository and public key first.')
    root=Path(__file__).resolve().parent
    output=root/'dist'/'releases'/('v'+args.version)
    if output.exists():
        parser.error('The release output already exists; it was not overwritten. Move it aside before rebuilding.')
    stage=root/'build'/'beta-releases'/('v'+args.version+'-'+uuid.uuid4().hex)
    source=stage/'source';source.mkdir(parents=True)
    for name in SOURCES:shutil.copyfile(root/name,source/name)
    shutil.copytree(root/'assets', source/'assets')
    (source/'app_version.py').write_text('APP_VERSION = '+repr(args.version)+'\nAPP_ID = "GRAILD"\n',encoding='utf-8')
    binary=stage/'bin'
    def build(script,name,extra):
        print('Building',name,'version',args.version,flush=True)
        with open(stage/(name+'.build.log'),'w',encoding='utf-8') as log:
            subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--noconsole','--name',name,
                            '--distpath',str(binary),'--workpath',str(stage/'work'),'--specpath',str(stage/'spec'),
                            *extra,str(source/script)],cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
    build('graild_updater.py','GRAILDUpdater',['--icon',str(source/'assets/graild.ico')])
    extra=['--hidden-import=pygame','--collect-all','pygame','--collect-all','webview','--collect-all','imageio_ffmpeg']
    extra += ['--icon',str(source/'assets/graild.ico')]
    extra += ['--collect-data','certifi']
    for name in ['index.html','canary_ui.js','update_ui.js']:
        extra += ['--add-data',str(source/name)+';.']
    extra += ['--add-data',str(source/'assets')+';assets']
    extra += ['--add-data',str(binary/'GRAILDUpdater.exe')+';.']
    build('JuiceGuesserMain.py','GRAILD',extra)
    output.mkdir(parents=True)
    for name in ['GRAILD.exe','GRAILDUpdater.exe']:shutil.copyfile(binary/name,output/name)
    shutil.copyfile(args.notes,output/'release-notes.md')
    subprocess.run([sys.executable,str(root/'release_tools.py'),'manifest','--private-key',args.private_key,
                    '--key-id',args.key_id,'--repository',DEFAULT_REPOSITORY,'--channel','beta','--version',args.version,
                    '--asset',str(output/'GRAILD.exe'),'--notes',str(output/'release-notes.md'),
                    '--output',str(output/'graild-update.json')],check=True,cwd=root)
    (output/'build-info.json').write_text(json.dumps({'version':args.version,'repository':DEFAULT_REPOSITORY,
        'channel':'beta','sha256':sha256_file(output/'GRAILD.exe'),'source_stage':str(stage),
        'upload':['GRAILD.exe','graild-update.json']},indent=2),encoding='utf-8')
    print('Prepared (NOT published):',output,flush=True)


if __name__=='__main__':main()
