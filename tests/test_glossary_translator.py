import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import srt

import audio_sub_pipeline as audio
import gui_server as gui
from core.glossary_translator import (
    apply_post_replace,
    build_glossary_sample_text,
    extract_glossary_with_gemini,
    group_broken_cues,
    join_cues_text,
    load_glossary,
    mask_batch_texts,
    merge_glossary_rules,
    normalize_glossary_payload,
    save_glossary,
    split_translation_for_cues,
    translate_units_resilient,
)


class GlossaryAndSentenceTests(unittest.TestCase):
    def test_pre_and_post_replace_preserves_longest_terms_and_word_boundaries(self):
        rules = normalize_glossary_payload(
            {
                "rules": [
                    {"zh": "青云宗", "vi": "Thanh Vân Tông"},
                    {"zh": "青云宗主", "vi": "Tông Chủ Thanh Vân"},
                    {"zh": "韩立", "vi": "Hàn Lập"},
                    {"find": "Hàn Đứng", "replace": "Hàn Lập", "stage": "post"},
                    {"find": "Hàn", "replace": "Họ Hàn", "stage": "post"},
                ]
            }
        )["rules"]

        masked, token_map = mask_batch_texts(["韩立拜见青云宗主，离开青云宗。"], rules)
        self.assertIn("XGLOSS0000X", masked[0])
        self.assertIn("XGLOSS0001X", masked[0])
        self.assertIn("XGLOSS0002X", masked[0])

        # Simulate Google lowercasing a token and returning a stiff post term.
        simulated_google = "xgloss0000x bái kiến XGLOSS0001X , rời khỏi XGLOSS0002X . Hàn Quốc cũng biết Hàn Đứng."
        restored = apply_post_replace(simulated_google, token_map, rules)
        self.assertEqual(
            restored,
            "Hàn Lập bái kiến Tông Chủ Thanh Vân, rời khỏi Thanh Vân Tông. Họ Hàn Quốc cũng biết Hàn Lập.",
        )

    def test_post_replace_respects_word_boundaries_for_latin(self):
        rules = [{"find": "Lập", "replace": "Lập Ca", "stage": "post"}]
        self.assertEqual(apply_post_replace("Hàn Lập lập tức đi.", {}, rules), "Hàn Lập Ca Lập Ca tức đi.")
        self.assertEqual(apply_post_replace("Độc lập tự do.", {}, rules), "Độc Lập Ca tự do.")

        rules_exact = [{"find": "Hàn Đứng", "replace": "Hàn Lập", "stage": "post"}]
        self.assertEqual(apply_post_replace("Hàn Đứng1 không đổi, Hàn Đứng đổi.", {}, rules_exact), "Hàn Đứng1 không đổi, Hàn Lập đổi.")

    def test_group_broken_cues_and_proportional_split(self):
        cues = [
            srt.Subtitle(1, timedelta(seconds=1.0), timedelta(seconds=2.0), "我們現在"),
            srt.Subtitle(2, timedelta(seconds=2.1), timedelta(seconds=3.2), "必須馬上去"),
            srt.Subtitle(3, timedelta(seconds=3.3), timedelta(seconds=4.8), "找師兄幫忙。"),
            srt.Subtitle(4, timedelta(seconds=5.0), timedelta(seconds=6.5), "好，走吧！"),
            srt.Subtitle(5, timedelta(seconds=8.0), timedelta(seconds=9.5), "快點跟上"),
        ]
        groups = group_broken_cues(cues)
        self.assertEqual(len(groups), 3)
        self.assertEqual([c.index for c in groups[0]], [1, 2, 3])
        self.assertEqual(join_cues_text(groups[0]), "我們現在必須馬上去找師兄幫忙。")

        pieces = split_translation_for_cues("Chúng ta bây giờ phải lập tức đi tìm sư huynh giúp đỡ.", groups[0])
        self.assertIsNotNone(pieces)
        self.assertEqual(len(pieces), 3)
        self.assertTrue(all(p.strip() for p in pieces))
        self.assertEqual(" ".join(pieces), "Chúng ta bây giờ phải lập tức đi tìm sư huynh giúp đỡ.")

    def test_translate_units_resilient_uses_binary_split_when_markers_missing(self):
        calls = []

        def fake_google(payload: str) -> str:
            calls.append(payload)
            lines = payload.splitlines()
            # Force mismatch on multi-line batch >= 3 so binary splitting is exercised.
            if len(lines) >= 3:
                return "merged into one line without markers"
            return "\n".join(
                f"XQ{i:03d}X Dịch_{line.split(' ', 1)[1]}"
                for i, line in enumerate(lines)
            )

        out = translate_units_resilient(
            ["câu 1", "câu 2", "câu 3", "câu 4"],
            translate_fn=fake_google,
            batch_size=4,
            sleep_sec=0,
        )
        self.assertEqual(out, ["Dịch_câu 1", "Dịch_câu 2", "Dịch_câu 3", "Dịch_câu 4"])
        # 1 full batch (4) + 2 half batches (2 + 2) = 3 calls, NOT 1 + 4 = 5 single calls.
        self.assertEqual(len(calls), 3)

    def test_translate_srt_with_glossary_merging_and_resume_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            glossary_file = root / "custom_glossary.json"
            save_glossary({"rules": [{"zh": "韩立", "vi": "Hàn Lập"}]}, glossary_file)

            zh_srt = root / "part_01.zh.srt"
            vi_srt = root / "part_01.vi.srt"
            zh_srt.write_text(
                srt.compose(
                    [
                        srt.Subtitle(1, timedelta(seconds=0), timedelta(seconds=1.2), "韩立現在"),
                        srt.Subtitle(2, timedelta(seconds=1.3), timedelta(seconds=2.8), "必須離開這裡。"),
                        srt.Subtitle(3, timedelta(seconds=3.5), timedelta(seconds=5.0), "師兄快走！"),
                        srt.Subtitle(4, timedelta(seconds=6.0), timedelta(seconds=7.5), "不要回頭。"),
                    ]
                ),
                encoding="utf-8",
            )

            seen_batches = []
            fail_on_second_batch = True

            def fake_gtx(text: str, source: str = "zh-CN", target: str = "vi") -> str:
                seen_batches.append(text)
                if fail_on_second_batch and "師兄" in text:
                    raise RuntimeError("429 simulated")
                out_lines = []
                for line in text.splitlines():
                    prefix = ""
                    body = line
                    if line.startswith("XQ"):
                        prefix, body = line.split(" ", 1)
                        prefix += " "
                    if "XGLOSS" in body:
                        tok = next(w for w in body.split() if w.startswith("XGLOSS"))
                        out_lines.append(f"{prefix}{tok} bây giờ phải rời khỏi nơi này.")
                    elif "師兄" in body:
                        out_lines.append(f"{prefix}Sư huynh mau đi!")
                    else:
                        out_lines.append(f"{prefix}Đừng quay đầu lại.")
                return "\n".join(out_lines)

            with (
                patch.object(audio, "_google_gtx_translate", side_effect=fake_gtx),
                patch("deep_translator.GoogleTranslator", None),
                patch("core.glossary_translator._sleep_checking_stop"),
            ):
                # batch_size=1 group per call -> group 0 succeeds & caches, group 1 fails after retries.
                with self.assertRaisesRegex(RuntimeError, "lưu tạm"):
                    audio.translate_srt(
                        str(zh_srt),
                        str(vi_srt),
                        batch_size=1,
                        sleep_sec=0,
                        glossary_path=str(glossary_file),
                    )
                cache_file = vi_srt.with_name(vi_srt.name + ".translate_cache.json")
                self.assertTrue(cache_file.is_file())

                # Resume: group 0 must NOT be translated again!
                fail_on_second_batch = False
                seen_batches.clear()
                progress_events = []
                audio.translate_srt(
                    str(zh_srt),
                    str(vi_srt),
                    batch_size=1,
                    sleep_sec=0,
                    glossary_path=str(glossary_file),
                    progress_callback=lambda done, total: progress_events.append((done, total)),
                )

            self.assertEqual(len(seen_batches), 2)  # Only group 1 and group 2 remained.
            self.assertFalse(cache_file.exists())
            parsed_vi = list(srt.parse(vi_srt.read_text(encoding="utf-8")))
            self.assertEqual(len(parsed_vi), 4)
            self.assertIn("Hàn Lập", parsed_vi[0].content)
            self.assertTrue(all(c.content.strip() for c in parsed_vi))
            self.assertEqual(progress_events[-1], (4, 4))

    def test_sampling_and_gemini_extract_and_gui_endpoints(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            glossary_file = root / "custom_glossary.json"
            output_dir = root / "output"
            p1 = output_dir / "Show" / "Phan_01" / ".work"
            p2 = output_dir / "Show" / "Phan_02" / ".work"
            p1.mkdir(parents=True)
            p2.mkdir(parents=True)
            (p1 / "ep1.zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n韩立来了\n", encoding="utf-8")
            (p2 / "ep2.zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n青云宗大长老\n", encoding="utf-8")

            sample = build_glossary_sample_text([p1 / "ep1.zh.srt", p2 / "ep2.zh.srt"], max_chars=500)
            self.assertIn("韩立来了", sample)
            self.assertIn("青云宗大长老", sample)

            fake_gemini_resp = json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": '```json\n{"rules": [{"zh": "韩立", "vi": "Hàn Lập", "type": "name"}]}\n```'}
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return fake_gemini_resp

            with patch("urllib.request.urlopen", return_value=_Resp()):
                extracted = extract_glossary_with_gemini(sample, api_key="test-key", model="gemini-2.5-flash")
            self.assertEqual(extracted, [{"zh": "韩立", "vi": "Hàn Lập", "type": "name", "stage": "both"}])

            # Test GUI endpoints
            state = gui.PipelineState()
            state.add_log = Mock()
            state.srt_rows = [{"index": 1, "start": "00:00:00,000", "end": "00:00:01,000", "zh_text": "韩立", "vi_text": "Hàn Đứng đi"}]
            with (
                patch.object(gui, "GLOSSARY_PATH", glossary_file),
                patch.object(gui, "OUTPUT_DIR", output_dir),
                patch.object(gui, "STATE", state),
            ):
                handler = gui.GuiRequestHandler.__new__(gui.GuiRequestHandler)
                handler._send_json = Mock()
                handler.path = "/api/glossary/save"
                handler._read_json_body = Mock(
                    return_value={
                        "raw_json": '```json\n{"rules": [{"zh": "韩立", "vi": "Hàn Lập"}, {"find": "Hàn Đứng", "replace": "Hàn Lập", "stage": "post"}]}\n```',
                        "merge": True,
                    }
                )
                handler._dispatch_POST()
                saved_resp = handler._send_json.call_args.args[0]
                self.assertTrue(saved_resp["ok"])
                self.assertEqual(len(saved_resp["rules"]), 2)
                self.assertEqual(len(load_glossary(glossary_file)["rules"]), 2)

                handler.path = "/api/glossary/apply-to-rows"
                handler._read_json_body = Mock(return_value={"srt_rows": state.srt_rows})
                handler._dispatch_POST()
                applied_resp = handler._send_json.call_args.args[0]
                self.assertEqual(applied_resp["changed"], 1)
                self.assertEqual(applied_resp["srt_rows"][0]["vi_text"], "Hàn Lập đi")

                handler.path = "/api/glossary/starter"
                handler._read_json_body = Mock(return_value={})
                handler._dispatch_POST()
                starter_resp = handler._send_json.call_args.args[0]
                self.assertTrue(starter_resp["ok"])
                self.assertGreater(starter_resp["added"], 10)

                handler.path = "/api/glossary/prompt"
                handler._read_json_body = Mock(return_value={})
                handler._dispatch_POST()
                prompt_resp = handler._send_json.call_args.args[0]
                self.assertTrue(prompt_resp["ok"])
                self.assertIn("韩立来了", prompt_resp["prompt"])

                with patch("urllib.request.urlopen", return_value=_Resp()):
                    handler.path = "/api/glossary/extract-gemini"
                    handler._read_json_body = Mock(return_value={"api_key": "test-key", "model": "gemini-2.5-flash"})
                    handler._dispatch_POST()
                ext_resp = handler._send_json.call_args.args[0]
                self.assertTrue(ext_resp["ok"])
                self.assertEqual(ext_resp["extracted"], 1)

                handler.path = "/api/glossary"
                handler.do_GET()
                get_resp = handler._send_json.call_args.args[0]
                self.assertTrue(get_resp["ok"])
                self.assertGreater(len(get_resp["rules"]), 10)

    def test_merge_glossary_rules_deduplicates(self):
        existing = [{"zh": "韩立", "vi": "Hàn Đứng", "stage": "both"}]
        incoming = [
            {"zh": "韩立", "vi": "Hàn Lập", "stage": "both"},
            {"zh": "厉飞雨", "vi": "Lệ Phi Vũ", "stage": "both"},
        ]
        merged, added = merge_glossary_rules(existing, incoming)
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["vi"], "Hàn Lập")


if __name__ == "__main__":
    unittest.main()
