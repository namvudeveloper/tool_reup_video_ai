import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gui_server as gui

SRT = '1\n00:00:00,000 --> 00:00:02,500\nXin chào Việt Nam!\n'


class SubtitleImportTests(unittest.TestCase):
    def request(self, body):
        handler = gui.GuiRequestHandler.__new__(gui.GuiRequestHandler)
        handler.path = '/api/srt/import'
        handler._read_json_body = Mock(return_value=body)
        handler._send_json = Mock()
        handler._dispatch_POST()
        return handler._send_json.call_args

    def test_browser_file_import_uses_its_own_destination_without_writing(self):
        with tempfile.TemporaryDirectory() as d, patch.object(gui, 'STATE', gui.PipelineState()) as state, patch.object(gui, 'SRT_WORK_DIR', Path(d) / 'subtitles'), patch.object(gui, 'OUTPUT_DIR', Path(d) / 'output'):
            previous = Path(d) / 'previous.vi.srt'
            previous.write_text('keep this document')
            state.active_srt_path = str(previous)
            call = self.request({'filename': 'Phim_Phan_01.vi.srt', 'text': SRT})
            self.assertTrue(call.args[0]['ok'])
            self.assertEqual(state.srt_rows[0]['vi_text'], 'Xin chào Việt Nam!')
            self.assertNotEqual(state.active_srt_path, str(previous))
            self.assertFalse(Path(state.active_srt_path).exists())
            self.assertEqual(previous.read_text(), 'keep this document')

    def test_file_uri_with_spaces_and_vietnamese_loads_matching_video(self):
        with tempfile.TemporaryDirectory() as d, patch.object(gui, 'STATE', gui.PipelineState()) as state, patch.object(gui, 'OUTPUT_DIR', Path(d) / 'output'):
            path = Path(d) / 'Phần một.vi.srt'
            path.write_text(SRT)
            video = path.with_name('Phần một.mp4')
            video.write_bytes(b'video')
            call = self.request({'source_path': path.as_uri()})
            self.assertTrue(call.args[0]['ok'])
            self.assertEqual(state.active_srt_path, str(path.resolve()))
            self.assertEqual(state.active_video_for_srt, str(video.resolve()))
            self.assertIn(str(video.resolve()), [v['path'] for v in call.args[0]['available_videos']])

    def test_invalid_file_keeps_current_subtitle_and_save_destination(self):
        with patch.object(gui, 'STATE', gui.PipelineState()) as state:
            state.srt_rows = [{'vi_text': 'Keep this cue'}]
            state.active_srt_path = '/keep.vi.srt'
            for body in [{'filename': 'broken.srt', 'text': 'not subtitles'},
                         {'filename': 'bad.srt', 'text': '1\nbad --> worse\ntext'},
                         {'source_path': 'file://remote/share/test.srt'},
                         {'filename': 'data.txt', 'text': SRT}]:
                call = self.request(body)
                self.assertEqual(call.kwargs['status'], 400)
                self.assertEqual(state.srt_rows, [{'vi_text': 'Keep this cue'}])
                self.assertEqual(state.active_srt_path, '/keep.vi.srt')


if __name__ == '__main__':
    unittest.main()
