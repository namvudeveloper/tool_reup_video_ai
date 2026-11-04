@echo off
chcp 65001 >nul
echo ============================================================
echo   🎬 MỞ DỰ ÁN CAPCUT: Kẻ_Đi_Bộ_Trong_Bóng_Tối (8.5 TIẾNG)
echo ============================================================
echo.

:: 1. Chạy cập nhật dự án vào CapCut
call .venv\Scripts\python.exe tao_du_an_capcut.py

echo.
echo 📂 Đang mở thư mục chứa Video và Phụ đề gộp...
start explorer.exe "d:\tool\tool_reup_video_ai\output\Kẻ_Đi_Bộ_Trong_Bóng_Tối"

echo 🚀 Đang khởi động CapCut...
start "" "%LOCALAPPDATA%\CapCut\Apps\9.7.0.4153\CapCut.exe"

echo.
echo ✅ ĐÃ XONG!
echo Trong CapCut, bạn sẽ thấy ngay dự án: "Kẻ_Đi_Bộ_Trong_Bóng_Tối" ở đầu danh sách.
echo Bấm vào dự án để xem video và toàn bộ 12,837 câu phụ đề đã được xếp sẵn trên timeline!
echo.
pause
