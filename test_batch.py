"""Mixed local/YouTube queues preserve order and survive interruption."""
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from batch_queue import BatchQueue
from batch_ui import BatchWindow


class MixedQueueTests(unittest.TestCase):
    def test_files_are_deduplicated_persisted_and_removed_without_deleting_media(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'Матч with spaces.mp4';video.write_bytes(b'video')
            model=BatchQueue(Path(d)/'queue.json')
            model.add_files([video,video]);model.add_files([video])
            model=BatchQueue(model.path)
            self.assertEqual(len(model.snapshot()),1)
            item=model.snapshot()[0]
            self.assertEqual(item['source_type'],'file')
            self.assertEqual(item['url'],str(video.resolve()))
            model.remove({item['id']})
            self.assertEqual(model.snapshot(),[]);self.assertTrue(video.exists())

    def test_missing_file_batch_does_not_partially_add(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'match.mp4';video.touch()
            model=BatchQueue(Path(d)/'queue.json')
            with self.assertRaises(ValueError):model.add_files([video,Path(d)/'missing.mp4'])
            self.assertEqual(model.snapshot(),[])

    def test_mixed_inputs_route_to_existing_pipeline_and_continue_after_failure(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'local match.mp4';video.touch()
            model=BatchQueue(Path(d)/'queue.json')
            model.add('https://youtu.be/so5hJv_2cVQ');model.add_files([video])
            owner=SimpleNamespace(busy=False,review_open=False,settings=lambda:{'target':90},
                music=Mock(),app_base=Path(d),log=Mock(),cancel_event=threading.Event(),jobs=queue.Queue())
            owner.music.get.return_value=''
            owner.start=lambda job,callback:callback(job())
            finished=Mock();window=SimpleNamespace(owner=owner,model=model,finished=finished)
            def create(base,**kwargs):
                if kwargs['url']:raise RuntimeError('download failed')
                self.assertEqual(kwargs['local_video'],str(video.resolve()))
                self.assertEqual(kwargs['settings'],{'target':90})
                return {'directory':str(Path(d)/'output/local'),'project':{'title':'Local'}}
            with patch('batch_ui.workflow.create_project',side_effect=create) as pipeline:
                BatchWindow.run(window)
            self.assertEqual(pipeline.call_count,2)
            self.assertEqual([i['status'] for i in model.snapshot()],['error','done'])
            self.assertEqual(len(finished.call_args.args[0]),1)
            self.assertEqual([owner.jobs.get_nowait()[0] for _ in range(owner.jobs.qsize())],['batch_progress']*4)

    def test_restart_recovers_running_local_item_and_preserves_waiting_item(self):
        with tempfile.TemporaryDirectory() as d:
            video=Path(d)/'local.mp4';video.touch()
            model=BatchQueue(Path(d)/'queue.json');model.add_files([video])
            model.add('https://youtu.be/so5hJv_2cVQ')
            model.items[0]['status']='running';model.save()
            restored=BatchQueue(model.path)
            self.assertEqual([i['status'] for i in restored.snapshot()],['queued','queued'])
            restored.running=True
            with self.assertRaises(ValueError):restored.remove({restored.items[0]['id']})
            with self.assertRaises(ValueError):restored.add_files([video])

    @unittest.skipUnless(os.environ.get('FOOTSHORTS_GUI_TESTS')=='1','Windows Tk integration')
    def test_visible_file_picker_adds_multiple_files_and_removes_selected(self):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as d:
            videos=[Path(d)/'A B.mp4',Path(d)/'C D.mp4']
            for p in videos:p.touch()
            root=tk.Tk();root.cancel_event=threading.Event()
            model=BatchQueue(Path(d)/'queue.json')
            window=BatchWindow(root,model)
            try:
                with patch('batch_ui.filedialog.askopenfilenames',return_value=[str(p) for p in videos]):
                    window.add_files()
                root.update()
                self.assertEqual(len(window.table.get_children()),2)
                window.table.selection_set(model.snapshot()[0]['id']);window.remove_selected()
                self.assertEqual(len(window.table.get_children()),1)
                self.assertTrue(all(p.exists() for p in videos))
            finally:window.destroy();root.destroy()
