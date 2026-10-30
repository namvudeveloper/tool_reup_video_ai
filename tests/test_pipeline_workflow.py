import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import audio_sub_pipeline as audio
import gui_server as gui


@unittest.skipUnless(shutil.which("ffmpeg"), "requires ffmpeg")
class PipelineIntegrationTests(unittest.TestCase):
    def test_batch_continues_after_one_part_fails_and_preserves_its_srt(self):
        with tempfile.TemporaryDirectory() as d, ExitStack() as stack:
            output = Path(d) / "output"
            output.mkdir()
            stack.enter_context(patch.object(gui, "OUTPUT_DIR", output))
            state = gui.PipelineState()
            state.add_log = Mock()
            state.is_running = True
            stack.enter_context(patch.object(gui, "STATE", state))
            jobs = []
            for i in (1, 2):
                video = output / f"Demo_Phan_{i:02d}.mp4"
                video.write_bytes(b"video")
                jobs.append({"path": str(video), "name": video.name, "chunk_index": i})
            state.finished_outputs = [dict(j) for j in jobs]
            calls = []
            def process(video, folder, **kwargs):
                calls.append(video.name)
                record = {"path": str(folder / video.name), "name": video.name, "folder": str(folder),
                          "srt_path": str(folder / "sub.vi.srt"), "audio_vi": "", "stage": "tts",
                          "status": "error" if len(calls) == 1 else "complete", "error": "TTS failed" if len(calls) == 1 else ""}
                kwargs["progress"]("tts", 0, record["error"] or "done", record)
                if len(calls) == 1:
                    raise RuntimeError("TTS failed")
                return record
            with patch.object(gui, "process_part", process):
                gui._run_asset_batch_worker(jobs, "full", {})
            self.assertEqual(calls, ["Demo_Phan_01.mp4", "Demo_Phan_02.mp4"])
            self.assertEqual([r["status"] for r in state.finished_outputs], ["error", "complete"])
            self.assertTrue(state.finished_outputs[0]["srt_path"])
            self.assertIn("1 phần", state.error_message)
            self.assertFalse(state.is_running)

    def test_batch_rejects_unknown_paths_and_start_rejects_empty_selection(self):
        with tempfile.TemporaryDirectory() as d, patch.object(gui, "OUTPUT_DIR", Path(d)):
            state = gui.PipelineState()
            state.add_log = Mock()
            with patch.object(gui, "STATE", state):
                handler = gui.GuiRequestHandler.__new__(gui.GuiRequestHandler)
                handler.path = "/api/workflow/batch"
                handler._read_json_body = Mock(return_value={"paths": ["/unknown.mp4"], "mode": "full"})
                handler._send_json = Mock()
                handler._dispatch_POST()
                self.assertEqual(handler._send_json.call_args.kwargs["status"], 400)
                self.assertFalse(state.is_running)
                state.items = [{"name": "source.mp4"}]
                handler.path = "/api/start"
                handler._read_json_body.return_value = {}
                handler._dispatch_POST()
                self.assertEqual(handler._send_json.call_args.kwargs["status"], 400)
                self.assertFalse(state.is_running)

    def test_real_video_is_split_and_each_part_finishes_srt_and_audio_before_next(self):
        with tempfile.TemporaryDirectory(prefix="workflow_integration_") as d, ExitStack() as stack:
            root = Path(d)
            for name, path in {"OUTPUT_DIR": root / "output", "SRT_WORK_DIR": root / "output/subtitles",
                               "RAW_DIR": root / "raw", "PROCESSED_DIR": root / "processed",
                               "UPLOAD_CACHE_DIR": root / "uploads"}.items():
                stack.enter_context(patch.object(gui, name, path))
            state = gui.PipelineState()
            state.add_log = Mock()
            state.enc_info = {"encoder": "libx264", "label": "CPU"}
            state.started_at = time.time()
            state.is_running = True
            stack.enter_context(patch.object(gui, "STATE", state))
            source = root / "source.mp4"
            subprocess.run([state.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i",
                            "color=size=160x90:rate=1:duration=122", "-f", "lavfi", "-i",
                            "sine=frequency=400:duration=122", "-c:v", "libx264", "-preset", "ultrafast",
                            "-c:a", "aac", "-shortest", str(source)], check=True)
            order = []
            def transcript(src, dst, **kwargs):
                order.append((Path(dst).parent.parent.name, "whisper"))
                Path(dst).write_text("1\n00:00:00,100 --> 00:00:01,000\n你好\n")
                kwargs["progress_callback"](100, 1)
            def translate(src, dst, **kwargs):
                order.append((Path(dst).parent.name, "srt"))
                Path(dst).write_text("1\n00:00:00,100 --> 00:00:01,000\nXin chào\n")
                kwargs["progress_callback"](1, 1)
            def tts(src, dst, **kwargs):
                order.append((Path(dst).parent.name, "mp3"))
                subprocess.run([state.ffmpeg_path, "-y", "-v", "error", "-f", "lavfi", "-i",
                                "anullsrc=r=24000:cl=mono", "-t", str(kwargs["total_video_duration"]),
                                str(dst)], check=True)
                kwargs["progress_callback"](1, 1, "Xin chào")
            stack.enter_context(patch.object(audio, "transcribe_chinese", transcript))
            stack.enter_context(patch.object(audio, "translate_srt", translate))
            stack.enter_context(patch.object(audio, "generate_tts_from_srt", tts))
            settings = dict(state.settings, workflow_mode="full", resolution="160x90", fps=1,
                            video_bitrate="64k", anti_copyright={"enabled": False}, blur_sub={"mode": "off"})
            config = {"settings": settings, "items": [{"id": "source", "name": source.name,
                       "source": str(source), "is_local": True, "duration": 122}],
                      "project_name": "Demo", "target_hours": 1 / 60,
                      "chunk_mode": "target_duration", "selected_chunks": [1, 2]}
            gui._run_pipeline_worker(config)
            self.assertEqual(state.error_message, "")
            self.assertFalse(state.is_running)
            self.assertEqual(order, [("Phan_01", "whisper"), ("Phan_01", "srt"), ("Phan_01", "mp3"),
                                     ("Phan_02", "whisper"), ("Phan_02", "srt"), ("Phan_02", "mp3")])
            self.assertEqual(len(state.finished_outputs), 2)
            for result in state.finished_outputs:
                self.assertEqual(result["status"], "complete")
                self.assertTrue(all(Path(result[key]).is_file() for key in ("path", "srt_path", "audio_vi")))
                self.assertEqual(len([p for p in Path(result["folder"]).iterdir() if p.is_file()]), 3)
                duration, _ = gui.probe_media_info(state.ffprobe_path, Path(result["path"]))
                self.assertAlmostEqual(duration, 60, delta=.2)
            # A later batch resumes these folders and does not invoke AI or TTS again.
            state.is_running = True
            gui._run_asset_batch_worker([dict(r) for r in state.finished_outputs], "full", settings)
            self.assertEqual(len(order), 6)
            self.assertEqual(len(state.finished_outputs), 2)
            self.assertEqual(state.overall_pct, 100)


if __name__ == "__main__":
    unittest.main()
