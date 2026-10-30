import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import audio_sub_pipeline as audio
from core.chunker import build_target_chunks
from core.part_workflow import WorkflowStopped, part_folder, process_part


SRT = "1\n00:00:00,100 --> 00:00:01,000\nXin chào\n\n2\n00:00:01,200 --> 00:00:02,000\nTạm biệt\n"


class PartWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "Demo_Phan_01.mp4"
        self.video.write_bytes(b"video")
        self.folder = part_folder(self.root / "output", "Demo", 1)
        self.events = []

        def extract(src, dst):
            self.events.append("extract")
            Path(dst).write_bytes(b"wav")

        def transcribe(src, dst, **kwargs):
            self.events.append("whisper")
            kwargs["progress_callback"](50, 1)
            Path(dst).write_text(SRT)

        def translate(src, dst, **kwargs):
            self.events.append("translate")
            kwargs["progress_callback"](2, 2)
            Path(dst).write_text(SRT)

        def tts(src, dst, **kwargs):
            self.events.append("tts")
            kwargs["progress_callback"](2, 2, "")
            Path(dst).write_bytes(b"mp3" * 100)

        for name, value in {"extract_audio": extract, "transcribe_chinese": transcribe,
                            "translate_srt": translate, "generate_tts_from_srt": tts,
                            "_probe_duration": lambda *args: 30.0}.items():
            patcher = patch.object(audio, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_part(self, **kwargs):
        return process_part(self.video, self.folder, **kwargs)

    def test_all_artifacts_are_published_in_order_and_resume_skips_finished_stages(self):
        states = []
        def update(stage, percent, message, record):
            if record.get("srt_path"):
                self.assertTrue(Path(record["srt_path"]).is_file())
            if record.get("audio_vi"):
                self.assertTrue(Path(record["audio_vi"]).is_file())
            states.append(stage)
        result = self.run_part(progress=update)
        self.assertEqual(self.events, ["extract", "whisper", "translate", "tts"])
        self.assertLess(states.index("srt"), states.index("tts"))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len([p for p in self.folder.iterdir() if p.is_file()]), 3)
        self.events.clear()
        self.run_part()
        self.assertEqual(self.events, [])

    def test_manual_srt_changes_and_voice_changes_regenerate_only_audio(self):
        result = self.run_part()
        Path(result["srt_path"]).write_text(SRT.replace("Xin chào", "Chào bạn"))
        self.events.clear()
        self.run_part()
        self.assertEqual(self.events, ["tts"])
        self.events.clear()
        self.run_part(voice="vi-VN-HoaiMyNeural")
        self.assertEqual(self.events, ["tts"])

    def test_translation_failure_keeps_transcript_and_never_publishes_partial_srt(self):
        def fail(src, dst, **kwargs):
            Path(dst).write_text("incomplete")
            raise RuntimeError("network")
        with patch.object(audio, "translate_srt", fail):
            with self.assertRaisesRegex(RuntimeError, "network"):
                self.run_part()
        self.assertFalse((self.folder / "Demo_Phan_01.vi.srt").exists())
        self.assertFalse(list(self.folder.glob("*.pending.*")))
        self.events.clear()
        self.run_part()
        self.assertEqual(self.events, ["translate", "tts"])

    def test_stop_after_srt_preserves_work_and_resume_only_runs_tts(self):
        stopped = False
        def update(stage, percent, message, record):
            nonlocal stopped
            if stage == "srt":
                stopped = True
        with self.assertRaises(WorkflowStopped):
            self.run_part(progress=update, stop_checker=lambda: stopped)
        self.assertTrue((self.folder / "Demo_Phan_01.vi.srt").exists())
        self.events.clear()
        self.run_part()
        self.assertEqual(self.events, ["tts"])

    def test_existing_legacy_srt_is_reused_for_mp3_batch(self):
        legacy = self.root / "subtitles"
        legacy.mkdir()
        (legacy / "Demo_Phan_01.vi.srt").write_text(SRT)
        self.run_part(mode="mp3", legacy_subtitles=legacy)
        self.assertEqual(self.events, ["tts"])

    def test_organizing_existing_files_never_calls_online_services(self):
        legacy = self.root / "subtitles"
        legacy.mkdir()
        (legacy / "Demo_Phan_01.vi.srt").write_text(SRT)
        result = self.run_part(mode="organize", legacy_subtitles=legacy)
        self.assertTrue(Path(result["srt_path"]).is_file())
        self.assertEqual(self.events, [])

    def test_mp3_only_does_not_unexpectedly_run_whisper(self):
        with self.assertRaisesRegex(RuntimeError, "Chưa có SRT"):
            self.run_part(mode="mp3")
        self.assertEqual(self.events, [])

    def test_replaced_source_invalidates_subtitles_and_audio(self):
        self.run_part()
        self.video.write_bytes(b"different video")
        self.events.clear()
        self.run_part()
        self.assertEqual(self.events, ["extract", "whisper", "translate", "tts"])

    def test_tts_error_keeps_srt_and_retry_does_not_retranslate(self):
        with patch.object(audio, "generate_tts_from_srt", side_effect=RuntimeError("TTS failure")):
            with self.assertRaisesRegex(RuntimeError, "TTS failure"):
                self.run_part()
        manifest = json.loads((self.folder / ".work/progress.json").read_text())
        self.assertEqual(manifest["status"], "error")
        self.assertTrue((self.folder / "Demo_Phan_01.vi.srt").is_file())
        self.events.clear()
        self.run_part()
        self.assertEqual(self.events, ["tts"])

    def test_seven_hours_produces_fourteen_thirty_minute_parts(self):
        item = {"name": "7h.mp4", "source": "7h.mp4", "duration": 7 * 3600, "is_local": True}
        plan = build_target_chunks([item], "Demo", target_hours=.5, speed_factor=1)
        self.assertEqual(len(plan["chunks"]), 14)
        self.assertTrue(all(c["total_duration"] == 1800 for c in plan["chunks"]))


class TtsFailureTests(unittest.TestCase):
    def test_failed_voice_segment_stops_export_instead_of_silently_dropping_words(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path / "input.srt").write_text(SRT)
            with patch.object(audio, "_synthesize_edge_tts_segment", AsyncMock(return_value=False)):
                with self.assertRaisesRegex(RuntimeError, "Không tạo được giọng đọc"):
                    audio.generate_tts_from_srt(str(path / "input.srt"), str(path / "output.mp3"))
            self.assertFalse((path / "output.mp3").exists())


if __name__ == "__main__":
    unittest.main()
