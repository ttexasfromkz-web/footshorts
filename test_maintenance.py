import json
import os
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock,patch
import app
import core
from progress import Progress
import retention
import updater


class MaintenanceTests(unittest.TestCase):
    def project(self,base,name='old',age=10,status='ready'):
        folder=Path(base)/'output'/name
        (folder/'source').mkdir(parents=True)
        (folder/'source/project.json').write_text(json.dumps({'kind':'football_project','status':status}))
        (folder/'result.mp4').write_bytes(b'fixture')
        (folder/'result.txt').write_text('fixture')
        old=time.time()-age*86400
        for current,dirs,files in os.walk(folder,topdown=False):
            for n in files:os.utime(Path(current)/n,(old,old))
            os.utime(current,(old,old))
        return folder

    def test_retention_disabled_by_default_and_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.project(d)
            self.assertEqual(retention.load_days(d),0)
            self.assertEqual(retention.cleanup(d,0),([],[]));self.assertTrue(p.exists())
            retention.save_days(d,14);self.assertEqual(retention.load_days(d),14)
            for value in [-1,1,True,'7']:
                with self.assertRaises(ValueError):retention.save_days(d,value)
            Path(d,'preferences.json').write_text('broken')
            self.assertEqual(retention.load_days(d),0)

    def test_cleanup_removes_whole_expired_project_only(self):
        with tempfile.TemporaryDirectory() as d:
            old=self.project(d);fresh=self.project(d,'fresh',age=2)
            unfinished=self.project(d,'rendering',status='rendering')
            active=self.project(d,'active')
            unknown=Path(d,'output/unknown');unknown.mkdir();(unknown/'file').write_text('keep')
            removed,errors=retention.cleanup(d,7,[active])
            self.assertEqual(removed,['old']);self.assertEqual(errors,[])
            self.assertFalse(old.exists())
            for p in [fresh,unfinished,active,unknown]:self.assertTrue(p.exists())

    def test_recently_touched_media_extends_retention(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.project(d)
            os.utime(p/'result.mp4',None)
            self.assertEqual(retention.cleanup(d,7),([],[]));self.assertTrue(p.exists())

    def test_linked_output_is_never_traversed(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as external:
            p=self.project(external)
            try:Path(d,'output').symlink_to(Path(external,'output'),target_is_directory=True)
            except OSError:self.skipTest('symlink permission unavailable')
            self.assertEqual(retention.cleanup(d,7),([],[]));self.assertTrue(p.exists())

    def test_nested_symlink_preserves_project_and_target(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as external:
            p=self.project(d)
            try:(p/'source/link').symlink_to(external,target_is_directory=True)
            except OSError:self.skipTest('symlink permission unavailable')
            old=time.time()-10*86400;os.utime(p/'source',(old,old))
            self.assertEqual(retention.cleanup(d,7),([],[]));self.assertTrue(p.exists());self.assertTrue(Path(external).exists())

    def test_measured_progress_eta_and_no_fake_ticks(self):
        now=[0.];p=Progress(lambda:now[0])
        p.observe('@progress:reset')
        self.assertFalse(p.observe('Жүктелуде: 50.0%'))
        now[0]=10
        state=p.snapshot();self.assertEqual(state['percent'],10)
        self.assertIn('00:10',state['text'])
        now[0]=25;self.assertEqual(p.snapshot()['percent'],10)
        self.assertIn('25 сек',p.snapshot()['detail'])
        p.observe('@progress:analyze:0:OCR')
        p.observe('Есепті оқу: 50/100 кадр')
        self.assertAlmostEqual(p.snapshot()['percent'],30.625)
        p.observe('@progress:render:0.5:2/4');now[0]=35
        self.assertIn('00:10',p.snapshot()['text'])
        p.finish(True);self.assertEqual(p.snapshot()['percent'],100)

    def test_ffmpeg_progress_reads_microseconds_and_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d,'progress.txt')
            p.write_bytes(b'frame=1\nout_time_us=2500000\nprogress=continue\n')
            self.assertEqual(core.read_progress(p,10),.25)
            p.write_bytes(b'out_time_us=-20\n')
            self.assertEqual(core.read_progress(p,10),0)
            p.write_bytes(b'out_time_us=20000000\n')
            self.assertEqual(core.read_progress(p,10),.999)
            p.write_bytes(b'out_time_us=N/A\n')
            self.assertIsNone(core.read_progress(p,10))

    def test_update_check_runs_even_after_updater_restart(self):
        release={'tag_name':'v9.0.0','assets':[{'name':updater.ASSET},{'name':'update.json'}]}
        with tempfile.TemporaryDirectory() as d:
            Path(d,'version.json').write_text('{"version":"1.8.0"}')
            with patch.dict(os.environ,{'FOOTSHORTS_SKIP_UPDATE':'1'}),patch('updater.fetch',return_value=json.dumps(release).encode()) as fetch:
                self.assertEqual(updater.find_update(d),release);fetch.assert_called_once()

    def test_startup_check_presents_visible_state_and_queue_result(self):
        ui=SimpleNamespace(update_checking=False,pending_update=None,update_installing=False,update_status=Mock(),jobs=queue.Queue())
        def thread(target,daemon):return SimpleNamespace(start=target)
        with patch('app.threading.Thread',side_effect=thread),patch('updater.find_update',return_value={'tag_name':'v9.0.0'}) as find:
            app.App.check_updates(ui)
        ui.update_status.set.assert_called_once()
        self.assertIn('тексерілуде',ui.update_status.set.call_args.args[0])
        self.assertEqual(ui.jobs.get_nowait()[0],'update_available');find.assert_called_once()

    def test_update_network_failure_is_not_reported_as_latest(self):
        ui=SimpleNamespace(update_checking=False,pending_update=None,update_installing=False,update_status=Mock(),jobs=queue.Queue())
        def thread(target,daemon):return SimpleNamespace(start=target)
        with patch('app.threading.Thread',side_effect=thread),patch('updater.find_update',side_effect=OSError('offline')):
            app.App.check_updates(ui)
        self.assertEqual(ui.jobs.get_nowait(),('update_error','offline'))


if __name__=='__main__':unittest.main()
