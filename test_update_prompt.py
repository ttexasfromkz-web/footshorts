import json
import os
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import app
import updater


class UpdatePromptTests(unittest.TestCase):
    def fake_app(self):
        return SimpleNamespace(busy=False,log=Mock(),update_checking=False,pending_update=None,
                               update_installing=False,jobs=queue.Queue(),save_state=Mock(),destroy=Mock())

    def test_decline_never_downloads_or_installs(self):
        ui=self.fake_app()
        with patch('app.messagebox.askyesno',return_value=False),patch('updater.download_update') as download,patch('updater.launch_helper') as launch:
            app.App.offer_update(ui,{'tag_name':'v9.0.0'})
        download.assert_not_called();launch.assert_not_called()
        self.assertIsNone(ui.pending_update);self.assertFalse(ui.update_checking)

    def test_accept_downloads_and_queues_verified_stage(self):
        ui=self.fake_app()
        def thread(target,daemon):return SimpleNamespace(start=target)
        with patch('app.messagebox.askyesno',return_value=True) as prompt,patch('app.threading.Thread',side_effect=thread),patch('updater.download_update',return_value='/verified/stage') as download:
            app.App.offer_update(ui,{'tag_name':'v9.0.0'})
        self.assertIn('9.0.0',prompt.call_args.args[1]);download.assert_called_once()
        self.assertEqual(ui.jobs.get_nowait(),('update_ready','/verified/stage'))

    def test_approved_install_waits_for_active_work(self):
        ui=self.fake_app();ui.pending_update='/verified/stage';ui.busy=True
        with patch('updater.launch_helper') as launch:
            self.assertFalse(app.App.install_pending_update(ui));launch.assert_not_called()
            ui.busy=False
            self.assertTrue(app.App.install_pending_update(ui));launch.assert_called_once()
        ui.save_state.assert_called_once();ui.destroy.assert_called_once()

    def test_discovery_fetches_metadata_only(self):
        release={'tag_name':'v9.0.0','assets':[{'name':updater.ASSET},{'name':'update.json'}]}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'FOOTSHORTS_SKIP_UPDATE':'0'}),patch('updater.fetch',return_value=json.dumps(release).encode()) as fetch:
            Path(d,'version.json').write_text(json.dumps({'version':'1.7.0'}))
            self.assertEqual(updater.find_update(d),release)
            fetch.assert_called_once_with(updater.API,1024*1024)
            self.assertFalse(Path(d,'.updates/staging').exists())


if __name__=='__main__':unittest.main()
