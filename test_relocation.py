import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import workflow
from batch_queue import BatchQueue


class RelocationTests(unittest.TestCase):
    def create_app(self,root):
        (root/'inputs').mkdir(parents=True);(root/'music').mkdir()
        (root/'inputs/match.mp4').write_bytes(b'source')
        (root/'music/Stadium_Ignition.mp3').write_bytes(b'music')
        def render(*args,**kwargs):Path(args[3]).write_bytes(kwargs['score'].encode())
        with patch('workflow.core.analyze',return_value=dict(score='1:0',clips=[dict(start=0,end=2,reason='fixture')],warnings=[])),patch('workflow.core.render',side_effect=render):
            return workflow.create_project(root,local_video=str(root/'inputs/match.mp4'),music=str(root/'music/Stadium_Ignition.mp3'),title_hint='North FC — South FC',log=lambda _:None)['project']

    def state(self,root,project):
        return dict(application_base=str(root),project=project['directory'],project_id=project['project_id'],
                    video=str(Path(project['directory'])/project['source_file']),music=str(root/'music/Stadium_Ignition.mp3'),
                    settings={'channel_style':{'brand_logo':str(root/'brand/logo.png')},'youtube_cookie_file':str(root/'cookies.txt')})

    def test_copy_prefers_new_output_even_when_original_still_exists(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'Old App';new=Path(d).resolve()/'New App';p=self.create_app(old);state=self.state(old,p)
            shutil.copytree(old,new)
            relocated=workflow.relocate_ui_state(new,state);directory=Path(relocated['project'])
            self.assertTrue(directory.is_relative_to(new/'output'))
            self.assertEqual(Path(relocated['video']),directory/'source/original.mp4')
            self.assertEqual(Path(relocated['music']),new/'music/Stadium_Ignition.mp3')
            self.assertEqual(Path(relocated['settings']['channel_style']['brand_logo']),new/'brand/logo.png')
            before=Path(p['directory'],'North FC — South FC.mp4').read_bytes()
            def render(*args,**kwargs):Path(args[3]).write_bytes(b'new export')
            with patch('workflow.core.render',side_effect=render):result=workflow.rerender(directory,'2:1',log=lambda _:None)
            self.assertTrue(Path(result['video']).is_relative_to(new/'output'))
            self.assertEqual(Path(result['video']).read_bytes(),b'new export')
            self.assertEqual(Path(p['directory'],'North FC — South FC.mp4').read_bytes(),before)
            self.assertEqual(state['project'],p['directory'])

    def test_legacy_state_relocates_after_original_is_removed(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'Old';new=Path(d).resolve()/'New';p=self.create_app(old);state=self.state(old,p)
            state.pop('application_base');state.pop('project_id')
            shutil.copytree(old,new);shutil.rmtree(old)
            relocated=workflow.relocate_ui_state(new,state)
            self.assertTrue(Path(relocated['project']).is_relative_to(new))
            self.assertTrue(Path(relocated['video']).is_file());self.assertTrue(Path(relocated['music']).is_file())

    def test_checkpoint_prefers_copied_project_and_finds_it_after_rename(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'Old';new=Path(d).resolve()/'New';p=self.create_app(old);shutil.copytree(old,new)
            item=dict(directory=p['directory'],project_id=p['project_id'])
            local=new/'output'/Path(p['directory']).name;renamed=local.with_name('Renamed project');local.rename(renamed)
            self.assertEqual(workflow.resolve_checkpoint(new,item),renamed)
            state=workflow.relocate_ui_state(new,self.state(old,p))
            self.assertEqual(Path(state['video']),renamed/'source/original.mp4')

    def test_missing_copy_does_not_fall_back_to_old_output_or_wrong_identity(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'Old';new=Path(d).resolve()/'New';p=self.create_app(old);new.mkdir()
            item=dict(directory=p['directory'],project_id=p['project_id'])
            self.assertIsNone(workflow.resolve_checkpoint(new,item))
            shutil.copytree(old/'output',new/'output')
            local=new/'output'/Path(p['directory']).name
            copied=workflow.load_project(local);copied['project_id']='different-project';workflow.save_project(copied)
            self.assertIsNone(workflow.resolve_checkpoint(new,item))

    def test_external_media_are_preserved_and_folder_prefix_is_not_enough(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'App';new=Path(d).resolve()/'Moved';old.mkdir();new.mkdir()
            external=Path(d).resolve()/'App-other/match.mp4'
            state=dict(application_base=str(old),video=str(external),music=str(Path(d).resolve()/'Music/song.mp3'),settings={})
            relocated=workflow.relocate_ui_state(new,state)
            self.assertEqual(relocated['video'],str(external));self.assertEqual(relocated['music'],state['music'])

    def test_copied_queue_rebases_inputs_checkpoint_and_persists_new_root(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'Old';new=Path(d).resolve()/'New';p=self.create_app(old)
            queue=BatchQueue(old/'queue.json');queue.add_files([old/'inputs/match.mp4'])
            queue.items[0].update(directory=p['directory'],project_id=p['project_id']);queue.save()
            shutil.copytree(old,new);restored=BatchQueue(new/'queue.json');item=restored.snapshot()[0]
            self.assertEqual(Path(item['url']),new/'inputs/match.mp4')
            self.assertTrue(Path(item['directory']).is_relative_to(new/'output'))
            self.assertEqual(json.loads((new/'queue.json').read_text())['application_base'],str(new))

    def test_loading_project_rebases_pending_requests_without_double_mapping_nested_copy(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'App';p=self.create_app(old);new=old/'Nested Copy';new.mkdir()
            shutil.copytree(old/'output',new/'output');shutil.copytree(old/'inputs',new/'inputs');shutil.copytree(old/'music',new/'music')
            moved=workflow.load_project(new/'output'/Path(p['directory']).name)
            self.assertEqual(Path(moved['request']['local_video']),new/'inputs/match.mp4')
            self.assertEqual(Path(moved['request']['music']),new/'music/Stadium_Ignition.mp3')
            moved['settings']['channel_style']['brand_logo']=str(Path(p['directory'])/'source/logo.png')
            workflow.save_project(moved)
            # Simulate a manifest with its original project-root asset path.
            manifest=Path(moved['directory'])/'source/project.json'
            data=json.loads(manifest.read_text());data['directory']=p['directory'];manifest.write_text(json.dumps(data))
            loaded=workflow.load_project(moved['directory'])
            self.assertEqual(Path(loaded['settings']['channel_style']['brand_logo']),Path(moved['directory'])/'source/logo.png')


@unittest.skipUnless(__import__('os').environ.get('FOOTSHORTS_GUI_TESTS')=='1','Tk restore integration')
class RestoreWindowTests(unittest.TestCase):
    def test_real_window_restores_copied_project_and_saves_new_location(self):
        import app
        import updater
        with tempfile.TemporaryDirectory() as d:
            old=Path(d).resolve()/'Old App';new=Path(d).resolve()/'Copied App';helper=RelocationTests();p=helper.create_app(old)
            (old/'version.json').write_text('{"version":"3.1.1"}')
            state=helper.state(old,p);state.pop('application_base');state.pop('project_id');state['settings']=dict(p['settings'])
            updater.atomic_json(old/'ui_state.json',state);shutil.copytree(old,new)
            with patch('app.BASE',new),patch.object(app.App,'check_updates'),patch('updater.mark_healthy'):
                ui=app.App(prompt_format=False)
                try:
                    ui.update()
                    self.assertTrue(Path(ui.project_dir).is_relative_to(new/'output'))
                    self.assertTrue(Path(ui.video.get()).is_relative_to(new/'output'))
                    ui.save_state();saved=json.loads((new/'ui_state.json').read_text())
                    self.assertEqual(saved['application_base'],str(new));self.assertEqual(saved['project_id'],p['project_id'])
                finally:
                    for ident in ui.tk.call('after','info'):ui.after_cancel(ident)
                    ui.destroy()
