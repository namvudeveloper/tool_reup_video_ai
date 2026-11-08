import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.media_waveform import read_waveform
import gui_server as gui


class WaveformTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg'), 'requires ffmpeg')
    def test_real_audio_has_bounded_peaks_and_cache_changes_with_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'sample.wav'
            def generate(source):
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', source, str(path)], check=True)
            generate('sine=frequency=440:duration=1')
            data = read_waveform(path, 'ffmpeg')
            self.assertTrue(data['peaks'])
            self.assertTrue(all(0 <= p <= 1 for p in data['peaks']))
            self.assertGreater(max(data['peaks']), .1)
            self.assertAlmostEqual(data['duration'], 1, delta=.2)
            generate('anullsrc=r=44100:cl=mono:d=1')
            self.assertTrue(all(p == 0 for p in read_waveform(path, 'ffmpeg')['peaks']))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'requires ffmpeg')
    def test_close_zoom_reads_the_requested_interval_with_detail(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'transition.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'aevalsrc=if(lt(t\\,1)\\,0\\,0.3*sin(2*PI*220*t)):s=24000:d=2', str(path)], check=True)
            quiet = read_waveform(path, 'ffmpeg', 0, .5)
            sound = read_waveform(path, 'ffmpeg', 1.2, .5)
            self.assertTrue(all(p == 0 for p in quiet['peaks']))
            self.assertGreater(max(sound['peaks']), .2)
            self.assertGreater(len(sound['peaks']), 50)
            self.assertAlmostEqual(sound['duration'], .5, delta=.02)
            with self.assertRaises(ValueError):
                read_waveform(path, 'ffmpeg', float('nan'), .5)

    def test_route_rejects_files_outside_output_and_active_video(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            outside = root / 'outside.mp3'
            outside.write_bytes(b'audio')
            handler = gui.GuiRequestHandler.__new__(gui.GuiRequestHandler)
            handler.path = '/api/waveform?path=' + str(outside)
            with patch.object(gui, 'OUTPUT_DIR', root / 'output'), patch.object(gui, '_get_srt_target', return_value=''), patch.object(handler, '_send_json') as send:
                handler.do_GET()
            self.assertEqual(send.call_args.kwargs['status'], 404)


if __name__ == '__main__':
    unittest.main()
