#!/usr/bin/env python3
"""
chuan_hoa_sub.py
----------------
Chuẩn hóa và làm sạch toàn bộ phụ đề Tiếng Việt (.vi.srt) cho bộ phim:
"Kẻ Đi Bộ Trong Bóng Tối" (赦夜人 - Xá Dạ Nhân):
  1. Thống nhất tên gọi nhân vật chuẩn nguyên tác:
     - Trần Yến (陈彦 / 陈晏 - Chén Yàn): nhân vật chính, thay cho Chen Yan, Chen Ye, Trần Diệp, Anh Yan, Anh Xiaoyan, buổi sáng và buổi tối.
     - Hoắc Khuê (霍奎 / Huò Kuí): mentor / thủ lĩnh Bất Lưu, thay cho Hứa Khôi, Hoắc Khôi, Anh Kui, Anh Quỳ, Anh Quế, Anh Cối, Anh Khôi.
     - Bùi Dũng (裴勇 / Péi Yǒng): ông chủ Lầu Trạng Nguyên, thay cho Pei Yong, Bae Yong, Anh Yong, Yong Ge, Anh Pei, Ông chủ Pei.
     - Ngụy Kinh (魏京 / Wèi Jīng): cộng sự thân cận, thay cho Anh Wei, Wei Jing, Vệ Kinh.
     - Sơ Sơ (初初 / 楚楚): con gái Trần Yến, thay cho Chuchu, chuchu, Chu Chu.
     - Nhiếp Tiểu Khả (聂小可) & Nhiếp Húc (聂旭): thay cho Xiaoke, Nie Xiaoke, Nie Xu, Nhiếp Xu.
     - Lâm Bội Nhã (林佩雅) & Lâm Thành chủ (林城主): thay cho Peiya, Lin Peiya, Chengzhu, Lin Chengzhu, cô Lin, Lin tiểu thư.
     - Tôn Đại Triển (孙大展): đội trưởng cựu Mục Quang Giả, thay cho Sun Dazhan, Sun Da Zhao, Sun Zhanzhan, Tôn Đại Chiến, anh Sun.
     - Phùng Thanh (冯青): thay cho Feng Qing.
     - A Siêu (阿超): thay cho Ah Chao, A Chao, Achao.
     - Yến Tử (燕子): thay cho Yanzi, con én (khi nói về nhân vật).
     - Lạc Kiều Kiều (洛娇娇): thay cho Jiaojiao, Chị Tiêu Tiêu, Chị Tiểu Tiểu.
     - Chị Diêu / Diêu Diêu (姚姐 / 姚姚): thay cho Chị Yao, Chị Yao Yao.
     - Anh Phi (飞哥): thay cho anh Fei, Fei Ge.
     - Ngô Nhã (吴雅), Ngô Dương (吴阳), Trương Dương (张扬).

  2. Thống nhất tên địa danh & tổ chức:
     - Công hội Bất Lưu / Quán Bất Lưu (不留): thay cho Buliu, Bustay, Burei, Lou Buqiu, Bộ Thu, No Retention, không ở lại, người sẽ không ở lại.
     - Lầu Trạng Nguyên (壮元楼 / 状元楼): thay cho tháp Zhuangyuan, tòa nhà Zhuangyuan, tòa nhà Chuangyuan, Zhuangyuan Lou, phố Zhuangyuan.
     - Phố Đỏ (红街 / 红阶): thay cho Hongjie, Hồng Giai.
     - Thành phố Bắc Khâu (北丘市 / 北邱市): thay cho Beiqiu, thành phố Beiqiu.
     - Thành phố Trầm Tức (沉息之城): thay cho Chen Xizhi Cheng, thành phố Shen Xizhi, thành phố Chen Xizhi.
     - Thành Phi Bình (飞平城): thay cho Feiping, thành phố Feiping.
     - Núi Lăng Vương (凌王山): thay cho núi Lingwang, Lingwangshan.

  3. Thống nhất thuật ngữ mạt thế:
     - Xá Dạ Nhân (赦夜人 / 摄业人): thay cho nhiếp ảnh gia, các nhiếp ảnh gia.
     - Mục Quang Giả (目光者): thay cho những người nhìn tôi, người nhìn tôi, Gazers, những người đang xem.
     - Dạ Thải (夜采 / 夜才 / 夜彩): thay cho Yecai, Ye Cai, Ye cai.
     - Yên vật (湮物 / 严务): thay cho Yanwu, phân loại của Yanwu.
     - Dạ Kiếm (夜剑): thay cho Ye Jian.

  4. Làm sạch câu từ máy dịch thô:
     - Rút gọn tiền tệ: "... nhân dân tệ" -> "... tệ".
     - Sửa cụm vô nghĩa:
       * "sẽ không giết chết bạn" -> "không chết được đâu"
       * "mở cửa giao đồ ăn tối mai" -> "mở tuyến chở lương thực đêm mai"
       * "giấu Chen Ye dưới đống tro tàn" -> "thu nhận Trần Yến vào dưới trướng"
       * "Bà nội này có lẽ từ nay sẽ do" -> "Vụ làm ăn này từ nay có lẽ do"
       * "làm bài kiểm tra tại tòa nhà Zhuangyuan" -> "khảo nghiệm tại Lầu Trạng Nguyên"
     - Chuẩn hóa viết hoa chữ cái đầu và sửa khoảng trắng dấu câu.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Bộ chữ cái tiếng Việt và Latin
VN_LOWER = "a-zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ"
VN_UPPER = "A-ZÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÈÉẺẼẸÊẾỀỂỄỆÌÍỈĨỊÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰỲÝỶỸỴĐ"
ALL_ALPHA = f"[{VN_LOWER}{VN_UPPER}]"

# Các quy tắc thay thế theo thứ tự ưu tiên
REPLACEMENT_RULES: List[Tuple[re.Pattern, str]] = [
    # --- 1. SỬA CÁC LỖI DỊCH MÁY NẶNG / VÔ NGHĨA TRƯỚC ---
    (re.compile(r"Có chuyện xảy ra vào buổi sáng và buổi tối", re.IGNORECASE), "Trần Yến xảy ra chuyện rồi"),
    (re.compile(r"buổi sáng và buổi tối", re.IGNORECASE), "Trần Yến"),
    (re.compile(r"vào buổi sáng và buổi tối", re.IGNORECASE), "Trần Yến"),
    (re.compile(r"Trẻ em vào buổi sáng và buổi tối", re.IGNORECASE), "Bạn nhỏ của Trần Yến"),
    (re.compile(r"giấu (?:Chen Ye|Chen Yan|Trần Diệp|Trần Yến) dưới đống tro tàn", re.IGNORECASE), "thu nhận Trần Yến vào dưới trướng"),
    (re.compile(r"thu nhận (?:Chen Ye|Chen Yan|Trần Diệp) vào dưới trướng", re.IGNORECASE), "thu nhận Trần Yến vào dưới trướng"),
    (re.compile(r"Bà nội này có lẽ từ nay sẽ do", re.IGNORECASE), "Vụ làm ăn này từ nay có lẽ do"),
    (re.compile(r"mở cửa giao đồ ăn tối mai", re.IGNORECASE), "mở tuyến chở lương thực đêm mai"),
    (re.compile(r"giao đồ ăn tối mai", re.IGNORECASE), "chở lương thực đêm mai"),
    (re.compile(r"làm bài kiểm tra tại (?:tòa nhà Zhuangyuan|tháp Zhuangyuan|Lầu Trạng Nguyên)", re.IGNORECASE), "khảo nghiệm tại Lầu Trạng Nguyên"),
    (re.compile(r"sẽ không giết chết bạn", re.IGNORECASE), "không chết được đâu"),
    (re.compile(r"sẽ không giết chết người", re.IGNORECASE), "không chết được đâu"),
    (re.compile(r"giết chết bạn", re.IGNORECASE), "chết được đâu"),

    # --- 2. XÁ DẠ NHÂN (赦夜人 / 摄业人 - bị dịch nhầm thành nhiếp ảnh gia) ---
    (re.compile(r"\bcác nhiếp ảnh gia\b", re.IGNORECASE), "các Xá Dạ Nhân"),
    (re.compile(r"\bnhững nhiếp ảnh gia\b", re.IGNORECASE), "những Xá Dạ Nhân"),
    (re.compile(r"\bNhiếp ảnh gia\b"), "Xá Dạ Nhân"),
    (re.compile(r"\bnhiếp ảnh gia\b"), "Xá Dạ Nhân"),

    # --- 3. MỤC QUANG GIẢ (目光者 - lực lượng tuần tra có nguồn sáng) ---
    (re.compile(r"những người nhìn tôi", re.IGNORECASE), "Mục Quang Giả"),
    (re.compile(r"những người nhìn bạn", re.IGNORECASE), "Mục Quang Giả"),
    (re.compile(r"Những người nhìn tôi"), "Mục Quang Giả"),
    (re.compile(r"người nhìn tôi", re.IGNORECASE), "Mục Quang Giả"),
    (re.compile(r"người nhìn đến cửa", re.IGNORECASE), "Mục Quang Giả tìm tới cửa"),
    (re.compile(r"những người nhìn", re.IGNORECASE), "Mục Quang Giả"),
    (re.compile(r"những người đang xem", re.IGNORECASE), "Mục Quang Giả"),
    (re.compile(r"\bGazers\b"), "Mục Quang Giả"),
    (re.compile(r"\bGazer\b"), "Mục Quang Giả"),

    # --- 4. CÔNG HỘI / QUÁN BAR BẤT LƯU (不留 - bị dịch thành Buliu, Bustay, không ở lại...) ---
    (re.compile(r"Đừng rời khỏi quán bar để tìm tôi", re.IGNORECASE), "Đến quán bar Bất Lưu tìm tôi"),
    (re.compile(r"Chủ tịch Hoắc Quỳ sẽ không được giữ lại", re.IGNORECASE), "Hội trưởng Bất Lưu - Hoắc Khuê"),
    (re.compile(r"chủ tịch sẽ không được giữ lại", re.IGNORECASE), "hội trưởng Bất Lưu"),
    (re.compile(r"tổng thống sẽ không ở lại", re.IGNORECASE), "hội trưởng Bất Lưu"),
    (re.compile(r"quán bar không ở lại", re.IGNORECASE), "quán bar Bất Lưu"),
    (re.compile(r"không ở lại quán bar", re.IGNORECASE), "quán bar Bất Lưu"),
    (re.compile(r"quán bar Buliu", re.IGNORECASE), "quán bar Bất Lưu"),
    (re.compile(r"tham gia mà không ở lại", re.IGNORECASE), "gia nhập Bất Lưu"),
    (re.compile(r"gia nhập mà không ở lại", re.IGNORECASE), "gia nhập Bất Lưu"),
    (re.compile(r"những người sẽ không ở lại", re.IGNORECASE), "người của Bất Lưu"),
    (re.compile(r"người sẽ không ở lại", re.IGNORECASE), "người của Bất Lưu"),
    (re.compile(r"người không ở lại", re.IGNORECASE), "người của Bất Lưu"),
    (re.compile(r"Người không ở lại"), "Người của Bất Lưu"),
    (re.compile(r"người tôi sẽ không giữ", re.IGNORECASE), "người của Bất Lưu"),
    (re.compile(r"phản bội Lou Buqiu", re.IGNORECASE), "phản bội Bất Lưu"),
    (re.compile(r"phản bội Bộ Thu", re.IGNORECASE), "phản bội Bất Lưu"),
    (re.compile(r"phản bội Buliu", re.IGNORECASE), "phản bội Bất Lưu"),
    (re.compile(r"\bBuliu\b"), "Bất Lưu"),
    (re.compile(r"\bBustay\b"), "Bất Lưu"),
    (re.compile(r"\bBurei\b"), "Bất Lưu"),
    (re.compile(r"\bNo Retention\b"), "Bất Lưu"),

    # --- 5. NHÂN VẬT CHÍNH: TRẦN YẾN (陈彦 / 陈晏 - Chén Yàn) ---
    (re.compile(r"\bChen Yan\b"), "Trần Yến"),
    (re.compile(r"\bChen Ye\b"), "Trần Yến"),
    (re.compile(r"\bChenye\b"), "Trần Yến"),
    (re.compile(r"\bTrần Diệp\b"), "Trần Yến"),
    (re.compile(r"\bChen Ren\b"), "Trần Yến"),
    (re.compile(r"\bAnh Yan\b"), "Anh Yến"),
    (re.compile(r"\banh Yan\b"), "anh Yến"),
    (re.compile(r"\bAnh Xiaoyan\b"), "Anh Yến"),
    (re.compile(r"\banh Xiaoyan\b"), "anh Yến"),

    # --- 6. HOẮC KHUÊ (霍奎 / Huò Kuí - Khuê ca / Anh Khuê) ---
    (re.compile(r"\bHứa Khôi\b"), "Hoắc Khuê"),
    (re.compile(r"\bHoắc Khôi\b"), "Hoắc Khuê"),
    (re.compile(r"\bHứa Kui\b"), "Hoắc Khuê"),
    (re.compile(r"\bHuo Kui\b"), "Hoắc Khuê"),
    (re.compile(r"\bAnh Quỳ\b"), "Anh Khuê"),
    (re.compile(r"\banh Quỳ\b"), "anh Khuê"),
    (re.compile(r"\bAnh Kui\b"), "Anh Khuê"),
    (re.compile(r"\banh Kui\b"), "anh Khuê"),
    (re.compile(r"\bAnh Quế\b"), "Anh Khuê"),
    (re.compile(r"\banh Quế\b"), "anh Khuê"),
    (re.compile(r"\bAnh Cối\b"), "Anh Khuê"),
    (re.compile(r"\banh Cối\b"), "anh Khuê"),
    (re.compile(r"\bAnh Khôi\b"), "Anh Khuê"),
    (re.compile(r"\banh Khôi\b"), "anh Khuê"),

    # --- 7. BÙI DŨNG (裴勇 / Péi Yǒng - Dũng ca / Anh Dũng / Lão Bùi) ---
    (re.compile(r"anh trai Yong của bạn", re.IGNORECASE), "Anh Dũng của bạn"),
    (re.compile(r"bạn gái của anh trai chúng tôi Yong", re.IGNORECASE), "bạn gái của Anh Dũng chúng ta"),
    (re.compile(r"Anh Đặng Yong", re.IGNORECASE), "Anh Đặng Dũng"),
    (re.compile(r"anh Đặng Yong", re.IGNORECASE), "anh Đặng Dũng"),
    (re.compile(r"Anh Ji Yong", re.IGNORECASE), "Anh Kỷ Dũng"),
    (re.compile(r"anh Ji Yong", re.IGNORECASE), "anh Kỷ Dũng"),
    (re.compile(r"\bHui Yong\b"), "Huệ Dũng"),
    (re.compile(r"\bPei Yong\b"), "Bùi Dũng"),
    (re.compile(r"\bBae Yong\b"), "Bùi Dũng"),
    (re.compile(r"\bAnh Yong\b"), "Anh Dũng"),
    (re.compile(r"\banh Yong\b"), "anh Dũng"),
    (re.compile(r"\bYong Ge\b"), "Anh Dũng"),
    (re.compile(r"\banh trai Yong\b"), "anh Dũng"),
    (re.compile(r"\bAnh Pei\b"), "Anh Bùi"),
    (re.compile(r"\banh Pei\b"), "anh Bùi"),
    (re.compile(r"\bÔng chủ Pei\b"), "Ông chủ Bùi"),
    (re.compile(r"\bông chủ Pei\b"), "ông chủ Bùi"),
    (re.compile(r"\bLão Pei\b"), "Lão Bùi"),
    (re.compile(r"\blão Pei\b"), "lão Bùi"),

    # --- 8. NGỤY KINH (魏京 / Wèi Jīng - Ngụy ca / Anh Ngụy) ---
    (re.compile(r"\bAnh Wei\b"), "Anh Ngụy"),
    (re.compile(r"\banh Wei\b"), "anh Ngụy"),
    (re.compile(r"\bWei Jing\b"), "Ngụy Kinh"),
    (re.compile(r"\bVệ Kinh\b"), "Ngụy Kinh"),

    # --- 9. SƠ SƠ (初初 / 楚楚 - Chuchu / con gái Trần Yến) ---
    (re.compile(r"\bChuchu\b"), "Sơ Sơ"),
    (re.compile(r"\bchuchu\b"), "Sơ Sơ"),
    (re.compile(r"\bChu Chu\b"), "Sơ Sơ"),

    # --- 10. NHIẾP TIỂU KHẢ & NHIẾP HÚC ---
    (re.compile(r"\bNie Xiaoke\b"), "Nhiếp Tiểu Khả"),
    (re.compile(r"\bXiaoke\b"), "Tiểu Khả"),
    (re.compile(r"\bNie Xu\b"), "Nhiếp Húc"),
    (re.compile(r"\bNhiếp Xu\b"), "Nhiếp Húc"),
    (re.compile(r"gia đình Nie cũ", re.IGNORECASE), "nhà họ Nhiếp"),

    # --- 11. GIA TỘC HỌ LÂM & THÀNH CHỦ ---
    (re.compile(r"\bLin Chengzhu\b"), "Lâm Thành chủ"),
    (re.compile(r"con gái của Chengzhu", re.IGNORECASE), "con gái của Thành chủ"),
    (re.compile(r"con gái Chengzhu", re.IGNORECASE), "con gái Thành chủ"),
    (re.compile(r"\bChengzhu\b"), "Thành chủ"),
    (re.compile(r"\bLin Peiya\b"), "Lâm Bội Nhã"),
    (re.compile(r"\bPeiya\b"), "Bội Nhã"),
    (re.compile(r"\bLin Peiying\b"), "Lâm Bội Anh"),
    (re.compile(r"\bPeiying\b"), "Bội Anh"),
    (re.compile(r"\bcô Lin\b"), "cô Lâm"),
    (re.compile(r"\bCô Lin\b"), "Cô Lâm"),
    (re.compile(r"\bLin tiểu thư\b"), "Lâm tiểu thư"),

    # --- 12. PHÙNG THANH, A SIÊU, YẾN TỬ, KIỀU KIỀU, DIÊU DIÊU, ANH PHI ---
    (re.compile(r"\bFeng Qing\b"), "Phùng Thanh"),
    (re.compile(r"sự nghi ngờ của Feng Qing", re.IGNORECASE), "sự nghi ngờ của Phùng Thanh"),
    (re.compile(r"\bAh Chao\b"), "A Siêu"),
    (re.compile(r"\bA Chao\b"), "A Siêu"),
    (re.compile(r"\bAchao\b"), "A Siêu"),
    (re.compile(r"\bXiao Yanzi\b"), "Tiểu Yến Tử"),
    (re.compile(r"\bYanzi\b"), "Yến Tử"),
    (re.compile(r"con én của tôi", re.IGNORECASE), "con bé Yến Tử nhà tôi"),
    (re.compile(r"Những con én của tôi", re.IGNORECASE), "Con bé Yến Tử nhà tôi"),
    (re.compile(r"những con én của tôi", re.IGNORECASE), "con bé Yến Tử nhà tôi"),
    (re.compile(r"con én nhỏ", re.IGNORECASE), "Tiểu Yến Tử"),
    (re.compile(r"những con én nhỏ", re.IGNORECASE), "Tiểu Yến Tử"),
    (re.compile(r"từ con én", re.IGNORECASE), "từ chỗ Yến Tử"),
    (re.compile(r"Con én đang", re.IGNORECASE), "Yến Tử đang"),
    (re.compile(r"\bLuo Jiaojiao\b"), "Lạc Kiều Kiều"),
    (re.compile(r"\bJiaojiao\b"), "Kiều Kiều"),
    (re.compile(r"\bChị Tiêu Tiêu\b"), "Chị Kiều Kiều"),
    (re.compile(r"\bChị Tiểu Tiểu\b"), "Chị Kiều Kiều"),
    (re.compile(r"\bChị Yao Yao\b"), "Chị Diêu Diêu"),
    (re.compile(r"\bChị Yao\b"), "Chị Diêu"),
    (re.compile(r"\bchị Yao\b"), "chị Diêu"),
    (re.compile(r"\banh Fei\b"), "anh Phi"),
    (re.compile(r"\bFei Ge\b"), "Anh Phi"),

    # --- 13. TÔN ĐẠI TRIỂN, NGÔ NHÃ, NGÔ DƯƠNG, TRƯƠNG DƯƠNG ---
    (re.compile(r"\bSun Dazhan\b"), "Tôn Đại Triển"),
    (re.compile(r"\bSun Da Zhao\b"), "Tôn Đại Triển"),
    (re.compile(r"\bSun Zhanzhan\b"), "Tôn Đại Triển"),
    (re.compile(r"\bTôn Đại Chiến\b"), "Tôn Đại Triển"),
    (re.compile(r"\banh Sun\b"), "anh Tôn"),
    (re.compile(r"\bAnh Sun\b"), "Anh Tôn"),
    (re.compile(r"\bWu Ya\b"), "Ngô Nhã"),
    (re.compile(r"\bWu Yang\b"), "Ngô Dương"),
    (re.compile(r"\bZhang Yang\b"), "Trương Dương"),

    # --- 14. ĐỊA DANH & CƠ SỞ ---
    (re.compile(r"thành phố Beiqiu", re.IGNORECASE), "thành phố Bắc Khâu"),
    (re.compile(r"\bBeiqiu\b"), "Bắc Khâu"),
    (re.compile(r"tòa nhà Ke Zhuangyuan", re.IGNORECASE), "Lầu Trạng Nguyên"),
    (re.compile(r"tháp Zhuangyuan", re.IGNORECASE), "Lầu Trạng Nguyên"),
    (re.compile(r"tòa nhà Zhuangyuan", re.IGNORECASE), "Lầu Trạng Nguyên"),
    (re.compile(r"Tòa nhà Zhuangyuan"), "Lầu Trạng Nguyên"),
    (re.compile(r"tòa nhà Chuangyuan", re.IGNORECASE), "Lầu Trạng Nguyên"),
    (re.compile(r"Zhuangyuan Lou", re.IGNORECASE), "Lầu Trạng Nguyên"),
    (re.compile(r"phố Zhuangyuan", re.IGNORECASE), "Phố Trạng Nguyên"),
    (re.compile(r"\bHongjie\b"), "Phố Đỏ"),
    (re.compile(r"thành phố Shen Xizhi", re.IGNORECASE), "thành phố Trầm Tức"),
    (re.compile(r"thành phố Chen Xizhi", re.IGNORECASE), "thành phố Trầm Tức"),
    (re.compile(r"Chen Xizhi Cheng", re.IGNORECASE), "thành phố Trầm Tức"),
    (re.compile(r"thành phố Feiping", re.IGNORECASE), "thành Phi Bình"),
    (re.compile(r"Fei Pingchang", re.IGNORECASE), "Phi Bình Thành"),
    (re.compile(r"\bFeiping\b"), "Phi Bình"),
    (re.compile(r"núi Lingwangshan", re.IGNORECASE), "núi Lăng Vương"),
    (re.compile(r"núi Lingwang", re.IGNORECASE), "núi Lăng Vương"),
    (re.compile(r"Núi Lingwang"), "Núi Lăng Vương"),

    # --- 15. THUẬT NGỮ THẾ GIỚI ---
    (re.compile(r"\bYecai\b"), "Dạ Thải"),
    (re.compile(r"\bYe Cai\b"), "Dạ Thải"),
    (re.compile(r"\bYe cai\b"), "Dạ Thải"),
    (re.compile(r"\bYanwu\b"), "Yên vật"),
    (re.compile(r"\bYan wu\b"), "Yên vật"),
    (re.compile(r"\bYe Jian\b"), "Dạ Kiếm"),

    # --- 16. RÚT GỌN ĐƠN VỊ TIỀN TỆ ---
    (re.compile(r"bốn trăm hai mươi nhân dân tệ", re.IGNORECASE), "420 tệ"),
    (re.compile(r"sáu trăm tám mươi nhân dân tệ", re.IGNORECASE), "680 tệ"),
    (re.compile(r"bảy trăm nhân dân tệ", re.IGNORECASE), "700 tệ"),
    (re.compile(r"tám trăm nhân dân tệ", re.IGNORECASE), "800 tệ"),
    (re.compile(r"hai trăm nhân dân tệ", re.IGNORECASE), "200 tệ"),
    (re.compile(r"năm mươi nhân dân tệ", re.IGNORECASE), "50 tệ"),
    (re.compile(r"50 nhân dân tệ", re.IGNORECASE), "50 tệ"),
    (re.compile(r"\s+nhân dân tệ\b", re.IGNORECASE), " tệ"),
]


def fix_double_cap(s: str) -> str:
    """Sửa lỗi 2 chữ cái viết hoa liên tiếp ở đầu từ: 'ANh' -> 'Anh', 'TÔi' -> 'Tôi'."""
    return re.sub(
        rf"\b([{VN_UPPER}])([{VN_UPPER}])([{VN_LOWER}]*)",
        lambda m: m.group(1) + m.group(2).lower() + m.group(3),
        s,
    )


def cap_first_letter(s: str) -> str:
    """Viết hoa chữ cái đầu tiên của câu thoại nếu nó đang là chữ thường."""
    if not s:
        return s
    m = re.search(rf"[{VN_LOWER}{VN_UPPER}]", s)
    if m and m.group(0) in VN_LOWER:
        idx = m.start()
        return s[:idx] + s[idx].upper() + s[idx + 1 :]
    return s


def clean_punctuation_and_spaces(s: str) -> str:
    """Xóa khoảng trắng thừa trước dấu phẩy, chấm, hỏi..."""
    s = re.sub(r"\s+([,.:?!])", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def process_text(text: str) -> str:
    """Áp dụng toàn bộ quy tắc thay thế và chuẩn hóa lên 1 đoạn thoại."""
    res = text
    # 1. Sửa lỗi double uppercase trước (nếu có từ lần chạy trước)
    res = fix_double_cap(res)
    # 2. Áp dụng quy tắc từ điển
    for pat, rep in REPLACEMENT_RULES:
        res = pat.sub(rep, res)
    # 3. Dọn dẹp khoảng trắng & dấu câu
    res = clean_punctuation_and_spaces(res)
    # 4. Viết hoa chuẩn xác chữ cái đầu tiên
    res = cap_first_letter(res)
    # 5. Đảm bảo không còn double uppercase
    res = fix_double_cap(res)
    return res


def process_srt_file(srt_path: Path) -> Tuple[int, int]:
    """
    Xử lý một file .vi.srt:
    - Trả về: (tổng số câu, số câu bị sửa)
    """
    raw = srt_path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    blocks = re.split(r"\n\s*\n", raw.strip())
    new_blocks = []
    total = 0
    modified = 0

    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if ts_idx < 0:
            new_blocks.append(block)
            continue

        cue_num = lines[0] if ts_idx > 0 else str(total + 1)
        cue_ts = lines[ts_idx]
        cue_body = "\n".join(lines[ts_idx + 1 :]).strip()

        total += 1
        new_body = process_text(cue_body)
        if new_body != cue_body:
            modified += 1

        new_blocks.append(f"{cue_num}\n{cue_ts}\n{new_body}")

    new_content = "\n\n".join(new_blocks) + "\n"
    srt_path.write_text(new_content, encoding="utf-8")
    return total, modified


def main() -> None:
    film_dir = Path(r"d:\tool\tool_reup_video_ai\output\Kẻ_Đi_Bộ_Trong_Bóng_Tối").resolve()
    if not film_dir.is_dir():
        raise SystemExit(f"Không tìm thấy thư mục phim: {film_dir}")

    parts = sorted(p for p in film_dir.iterdir() if p.is_dir() and p.name.lower().startswith("phan_"))
    print(f"🎬 Bắt đầu chuẩn hóa phụ đề cho {len(parts)} phần tại: {film_dir.name}\n" + "=" * 60)

    grand_total = 0
    grand_modified = 0

    for part_dir in parts:
        vi_srt = next(iter(sorted(part_dir.glob("*.vi.srt"))), None)
        if not vi_srt:
            continue
        tot, mod = process_srt_file(vi_srt)
        grand_total += tot
        grand_modified += mod
        pct = (mod / tot * 100.0) if tot > 0 else 0.0
        status = f"✅ Chuẩn hóa {mod}/{tot} câu ({pct:.1f}%)" if mod > 0 else "— Đã chuẩn xác"
        print(f"  • {part_dir.name:10s} : {status}")

    print("=" * 60)
    print(f"🎉 Hoàn thành chuẩn hóa! Tổng cộng xử lý: {grand_modified} / {grand_total} câu.")

    # Tái tạo phụ đề gộp master Kẻ_Đi_Bộ_Trong_Bóng_Tối_FULL.vi.srt
    print("\n📦 Đang cập nhật phụ đề gộp tổng Kẻ_Đi_Bộ_Trong_Bóng_Tối_FULL.vi.srt...")
    import gop_phan_capcut
    gop_phan_capcut.build(film_dir)

    # Cập nhật dự án CapCut
    print("\n🎨 Đang đồng bộ phụ đề mới vào Dự án CapCut...")
    import tao_du_an_capcut
    tao_du_an_capcut.main()

    print("\n✨ TẤT CẢ ĐÃ HOÀN TẤT VÀ SẴN SÀNG TRONG CAPCUT!")


if __name__ == "__main__":
    main()
