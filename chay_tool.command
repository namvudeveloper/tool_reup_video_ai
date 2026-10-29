#!/bin/bash
# File chạy 1-click mở Giao Diện Trực Quan trên macOS (Nhấp đúp chuột trực tiếp từ Finder)

cd "$(dirname "$0")" || exit 1

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONIOENCODING="utf-8"

echo "========================================================================"
echo "  🎬 TOOL GHÉP VIDEO 5 TIẾNG & LÁCH BẢN QUYỀN (GIAO DIỆN TRỰC QUAN)"
echo "========================================================================"
echo ""

# 1. Kiểm tra Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[LỖI] Máy Mac của bạn chưa cài đặt Python 3!"
    echo "👉 Hãy mở Terminal và chạy: brew install python"
    echo ""
    read -n 1 -s -r -p "Nhấn phím bất kỳ để đóng cửa sổ..."
    exit 1
fi

# 2. Kiểm tra FFmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "[CẢNH BÁO] Chưa tìm thấy FFmpeg trên máy Mac."
    if command -v brew >/dev/null 2>&1; then
        echo "[INFO] Đang tự động cài đặt FFmpeg qua Homebrew..."
        brew install ffmpeg
    else
        echo "👉 Vui lòng cài đặt Homebrew và chạy lệnh: brew install ffmpeg"
        echo ""
        read -n 1 -s -r -p "Nhấn phím bất kỳ để đóng cửa sổ..."
        exit 1
    fi
fi

# 3. Khởi tạo môi trường Python (.venv) nếu có mạng
if [ ! -f ".venv/bin/python" ]; then
    python3 -m venv .venv >/dev/null 2>&1 || true
fi

PY_BIN="python3"
if [ -f ".venv/bin/python" ]; then
    PY_BIN=".venv/bin/python"
    if [ ! -f ".venv/.deps_installed_mac" ]; then
        echo "[INFO] Đang kiểm tra / cài đặt thư viện hỗ trợ trên macOS..."
        "$PY_BIN" -m pip install -r requirements.txt -q >/dev/null 2>&1 && touch .venv/.deps_installed_mac || true
    fi
fi

# 4. Mặc định mở Giao Diện Kéo Thả (GUI) cho dễ dùng, trừ khi truyền --cli
if [ "$1" = "--cli" ]; then
    shift
    "$PY_BIN" main.py "$@"
else
    "$PY_BIN" gui_server.py "$@"
    rc=$?
    if [ $rc -ne 0 ]; then
        echo ""
        echo "❌ Tool đã dừng với mã lỗi: $rc"
        echo "Vui lòng chụp lại thông báo lỗi ở trên để được hỗ trợ."
        echo ""
        read -n 1 -s -r -p "Nhấn phím bất kỳ để đóng cửa sổ..."
    fi
fi
