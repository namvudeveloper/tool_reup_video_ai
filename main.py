import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from core.concatenator import concatenate_videos
from core.downloader import download_all_videos
from core.logger import (
    RICH_AVAILABLE,
    Panel,
    console,
    log_error,
    log_info,
    log_step,
    log_success,
    log_warn,
    print_banner,
)
from core.processor import process_all_videos
from core.system_check import verify_environment

DEFAULT_SETTINGS: Dict[str, Any] = {
    "resolution": "1920x1080",
    "fps": 30,
    "video_bitrate": "8M",
    "gpu_acceleration": "auto",
    "trim_start_sec": 0,
    "trim_end_sec": 0,
    "anti_copyright": {
        "enabled": True,
        "zoom_factor": 1.02,
        "brightness": 0.015,
        "contrast": 1.03,
        "saturation": 1.04,
        "speed_factor": 1.0,
        "flip_horizontal": False,
        "pitch_shift": 1.0,
    },
    "audio_normalize": True,
    "clean_temp_after_done": True,
    "cookies_from_browser": "",
    "max_retries": 3,
}


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy file cấu hình tại: {config_path}\n"
            "Vui lòng tạo file config.json theo đúng hướng dẫn sử dụng."
        )
    try:
        raw_text = config_path.read_text(encoding="utf-8-sig")
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"File config.json bị sai cú pháp JSON (thiếu dấu phẩy hoặc dấu ngoặc kép): {exc}"
        ) from exc

    project_name = str(data.get("project_name", "Video_Tong_Hop_Full")).strip()
    links = data.get("links", [])
    if not isinstance(links, list):
        raise ValueError("Mục 'links' trong config.json phải là một danh sách (mảng [...]).")

    merged_settings = dict(DEFAULT_SETTINGS)
    user_settings = data.get("settings", {})
    if isinstance(user_settings, dict):
        for k, v in user_settings.items():
            if k == "anti_copyright" and isinstance(v, dict):
                ac = dict(DEFAULT_SETTINGS["anti_copyright"])
                ac.update(v)
                merged_settings["anti_copyright"] = ac
            else:
                merged_settings[k] = v

    return {
        "project_name": project_name,
        "links": [str(item).strip() for item in links if str(item).strip()],
        "settings": merged_settings,
    }


def _is_placeholder_link(link: str) -> bool:
    lower = link.lower()
    return "bv1xxxxxx" in lower or "example.com" in lower or "your_link_here" in lower


def generate_demo_samples(ffmpeg_path: str, demo_dir: Path) -> List[str]:
    """
    Tạo 3 tập video mẫu (1080p có cả hình ảnh chuyển động và âm thanh)
    để kiểm tra toàn bộ dây chuyền sản xuất trên máy Mac / Windows.
    """
    demo_dir.mkdir(parents=True, exist_ok=True)
    demo_files: List[str] = []
    colors = [("darkblue", 440), ("darkgreen", 523), ("darkred", 659)]

    for idx, (color, freq) in enumerate(colors, start=1):
        out_path = demo_dir / f"sample_ep_{idx:02d}.mp4"
        cmd = [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1920x1080:rate=30:duration=4",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:sample_rate=48000:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
        demo_files.append(str(out_path))

    return demo_files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tool Tự Động Hóa Gộp Video & Lách Bản Quyền (macOS & Windows)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Đường dẫn tới file cấu hình JSON (mặc định: config.json)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Giữ lại các file tạm trong thư mục raw/ và temp_processed/ sau khi xuất xong",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Chạy chế độ kiểm thử tự động với 3 tập video mẫu tự sinh",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    config_path = (project_root / args.config).resolve()

    print_banner()
    start_time = time.time()

    try:
        cfg = load_config(config_path)
        settings = cfg["settings"]
        if args.keep_temp:
            settings["clean_temp_after_done"] = False

        env_info = verify_environment(
            project_root=project_root,
            gpu_pref=str(settings.get("gpu_acceleration", "auto")),
        )

        raw_dir = project_root / "raw"
        processed_dir = project_root / "temp_processed"
        output_dir = project_root / "output"

        links: List[str] = cfg["links"]
        project_name: str = cfg["project_name"]

        if args.demo:
            log_info("Đang khởi tạo 3 tập video mẫu (Full HD 1080p) để kiểm thử dây chuyền...")
            demo_dir = project_root / "temp_demo_inputs"
            links = generate_demo_samples(env_info["ffmpeg"], demo_dir)
            project_name = f"{project_name}_DEMO"

        if not links:
            log_error("Danh sách 'links' trong file config.json đang trống!")
            log_info("👉 Hãy mở file config.json, dán các link video cần ghép vào mục 'links' rồi chạy lại.")
            return 1

        placeholder_links = [lnk for lnk in links if _is_placeholder_link(lnk)]
        if placeholder_links and not args.demo:
            log_warn(
                "Phát hiện link mẫu (BV1xxxxxx...) trong file config.json chưa được thay bằng link thật!"
            )
            log_info(
                "👉 Bước 1: Mở file 'config.json' bằng Notepad (Windows) hoặc TextEdit (Mac).\n"
                "👉 Bước 2: Thay các dòng 'https://www.bilibili.com/video/BV1xxxxxx1' bằng link video thật (YouTube, Bilibili, Douyin...) hoặc đường dẫn file .mp4 trên máy.\n"
                "👉 Bước 3: Lưu file lại (Ctrl+S hoặc Cmd+S) và bấm chạy lại tool.\n"
                "💡 Mẹo: Nếu bạn muốn chạy thử nghiệm kiểm tra máy ngay lập tức, hãy chạy lệnh: python main.py --demo"
            )
            return 1

        log_info(f"Tên dự án xuất file : {project_name}.mp4")
        log_info(f"Tổng số tập cần ghép : {len(links)} tập")
        log_info(
            f"Chuẩn đầu ra        : {settings['resolution']} @ {settings['fps']}fps | "
            f"Lách bản quyền: {'BẬT' if settings['anti_copyright'].get('enabled', True) else 'TẮT'}"
        )

        # BƯỚC 1: TẢI VIDEO RAW CHẤT LƯỢNG CAO
        log_step(1, 3, "Tải video raw chất lượng cao (1080p/4K)")
        raw_files = download_all_videos(
            links=links,
            raw_dir=raw_dir,
            project_root=project_root,
            ffmpeg_path=env_info["ffmpeg"],
            settings=settings,
        )

        # BƯỚC 2: CHUẨN HÓA ĐỊNH DẠNG & LÁCH BẢN QUYỀN TỪNG TẬP
        log_step(2, 3, "Chuẩn hóa khung hình 1080p, âm thanh & Lách bản quyền")
        processed_files = process_all_videos(
            raw_files=raw_files,
            processed_dir=processed_dir,
            ffmpeg_path=env_info["ffmpeg"],
            ffprobe_path=env_info["ffprobe"],
            encoder=env_info["encoder"],
            settings=settings,
        )

        # BƯỚC 3: GHÉP NỐI LIỀN MẠCH THÀNH VIDEO SIÊU DÀI & DỌN RÁC
        log_step(3, 3, "Nối liền mạch toàn bộ các tập & Xuất file thành phẩm")
        final_video = concatenate_videos(
            processed_files=processed_files,
            output_dir=output_dir,
            project_name=project_name,
            ffmpeg_path=env_info["ffmpeg"],
            ffprobe_path=env_info["ffprobe"],
            raw_dir=raw_dir,
            processed_dir=processed_dir,
            clean_temp=bool(settings.get("clean_temp_after_done", True)),
        )

        if args.demo:
            import shutil

            demo_dir = project_root / "temp_demo_inputs"
            if demo_dir.exists():
                shutil.rmtree(demo_dir, ignore_errors=True)

        elapsed = time.time() - start_time
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)

        if RICH_AVAILABLE:
            console.print()
            console.print(
                Panel.fit(
                    f"[bold green]🎉 [HOÀN THÀNH] QUÁ TRÌNH XỬ LÝ VÀ GHÉP VIDEO ĐÃ XONG![/bold green]\n\n"
                    f"📂 File thành phẩm : [bold yellow]{final_video}[/bold yellow]\n"
                    f"⏱️  Tổng thời gian  : [bold cyan]{mins} phút {secs} giây[/bold cyan]\n"
                    f"🚀 Trạng thái      : Sẵn sàng đăng tải lên YouTube / Facebook / TikTok",
                    border_style="green",
                    padding=(1, 2),
                )
            )
        else:
            print("\n" + "=" * 72)
            print("🎉 [HOÀN THÀNH] QUÁ TRÌNH XỬ LÝ VÀ GHÉP VIDEO ĐÃ XONG!")
            print(f"📂 File thành phẩm : {final_video}")
            print(f"⏱️  Tổng thời gian  : {mins} phút {secs} giây")
            print("=" * 72)

        return 0

    except KeyboardInterrupt:
        log_warn("\nĐã dừng chương trình theo yêu cầu của người dùng (Ctrl+C).")
        return 130
    except Exception as exc:
        log_error(f"Quá trình xử lý bị gián đoạn: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
