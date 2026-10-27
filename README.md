# 🎬 AUTO VIDEO AGGREGATOR & ANTI-COPYRIGHT PIPELINE (macOS & Windows)

Hệ thống tự động hóa tải video chất lượng cao (Raw 1080p/4K), xử lý lách bản quyền hình ảnh & âm thanh (Bypass Content ID), chuẩn hóa định dạng và ghép nối hàng loạt tập phim thành **video tổng hợp dài 3 – 5 tiếng** sắc nét.

Hỗ trợ vận hành **1-Click** trên cả **Windows** (`chay_tool.bat`) và **macOS** (`chay_tool.command`).

---

## 📌 PHẦN 1: HƯỚNG DẪN SỬ DỤNG GIAO DIỆN KÉO THẢ (DỄ NHẤT CHO NGƯỜI MỚI)

Tool đã được trang bị **Giao Diện Trực Quan Tiếng Việt (Drag & Drop Studio)**, chỉ cần làm đúng **3 bước trên màn hình**:

### Bước 1: Mở Giao Diện (Chỉ cần nhấp đúp chuột)
* **Trên macOS (MacBook / Mac mini / Mac Studio):** Nhấp đúp chuột vào file **`chay_tool.command`**.
* **Trên Windows:** Nhấp đúp chuột vào file **`chay_tool.bat`**.
* Cửa sổ **Giao Diện Ghép Video 5 Tiếng** sẽ tự động bật lên trên màn hình.

### Bước 2: Kéo & Thả Các Tập Phim Vào Giao Diện
* **Cách 1 (Kéo thả trực tiếp):** Bôi đen 20 – 50 tập phim ngoài màn hình máy tính rồi **kéo thả thẳng vào ô Bước 1** trên giao diện.
* **Cách 2 (Chọn cả thư mục):** Bấm nút tím **`📁 Chọn Nguyên Cả Thư Mục Phim`** hoặc nút xanh **`📂 Chọn Nhiều Tập Phim`**, máy sẽ tự động nạp toàn bộ các tập và **tự sắp xếp đúng thứ tự Tập 1 ➔ Tập Cuối**.
* **Cách 3 (Dán link mạng):** Bấm **`🔗 Dán Link`** nếu muốn tải trực tiếp từ Bilibili / YouTube / Douyin.

### Bước 3: Kiểm Tra Chia Phần (Chunk) 5 Tiếng & Bấm Xuất Video
* Ngay khi thả phim vào, **Thanh Đo Mục Tiêu 5 Tiếng** sẽ tự động cộng thời lượng từng tập (trừ đi số giây cắt đầu/cuối nếu có) và **tự động chia thành từng Phần (Chunk) chuẩn 5 tiếng**:
  * Ví dụ thả vào 35 tập phim ➔ Máy tự động chia:
    * 📦 **Phần 1:** Tập 1 ➔ Tập 16 (`5 giờ 04 phút`) ➔ Xuất ra `output/Ten_Phim_Phan_01.mp4`
    * 📦 **Phần 2:** Tập 17 ➔ Tập 32 (`5 giờ 04 phút`) ➔ Xuất ra `output/Ten_Phim_Phan_02.mp4`
* Bấm nút xanh lá siêu to **`🚀 BẮT ĐẦU GHÉP VIDEO NGAY`**.
* Khi chạy xong, bấm nút **`📂 Mở Thư Mục Lấy Video (output/)`** ngay góc phải trên cùng để lấy video đăng kênh!

---

## ⚙️ PHẦN 2: ĐẶC TẢ KỸ THUẬT (TECHNICAL SPECIFICATIONS)

### 1. Sơ đồ kiến trúc Pipeline 3 Bước

```
[ Nhập danh sách link video trong config.json ] 
                      ↓
  [ Bước 1: Tải video raw chất lượng cao (yt-dlp) ]  ──► Lưu tạm vào raw/ep_001.mp4...
                      ↓
  [ Bước 2: Chuẩn hóa 1080p & Lách bản quyền (GPU) ] ──► Lưu tạm vào temp_processed/norm_001.mp4...
                      ↓
  [ Bước 3: Nối liền mạch siêu tốc (Concat Copy) ]   ──► Xuất file output/<project_name>.mp4
                      ↓
  [ Tự động xóa file tạm (raw/ & temp_processed/) ]
```

### 2. Cơ chế xử lý kỹ thuật ngầm ở từng bước

1. **Bước 1 – Tải Video Raw (`core/downloader.py`):**
   * Tự động chọn luồng video có độ phân giải cao nhất (`bestvideo[height<=2160]+bestaudio`) và đóng gói `.mp4`.
   * Có cơ chế **Resume thông minh**: Nếu đang tải tập thứ 15 mà rớt mạng, khi bấm chạy lại tool sẽ bỏ qua 14 tập đã tải xong và tiếp tục ngay từ tập 15.
   * Hỗ trợ truyền `cookies_from_browser` (`"chrome"`, `"edge"`, `"safari"`, `"firefox"`) để tải luồng 1080p60/4K yêu cầu đăng nhập trên Bilibili/Douyin.

2. **Bước 2 – Chuẩn hóa & Lách bản quyền Content ID (`core/processor.py`):**
   * **Cắt bỏ Intro / Outro (`trim_start_sec`, `trim_end_sec`):** Tự động đo thời lượng từng tập bằng `ffprobe` và cắt chính xác số giây mở đầu / kết thúc của mỗi tập lẻ.
   * **Phóng to viền (`zoom_factor: 1.02`):** Phóng nhẹ 2% từ tâm và nội suy `lanczos` về chuẩn `1920x1080` để loại bỏ viền rác và thay đổi ma trận điểm ảnh.
   * **Cân chỉnh màu sắc (`brightness`, `contrast`, `saturation`):** Dịch chuyển nhẹ độ sáng, độ tương phản và độ bão hòa màu để mắt thường thấy hình ảnh trong trẻo hơn nhưng mã băm khung hình (Video Hash) khác hoàn toàn bản gốc.
   * **Chuẩn hóa đồng nhất:** Ép toàn bộ các tập về cùng độ phân giải `1920x1080`, cùng tốc độ khung hình (`30fps` hoặc `60fps`), chuẩn màu `yuv420p`, `timescale 90000` và âm thanh `AAC 48000Hz Stereo` chuẩn hóa âm lượng `loudnorm` (`-16 LUFS`).
   * **Xóa sạch Metadata gốc (`-map_metadata -1 -map_chapters -1`):** Xóa toàn bộ thông tin chữ ký file gốc.

3. **Bước 3 – Ghép nối siêu tốc & Dọn rác (`core/concatenator.py`):**
   * Nhờ Bước 2 đã chuẩn hóa 100% thông số kỹ thuật của mọi tập, Bước 3 sử dụng `FFmpeg Concat Demuxer (-c copy)` giúp ghép 10 – 20 tập (dài 3 – 5 tiếng) chỉ trong **vài chục giây đến vài phút** mà không làm giảm chất lượng hình ảnh.
   * Tự động dọn sạch thư mục tạm `raw/` và `temp_processed/` sau khi xuất file thành công để giải phóng ổ cứng.

### 3. Tăng tốc phần cứng đa nền tảng (GPU Hardware Acceleration)

Tool tự động nhận diện hệ điều hành và kiểm tra thực tế card đồ họa trên máy (`core/system_check.py`):
* **Trên Windows (NVIDIA RTX/GTX):** Tự động kích hoạt `h264_nvenc`.
* **Trên Windows (AMD / Intel):** Tự động kích hoạt `h264_amf` hoặc `h264_qsv`.
* **Trên macOS (Apple Silicon M1/M2/M3/M4 & Mac Intel):** Tự động kích hoạt `h264_videotoolbox`.
* **Chế độ dự phòng (Fallback):** Tự động chuyển về `libx264` đa luồng trên CPU nếu máy không có GPU rời.

---

## 🛠️ PHẦN 3: BẢNG THÔNG SỐ CẤU HÌNH NÂNG CAO (`config.json`)

Ngoài `"project_name"` và `"links"`, bạn có thể tùy chỉnh thêm trong mục `"settings"` của [`config.json`](config.json):

| Thông số | Mặc định | Ý nghĩa |
| :--- | :---: | :--- |
| `resolution` | `"1920x1080"` | Độ phân giải đầu ra chuẩn Full HD (`"1920x1080"` hoặc `"2560x1440"`). |
| `fps` | `30` | Tốc độ khung hình đồng nhất (`30` hoặc `60`). |
| `video_bitrate` | `"8M"` | Bitrate video đảm bảo độ nét cao khi đăng YouTube. |
| `gpu_acceleration` | `"auto"` | `"auto"` (tự nhận GPU Mac/Windows), `"nvenc"`, `"videotoolbox"`, hoặc `"cpu"`. |
| `trim_start_sec` | `0` | Số giây cắt bỏ ở đầu mỗi tập phim (Intro). |
| `trim_end_sec` | `0` | Số giây cắt bỏ ở cuối mỗi tập phim (Outro). |
| `anti_copyright.zoom_factor` | `1.02` | Tỉ lệ phóng to viền (`1.02` = phóng to 2%). |
| `anti_copyright.brightness` | `0.015` | Độ sáng cộng thêm nhẹ (`-0.05` đến `0.05`). |
| `anti_copyright.contrast` | `1.03` | Độ tương phản (`1.0` là giữ nguyên). |
| `anti_copyright.saturation` | `1.04` | Độ tươi màu sắc (`1.0` là giữ nguyên). |
| `anti_copyright.speed_factor` | `1.0` | Tốc độ phát (`1.02` = nhanh hơn 2% để lách cả âm thanh lẫn hình ảnh). |
| `anti_copyright.flip_horizontal` | `false` | Đặt `true` nếu muốn lật ngang khung hình. |
| `audio_normalize` | `true` | Tự động cân bằng âm lượng đồng đều giữa tất cả các tập. |
| `clean_temp_after_done` | `true` | Tự động xóa file tạm sau khi xuất xong video tổng hợp. |
| `cookies_from_browser` | `""` | Nhập `"chrome"`, `"edge"`, hoặc `"safari"` nếu cần lấy cookie tải video VIP. |

---

## ⚠️ 4. Lưu Ý Quan Trọng Khi Vận Hành

1. **Dung lượng ổ cứng:** Một dự án video 5 tiếng kèm file raw có thể chiếm từ `15 GB – 30 GB`. Hãy đảm bảo ổ đĩa còn trống ít nhất **`50 GB`**.
2. **Đường truyền mạng:** Khuyến khích sử dụng mạng dây LAN hoặc Wi-Fi ổn định để quá trình tải raw 1080p/4K diễn ra nhanh nhất.
