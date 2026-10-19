"""Check that compact controls stay reachable at desktop and laptop sizes."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app


@unittest.skipUnless(os.environ.get('FOOTSHORTS_GUI_TESTS')=='1','Tk layout integration')
class CompactLayoutTests(unittest.TestCase):
    def test_wide_columns_and_narrow_scroll_keep_score_reachable(self):
        with tempfile.TemporaryDirectory() as d,patch('app.BASE',Path(d)),patch.object(app.App,'check_updates'),patch('updater.mark_healthy'):
            Path(d,'version.json').write_text('{"version":"1.9.2"}')
            ui=app.App()
            try:
                ui.geometry('1600x900');ui.update()
                self.assertEqual(ui.youtube_login.get(),'Аккаунтсыз')
                ui.youtube_login.set('Chrome')
                self.assertEqual(ui.settings()['youtube_browser'],'chrome')
                self.assertEqual(ui.settings()['youtube_cookie_file'],'')
                ui.youtube_login.set('Аккаунтсыз')
                self.assertEqual(ui.settings()['youtube_browser'],'')
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
