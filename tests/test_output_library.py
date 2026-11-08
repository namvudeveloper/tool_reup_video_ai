import json
import tempfile
import unittest
from pathlib import Path

from core.output_library import scan_output_library


class OutputLibraryTests(unittest.TestCase):
    def test_missing_root_is_empty_and_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'output'
            self.assertEqual(scan_output_library(root)['summary']['parts'], 0)
            self.assertFalse(root.exists())

    def test_grouped_parts_keep_matching_assets_and_numeric_order(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for i in (10, 2):
                folder = root / 'Truyện ABC' / f'Phan_{i:02d}'
                folder.mkdir(parents=True)
                stem = f'ABC_Phan_{i:02d}'
                (folder / f'{stem}.mp4').write_bytes(b'video')
                (folder / f'{stem}.vi.srt').write_text('subtitle')
                (folder / f'{stem}.thuyet_minh.mp3').write_bytes(b'audio')
                work = folder / '.work'
                work.mkdir()
                (work / 'audio16k.wav').write_bytes(b'internal')
            # An old duplicate at the root must not create a second copy of part 2.
            (root / 'ABC_Phan_02.mp4').write_bytes(b'old')
            result = scan_output_library(root)
            self.assertEqual(result['summary']['parts'], 2)
            self.assertEqual(result['summary']['complete'], 2)
            self.assertEqual([p['chunk_index'] for p in result['projects'][0]['parts']], [2, 10])
            self.assertEqual(result['summary']['size_bytes'], 36)
            self.assertTrue(all(len(p['files']) == 3 for p in result['projects'][0]['parts']))

    def test_legacy_assets_and_checkpoint_error_can_be_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            video = root / 'ABC_Phan_03.mp4'
            video.write_bytes(b'video')
            (root / 'subtitles').mkdir()
            (root / 'subtitles/ABC_Phan_03.vi.srt').write_text('subtitle')
            result = scan_output_library(root)
            part = result['projects'][0]['parts'][0]
            self.assertEqual(part['chunk_index'], 3)
            self.assertEqual(part['status'], 'partial')
            self.assertTrue(part['srt_path'].endswith('.vi.srt'))
            result = scan_output_library(root, [{'path': str(video), 'status': 'error', 'stage': 'tts', 'error': 'Try again'}])
            part = result['projects'][0]['parts'][0]
            self.assertEqual(part['status'], 'error')
            self.assertEqual(part['error'], 'Try again')

    def test_symlinks_outside_root_and_internal_folders_are_not_listed(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            root = base / 'output'
            folder = root / 'ABC/Phan_01'
            folder.mkdir(parents=True)
            secret = base / 'outside.mp4'
            secret.write_bytes(b'outside')
            (folder / 'escaped.mp4').symlink_to(secret)
            (root / 'escaped').symlink_to(base, target_is_directory=True)
            (root / 'subtitles').mkdir()
            (root / 'subtitles/temp.mp4').write_bytes(b'internal')
            result = scan_output_library(root)
            self.assertEqual(len(result['projects']), 1)
            self.assertEqual(result['projects'][0]['parts'][0]['path'], '')
            self.assertEqual(result['summary']['size_bytes'], 0)

    def test_checkpoint_without_running_worker_is_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            folder = root / 'Story/Phan_01'
            (folder / '.work').mkdir(parents=True)
            video = folder / 'Story_Phan_01.mp4'
            video.write_bytes(b'video')
            (folder / '.work/progress.json').write_text(json.dumps({'status': 'running', 'stage': 'tts'}))
            part = scan_output_library(root)['projects'][0]['parts'][0]
            self.assertEqual(part['status'], 'stopped')
            part = scan_output_library(root, [{'path': str(video), 'status': 'running'}])['projects'][0]['parts'][0]
            self.assertEqual(part['status'], 'running')

    def test_empty_project_and_incomplete_part_remain_visible(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'Empty story').mkdir()
            folder = root / 'Story/Phan_01'
            (folder / '.work').mkdir(parents=True)
            (folder / '.work/progress.json').write_text(json.dumps({'status': 'error', 'stage': 'srt', 'error': 'Translation failed'}))
            result = scan_output_library(root)
            self.assertEqual(result['summary']['projects'], 2)
            part = next(p for p in result['projects'] if p['name'] == 'Story')['parts'][0]
            self.assertEqual(part['status'], 'error')
            self.assertEqual(part['stage'], 'srt')


if __name__ == '__main__':
    unittest.main()
