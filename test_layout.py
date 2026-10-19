"""Check that compact controls stay reachable at desktop and laptop sizes."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app


@unittest.skipUnless(os.environ.get('FOOTSHORTS_GUI_TESTS')=='1','Tk layout integration')
class CompactLayoutTests(unittest.TestCase):
    def test_startup_format_choice_and_unlimited_setting_persist(self):
        with tempfile.TemporaryDirectory() as d,patch('app.BASE',Path(d)),patch.object(app.App,'check_updates'),patch('updater.mark_healthy'):
            ui=app.App(prompt_format=False)
            try:
                ui.update();ui.choose_startup_format();dialog=ui.format_dialog
                self.assertTrue(dialog.winfo_exists());dialog.landscape_button.invoke();ui.update()
                self.assertEqual(ui.settings()['output_format'],'landscape')
                self.assertEqual(ui.settings()['target'],300)
                self.assertEqual(str(ui.zoom_btn['state']),'disabled')
                ui.target.set('Шектеусіз');ui.save_state()
                ui.set_output_format('shorts',user_change=True)
                self.assertEqual(ui.settings()['target'],180)
                ui.restore_state();self.assertEqual(ui.settings()['output_format'],'landscape')
                self.assertIsNone(ui.settings()['target'])
                ui.choose_startup_format();ui.format_dialog.shorts_button.invoke()
                self.assertEqual(ui.settings()['output_format'],'shorts')
                self.assertEqual(ui.settings()['target'],180)
                self.assertEqual(str(ui.zoom_btn['state']),'normal')
            finally:
                for ident in ui.tk.call('after','info'):ui.after_cancel(ident)
                ui.destroy()

    def test_channel_template_apply_keeps_login_and_restores_video_settings(self):
        from channel_ui import ChannelWindow
        with tempfile.TemporaryDirectory() as d,patch('app.BASE',Path(d)),patch.object(app.App,'check_updates'),patch('updater.mark_healthy'):
            Path(d,'version.json').write_text('{"version":"3.0.0"}')
            ui=app.App(prompt_format=False);window=None
            try:
                ui.music.set('');ui.youtube_login.set('Chrome');ui.intro.set(False);ui.show_final.set(False);ui.language.set('English')
                window=ChannelWindow(ui);window.name.set('ExampleChannel');window.values['accent_color'].set('#00ff00');window.save()
                ui.intro.set(True);ui.show_final.set(True);ui.language.set('Қазақша');window.apply();window=None
                self.assertEqual(ui.settings()['language'],'en')
                self.assertFalse(ui.intro.get());self.assertFalse(ui.show_final.get())
                self.assertEqual(ui.youtube_login.get(),'Chrome');self.assertEqual(ui.channel_style['accent_color'],'#00ff00')
            finally:
                if window:window.destroy()
                for ident in ui.tk.call('after','info'):ui.after_cancel(ident)
                ui.destroy()

    def test_timeline_mouse_trim_and_reorder_are_undoable(self):
        import tkinter as tk
        from clip_timeline import ClipTimeline
        from review_model import ReviewModel
        root=tk.Tk();root.geometry('600x220');model=ReviewModel([dict(start=0,end=10),dict(start=20,end=30)],40)
        errors=[];timeline=ClipTimeline(root,model,lambda i:None,lambda i:None,errors.append);timeline.pack(fill='x')
        try:
            root.update();a,b=timeline.blocks[0]
            timeline.canvas.event_generate('<ButtonPress-1>',x=int(a+3),y=40)
            timeline.canvas.event_generate('<B1-Motion>',x=int(a+30),y=40)
            timeline.canvas.event_generate('<ButtonRelease-1>',x=int(a+30),y=40);root.update()
            self.assertGreater(model.clips[0]['start'],0);model.undo();timeline.redraw()
            a,b=timeline.blocks[0];x=(a+b)/2;target=timeline.blocks[1][1]-10
            timeline.canvas.event_generate('<ButtonPress-1>',x=int(x),y=40)
            timeline.canvas.event_generate('<B1-Motion>',x=int(target),y=40)
            timeline.canvas.event_generate('<ButtonRelease-1>',x=int(target),y=40);root.update()
            self.assertEqual([c['start'] for c in model.clips],[20,0]);model.undo()
            self.assertEqual([c['start'] for c in model.clips],[0,20]);self.assertFalse(errors)
        finally:root.destroy()

    def test_wide_columns_and_narrow_scroll_keep_score_reachable(self):
        with tempfile.TemporaryDirectory() as d,patch('app.BASE',Path(d)),patch.object(app.App,'check_updates'),patch('updater.mark_healthy'):
            Path(d,'version.json').write_text('{"version":"1.9.2"}')
            ui=app.App(prompt_format=False)
            try:
                ui.geometry('1600x900');ui.update()
                self.assertEqual(ui.youtube_login.get(),'Аккаунтсыз')
                ui.youtube_login.set('Chrome')
                self.assertEqual(ui.settings()['youtube_browser'],'chrome')
                self.assertEqual(ui.settings()['youtube_cookie_file'],'')
                ui.youtube_login.set('Аккаунтсыз')
                self.assertEqual(ui.settings()['youtube_browser'],'')
                self.assertEqual(str(ui.language_combo['state']),'readonly')
                self.assertEqual(ui.settings()['language'],'kk')
                ui.language.set('Русский');ui.save_state();ui.language.set('English');ui.restore_state()
                self.assertEqual(ui.settings()['language'],'ru')
                self.assertTrue(ui.show_final.get())
                self.assertEqual(ui.show_final_btn.master.master,ui.visual_panel)
                ui.show_final_btn.invoke();self.assertFalse(ui.settings()['show_final'])
                ui.save_state();ui.show_final.set(True);ui.restore_state()
                self.assertFalse(ui.show_final.get())
                ui.show_final_btn.invoke();self.assertTrue(ui.settings()['show_final'])
                self.assertFalse(ui.action_camera.get())
                ui.zoom_btn.invoke();self.assertTrue(ui.settings()['action_camera'])
                ui.no_zoom_btn.invoke();self.assertFalse(ui.settings()['action_camera'])
                ui.zoom_btn.invoke();ui.new_project();self.assertFalse(ui.action_camera.get())
                self.assertTrue(ui._wide_layout)
                for left,right in [(ui.analysis_panel,ui.visual_panel),(ui.clips_panel,ui.messages_panel)]:
                    self.assertEqual(left.winfo_y(),right.winfo_y())
                    self.assertGreater(right.winfo_x(),left.winfo_x()+left.winfo_width())
                self.assertLessEqual(ui.score_entry.winfo_rooty()+ui.score_entry.winfo_height(),ui.winfo_rooty()+ui.winfo_height())
                ui.editor.insert('1.0','00:10 - 00:20 | Гол | goal=00:18')
                ui.score.set('2:1')
                ui.geometry('900x650');ui.update()
                self.assertFalse(ui._wide_layout)
                self.assertGreater(ui.messages_panel.winfo_y(),ui.clips_panel.winfo_y())
                ui.main_canvas.yview_moveto(1);ui.update()
                self.assertLess(ui.status_label.winfo_rooty(),ui.winfo_rooty()+ui.winfo_height())
                self.assertEqual(ui.score.get(),'2:1')
                self.assertIn('goal=00:18',ui.editor.get('1.0','end'))
            finally:
                for ident in ui.tk.call('after','info'):ui.after_cancel(ident)
                ui.destroy()
