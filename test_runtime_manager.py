from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import runtime_manager as runtime
import updater


class RuntimeTests(unittest.TestCase):
    def root(self,d):
        root=Path(d);(root/'version.json').write_text('{"version":"2.0.0"}')
        return root

    def test_external_old_runtime_is_ignored_after_move(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d)
            self.assertEqual(runtime.candidates(root,sys.executable),[])
            (root/'.updates').mkdir();updater.atomic_json(root/'.updates/runtime.json',{'python':sys.executable})
            self.assertEqual(updater.runtime_python(root,'fallback'),'fallback')

    def test_healthy_local_python_does_not_install_anything(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d);python=root/'.runtime/python.exe';python.parent.mkdir();python.touch()
            with patch.object(runtime,'probe',return_value=[]),patch.object(runtime,'logged_run') as run:
                self.assertEqual(runtime.ensure_runtime(root,python,lambda _:None),str(python.resolve()))
                run.assert_not_called()

    def test_repair_creates_separate_environment_and_preserves_user_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d);python=root/'.runtime/python.exe';python.parent.mkdir();python.write_bytes(b'working interpreter')
            (root/'requirements.txt').write_text('numpy\n');(root/'output').mkdir();(root/'output/video.mp4').write_bytes(b'keep')
            commands=[]
            def run(args,root,log):
                commands.append(args)
                if '-m' in args and 'venv' in args:
                    new=Path(args[-1])/('Scripts/python.exe' if os.name=='nt' else 'bin/python');new.parent.mkdir(parents=True);new.touch()
            with patch.object(runtime,'probe',side_effect=[['numpy'],[]]),patch.object(runtime,'logged_run',side_effect=run):
                selected=runtime.ensure_runtime(root,python,lambda _:None)
            self.assertIn('repair-',selected);self.assertEqual(len(commands),2)
            self.assertEqual(python.read_bytes(),b'working interpreter');self.assertEqual((root/'output/video.mp4').read_bytes(),b'keep')

    def test_failed_repair_does_not_change_working_pointer(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.root(d);python=root/'.runtime/python.exe';python.parent.mkdir();python.touch();(root/'.updates').mkdir()
            old={'python':str(python),'version':'1.9.5'};updater.atomic_json(root/'.updates/runtime.json',old)
            with patch.object(runtime,'probe',return_value=['numpy']),patch.object(runtime,'logged_run',side_effect=RuntimeError('pip failed')):
                with self.assertRaisesRegex(RuntimeError,'pip failed'):runtime.ensure_runtime(root,python,lambda _:None)
            self.assertEqual(json.loads((root/'.updates/runtime.json').read_text()),old)

    @unittest.skipUnless(os.name=='nt','Windows runtime integration')
    def test_probe_current_windows_python_including_native_dlls(self):
        self.assertEqual(runtime.probe(sys.executable),[])
