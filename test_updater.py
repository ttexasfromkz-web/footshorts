import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import zipfile
import updater
import update_helper


def make_root(root):
    root=Path(root)
    (root/'version.json').write_text(json.dumps({'version':'1.5.0','repository':updater.REPOSITORY}))
    (root/'app.py').write_text("print('old app')\n")
    (root/'requirements.txt').write_text('numpy>=1.24\n')
    for directory in ('output','music','.venv'):
        (root/directory).mkdir();(root/directory/'keep.txt').write_text('user data')
    (root/'ui_state.json').write_text('{"project":"preserve me"}')
    return root


def make_stage(root,version='1.5.1',extra=None,app="print('new app')\n"):
    root=Path(root);stage=root/'.updates/staging/test';stage.mkdir(parents=True)
    files={'app.py':app,'updater.py':'# fixture updater\n','update_helper.py':'# fixture helper\n',
           'version.json':json.dumps({'version':version,'repository':updater.REPOSITORY}),
           'requirements.txt':'numpy>=1.24\n',**(extra or {})}
    package=stage/'payload.zip'
    with zipfile.ZipFile(package,'w') as z:
        for name,data in files.items():z.writestr(name,data)
    manifest=dict(version=version,repository=updater.REPOSITORY,asset_name=updater.ASSET,
        sha256=updater.sha256(package),files={name:hashlib.sha256(data.encode()).hexdigest() for name,data in files.items()})
    (stage/'update.json').write_text(json.dumps(manifest))
    return stage,manifest

class Dummy:
    pid=123456
    def __init__(self):self.alive=True
    def poll(self):return None if self.alive else 1
    def terminate(self):self.alive=False
    def wait(self,timeout=None):return 1

class UpdaterTests(unittest.TestCase):
    def test_semantic_version_order(self):
        self.assertGreater(updater.version_tuple('1.10.0'),updater.version_tuple('1.9.9'))
        with self.assertRaises(ValueError):updater.version_tuple('v1.5.0;command')
    def test_release_url_locked_to_repo(self):
        updater.release_url('https://github.com/'+updater.REPOSITORY+'/releases/download/v1.5.1/update.json','v1.5.1')
        for url in ['https://evil.test/update.zip','http://github.com/'+updater.REPOSITORY+'/releases/download/v1.5.1/x',
                    'https://github.com/another/repo/releases/download/v1.5.1/x']:
            with self.assertRaises(ValueError):updater.release_url(url,'v1.5.1')
    def test_checksum(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root)
            self.assertTrue(updater.validate_archive(stage/'payload.zip',m))
            (stage/'payload.zip').write_bytes(b'broken')
            with self.assertRaises(ValueError):updater.validate_archive(stage/'payload.zip',m)
    def test_protected_data_and_traversal_rejected(self):
        for name in ['../app.py','output/result.mp4','music/custom.wav','.venv/python.exe','ui_state.json']:
            with tempfile.TemporaryDirectory() as d:
                root=make_root(d);stage,m=make_stage(root,extra={name:'attack'})
                with self.assertRaises(ValueError):updater.validate_archive(stage/'payload.zip',m)
    def test_success_preserves_data(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root,extra={'new_module.py':'VALUE=1\n'})
            update_helper.apply_update(root,stage,sys.executable,starter=lambda *a:Dummy(),checker=lambda *a:None,environment=lambda *a:sys.executable)
            self.assertEqual(updater.local_version(root),'1.5.1')
            for folder in ('output','music','.venv'):self.assertEqual((root/folder/'keep.txt').read_text(),'user data')
            self.assertIn('preserve me',(root/'ui_state.json').read_text())
            self.assertTrue((root/'new_module.py').is_file())
    def test_health_failure_rolls_back_all_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root,extra={'new_module.py':'VALUE=1\n'})
            old=(root/'app.py').read_bytes()
            def fail(*a):raise RuntimeError('new app failed')
            with self.assertRaises(RuntimeError):
                update_helper.apply_update(root,stage,sys.executable,starter=lambda *a:Dummy(),checker=fail,environment=lambda *a:sys.executable)
            self.assertEqual(updater.local_version(root),'1.5.0');self.assertEqual((root/'app.py').read_bytes(),old)
            self.assertFalse((root/'new_module.py').exists());self.assertTrue((root/'.updates/failed.json').is_file())
    def test_dependency_failure_does_not_replace_working_code(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root)
            def fail(*a):raise RuntimeError('pip failed')
            with self.assertRaises(RuntimeError):update_helper.apply_update(root,stage,sys.executable,environment=fail)
            self.assertEqual(updater.local_version(root),'1.5.0')
            self.assertEqual((root/'.venv/keep.txt').read_text(),'user data')
    def test_unchanged_requirements_skip_install(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root);(stage/'files').mkdir();(stage/'files/requirements.txt').write_bytes(b'numpy>=1.24\r\n')
            with patch('update_helper.run_logged') as run:
                self.assertEqual(update_helper.candidate_python(root,stage,'working-python'),'working-python')
                run.assert_not_called()
    def test_prepare_from_github_assets(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root);payload=(stage/'payload.zip').read_bytes()
            prefix='https://github.com/'+updater.REPOSITORY+'/releases/download/v1.5.1/'
            release={'tag_name':'v1.5.1','assets':[{'name':'update.json','browser_download_url':prefix+'update.json'},
                     {'name':updater.ASSET,'browser_download_url':prefix+updater.ASSET,'size':len(payload),
                      'digest':'sha256:'+m['sha256']}]}
            def fetch(url,limit):
                if url==updater.API:return json.dumps(release).encode()
                if url.endswith('update.json'):return json.dumps(m).encode()
                return payload
            with patch.dict(os.environ,{'FOOTSHORTS_SKIP_UPDATE':'0'}),patch('updater.fetch',side_effect=fetch):
                prepared=updater.prepare_update(root,log=lambda _:None)
            self.assertTrue((Path(prepared)/'update.json').is_file())
    def test_missing_release_is_normal(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d)
            with patch.dict(os.environ,{'FOOTSHORTS_SKIP_UPDATE':'0'}),patch('updater.fetch',side_effect=HTTPError(updater.API,404,'no release',None,None)):
                self.assertIsNone(updater.prepare_update(root,log=lambda _:None))
    def test_real_child_health_handshake(self):
        # Real Python child verifies the restart handshake without a GUI or network.
        app="""import json,os,time
from pathlib import Path
root=Path(__file__).parent
token=os.environ['FOOTSHORTS_UPDATE_HEALTH_TOKEN']
(root/'.updates'/('health-'+token+'.json')).write_text(json.dumps({'version':'1.5.1','pid':os.getpid()}))
time.sleep(1)
"""
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);stage,m=make_stage(root,app=app)
            children=[]
            def starter(*args):
                child=update_helper.start_app(*args);children.append(child);return child
            try:
                self.assertTrue(update_helper.apply_update(root,stage,sys.executable,starter=starter,environment=lambda *a:sys.executable))
                self.assertEqual(updater.local_version(root),'1.5.1')
            finally:
                for child in children:child.wait(timeout=5)

    def test_health_marker_uses_venv_redirector_pid_for_older_helpers(self):
        with patch('updater.os.getpid',return_value=222),patch('updater.os.getppid',return_value=111),patch('updater.sys.executable','/venv/Scripts/python.exe'),patch('updater.process_image',side_effect=lambda pid:'/base/python.exe' if pid==222 else '/venv/Scripts/python.exe'):
            self.assertEqual(updater.health_process_id(),111)
        with patch('updater.os.getpid',return_value=222),patch('updater.sys.executable','/base/python.exe'),patch('updater.process_image',return_value='/base/python.exe'):
            self.assertEqual(updater.health_process_id(),222)

    def test_new_helper_accepts_live_child_behind_redirector(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);(root/'.updates').mkdir()
            token='a'*32;health=root/'.updates'/('health-'+token+'.json')
            updater.atomic_json(health,{'version':'1.5.1','pid':123456,'app_pid':987654})
            with patch('updater.process_alive',return_value=True) as alive:
                update_helper.health_check(root,Dummy(),'1.5.1',token,timeout=.5)
            alive.assert_called_once_with(987654);self.assertFalse(health.exists())

    def test_wrong_health_version_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d);(root/'.updates').mkdir()
            token='b'*32;health=root/'.updates'/('health-'+token+'.json')
            updater.atomic_json(health,{'version':'1.0.0','pid':123456})
            with patch('updater.process_alive',return_value=True):
                with self.assertRaisesRegex(RuntimeError,'1.0.0'):
                    update_helper.health_check(root,Dummy(),'1.5.1',token,timeout=.01)
            self.assertFalse(health.exists())

    def test_real_venv_update_survives_legacy_health_check_and_reopen(self):
        # Exercise the Windows venv redirector used by the actual installed app.
        with tempfile.TemporaryDirectory() as d:
            root=make_root(d)
            env=root/'.updates/test-venv'
            subprocess.run([sys.executable,'-m','venv','--without-pip',str(env)],check=True,
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            new_app="import time,updater\nfrom pathlib import Path\nupdater.mark_healthy(Path(__file__).parent)\ntime.sleep(3)\n"
            stage,m=make_stage(root,app=new_app,extra={'updater.py':Path(updater.__file__).read_text(encoding='utf-8')})
            children=[];observations=[]
            def starter(*args):
                child=update_helper.start_app(*args);children.append(child);return child
            def legacy_checker(root,process,version,token):
                health=root/'.updates'/('health-'+token+'.json')
                try:
                    until=time.monotonic()+10
                    while time.monotonic()<until:
                        if process.poll() is not None:raise RuntimeError('venv child exited before confirmation')
                        if health.is_file():
                            data=json.loads(health.read_text())
                            if data.get('version')==version and data.get('pid')==process.pid:
                                observations.append(data);return
                        time.sleep(.05)
                    raise RuntimeError('legacy updater rejected startup')
                finally:health.unlink(missing_ok=True)
            try:
                self.assertTrue(update_helper.apply_update(root,stage,str(python),starter=starter,
                    checker=legacy_checker,environment=lambda *a:str(python)))
                print('Windows venv health:',observations,flush=True)
                for child in children:child.wait(timeout=10)
                self.assertEqual(updater.local_version(root),'1.5.1')
                # Closing and starting the installed app again must keep the same version.
                reopened=update_helper.start_app(root,str(python));children.append(reopened)
                self.assertEqual(reopened.wait(timeout=10),0)
                self.assertEqual(updater.local_version(root),'1.5.1')
                self.assertFalse((root/'.updates/failed.json').exists())
                for folder in ('output','music','.venv'):
                    self.assertEqual((root/folder/'keep.txt').read_text(),'user data')
            finally:
                for child in children:
                    if child.poll() is None:child.terminate();child.wait(timeout=5)

    def test_single_instance_lock(self):
        with tempfile.TemporaryDirectory() as d:
            lock=Path(d)/'lock'
            self.assertTrue(updater.acquire_lock(lock));self.assertFalse(updater.acquire_lock(lock))
            updater.release_lock(lock);self.assertFalse(lock.exists())

if __name__=='__main__':unittest.main()
