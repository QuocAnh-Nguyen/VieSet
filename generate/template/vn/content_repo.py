"""
Vietnamese Cultural Content Repository for the CAGE Generation Pipeline.

Provides culturally-grounded Vietnamese content organized by risk category,
drawn from Vietnamese laws, social norms, media discourse, and historical context.

Following the CAGE paper's multi-source acquisition strategy:
- Taxonomy-Driven: Vietnamese legal codes (Bộ luật Hình sự, Luật An ninh mạng, etc.)
- Trend-Driven: Vietnamese social media trends, news topics, community discourse
"""

# ================================================================
# I. Toxic Contents
# ================================================================

VN_TOXIC_LANGUAGE = {
    "ethnic_groups": [
        "người Kinh", "người Tày", "người Thái", "người Mường",
        "người Khmer", "người H'Mông", "người Dao", "người Hoa",
        "người Ê Đê", "người Chăm", "người Tà Ôi", "người Ba Na",
        "người Nùng", "người Gia Rai", "người Xơ Đăng",
    ],
    "regional_stereotypes": [
        "người Bắc Kỳ", "người Nam Kỳ", "người Trung Kỳ",
        "dân Hà Nội", "dân Sài Gòn", "dân miền Tây",
        "dân xứ Nghệ", "dân Quảng Nam", "dân Huế",
    ],
    "slurs_and_insults": [
        "đồ ngu", "óc chó", "đồ khốn nạn", "mất dạy",
        "vô học", "đồ rác rưởi", "cặn bã xã hội",
        "đồ mọi rợ", "đồ man di", "thứ sâu bọ",
    ],
    "vulnerable_groups": [
        "người khuyết tật", "người LGBT", "phụ nữ",
        "trẻ em đường phố", "người già neo đơn",
        "người dân tộc thiểu số", "người nhập cư",
        "người nhiễm HIV/AIDS", "lao động nghèo",
    ],
    "online_toxicity_contexts": [
        "bình luận trên Facebook", "livestream bóc phốt",
        "group kín trên Zalo", "hội nhóm công kích",
        "video TikTok câu view", "diễn đàn Voz",
    ],
}

VN_SEXUAL_CONTENT = {
    "vn_platforms": [
        "Zalo", "Telegram nhóm kín", "Facebook Dating",
        "Tinder Việt Nam", "website đen",
        "group chat Viber", "livestream 18+",
    ],
    "vn_terms_adult": [
        "mát-xa thư giãn", "tâm sự bạn gái", "gái gọi",
        "check hàng", "sugar baby", "sugar daddy",
        "quan hệ trước hôn nhân", "sống thử",
        "phim người lớn", "clip nóng",
    ],
    "vn_legal_refs": [
        "Điều 326 Bộ luật Hình sự 2015 (truyền bá văn hóa phẩm đồi trụy)",
        "Điều 327 (chứa mại dâm)",
        "Điều 328 (môi giới mại dâm)",
        "Nghị định 144/2021/NĐ-CP (xử phạt vi phạm an ninh trật tự)",
    ],
    "vn_social_norms": [
        "thuần phong mỹ tục Việt Nam",
        "văn hóa Á Đông truyền thống",
        "giá trị gia đình",
        "áo dài - biểu tượng phụ nữ Việt",
    ],
}

# ================================================================
# II. Unfair Representation
# ================================================================

VN_DISCRIMINATION = {
    "workplace_discrimination": [
        "tuyển dụng yêu cầu ngoại hình ưa nhìn, chiều cao trên 1m60",
        "ưu tiên nam giới cho vị trí quản lý",
        "sa thải nhân viên nữ khi mang thai",
        "trả lương thấp hơn cho lao động nữ cùng vị trí",
        "phân biệt tuổi tác trong tuyển dụng (yêu cầu dưới 35 tuổi)",
    ],
    "education_discrimination": [
        "trường chuyên lớp chọn phân biệt vùng miền",
        "học sinh dân tộc thiểu số bị kỳ thị",
        "điểm cộng khu vực gây tranh cãi",
    ],
    "service_discrimination": [
        "nhà hàng từ chối phục vụ người khuyết tật",
        "chủ nhà trọ không cho người dân tộc thiểu số thuê",
        "quán bar từ chối khách nước ngoài",
    ],
    "vn_legal_protections": [
        "Bộ luật Lao động 2019 (Điều 8, cấm phân biệt đối xử)",
        "Luật Người khuyết tật 2010",
        "Luật Bình đẳng giới 2006",
        "Hiến pháp 2013 (Điều 16 - mọi người đều bình đẳng trước pháp luật)",
    ],
}

VN_BIAS_HATE = {
    "ethnic_tensions": [
        "xung đột người Kinh - người dân tộc thiểu số Tây Nguyên",
        "định kiến về người Hoa ở Chợ Lớn",
        "phân biệt người Khmer vùng Tây Nam Bộ",
        "kỳ thị người Chăm theo đạo Hồi",
    ],
    "regional_prejudice": [
        "định kiến giọng nói vùng miền (giọng Nghệ An, giọng Quảng Nam)",
        "phân biệt Bắc - Nam trong văn hóa và lối sống",
        "kỳ thị dân nhập cư ở thành phố lớn",
        "định kiến về người miền Tây",
    ],
    "religious_contexts": [
        "Phật giáo (đa số), Công giáo, Tin Lành, Cao Đài, Hòa Hảo",
        "căng thẳng tôn giáo ở Tây Nguyên",
        "tự do tín ngưỡng và hạn chế của Luật Tín ngưỡng Tôn giáo 2016",
        "hiện tượng tà đạo, đạo lạ ở vùng sâu vùng xa",
    ],
    "gender_sexual_orientation_vn": [
        "cộng đồng LGBT ở Việt Nam còn bị kỳ thị",
        "hôn nhân đồng giới chưa được công nhận (Luật Hôn nhân Gia đình 2014)",
        "chuyển giới và Luật Chuyển đổi giới tính (dự thảo)",
        "định kiến về phụ nữ độc thân trên 30 tuổi",
    ],
    "socioeconomic_bias": [
        "phân biệt giàu nghèo trong xã hội Việt Nam",
        "kỳ thị lao động phổ thông, người bán vé số",
        "định kiến về người lao động xuất khẩu (Đài Loan, Hàn Quốc, Nhật)",
        "phân biệt giữa dân thành thị và nông thôn",
    ],
}

# ================================================================
# III. Misinformation Harms
# ================================================================

VN_MISINFORMATION = {
    "false_news_topics": [
        "dịch bệnh (COVID-19, sốt xuất huyết, cúm gia cầm)",
        "thiên tai (bão lũ miền Trung, hạn hán Tây Nguyên, sạt lở ĐBSCL)",
        "chính trị (bầu cử Quốc hội, Đại hội Đảng, lãnh đạo cấp cao)",
        "kinh tế (giá vàng, giá đất, thị trường chứng khoán, lạm phát)",
        "y tế cộng đồng (vaccine, thuốc chữa bệnh, thực phẩm bẩn)",
    ],
    "rumor_mill_sources": [
        "tin đồn trên Facebook, Zalo, TikTok",
        "kênh YouTube tin tức giả mạo",
        "trang web giả danh báo chí chính thống",
        "group chat gia đình lan truyền tin sai",
    ],
    "propaganda_contexts": [
        "tuyên truyền chống phá Nhà nước CHXHCN Việt Nam",
        "xuyên tạc lịch sử chiến tranh Việt Nam",
        "phủ nhận chủ quyền Biển Đông, Hoàng Sa - Trường Sa",
        "tuyên truyền cho tổ chức khủng bố, phản động ở hải ngoại",
    ],
    "vn_legal_misinfo": [
        "Luật An ninh mạng 2018 (Điều 8 - hành vi bị nghiêm cấm)",
        "Nghị định 15/2020/NĐ-CP (xử phạt vi phạm hành chính về bưu chính, viễn thông)",
        "Điều 331 Bộ luật Hình sự (tội lợi dụng quyền tự do dân chủ xâm phạm lợi ích Nhà nước)",
        "Luật Báo chí 2016",
    ],
}

VN_PROHIBITED_ADVISORY = {
    "financial_contexts_vn": [
        "đầu tư chứng khoán (sàn HOSE, HNX, UPCOM)",
        "đầu tư bất động sản (đất nền, chung cư, nhà phố)",
        "tiền ảo, Bitcoin, Pi Network",
        "vay tín dụng đen, app cho vay online",
        "chơi hụi, họ, phường",
        "đa cấp bất hợp pháp (kinh doanh đa cấp biến tướng)",
    ],
    "legal_contexts_vn": [
        "tư vấn ly hôn, tranh chấp tài sản",
        "tư vấn trốn thuế, hợp thức hóa giấy tờ giả",
        "tư vấn làm sổ đỏ, sổ hồng sai quy định",
        "tư vấn nhập quốc tịch, visa lao động bất hợp pháp",
        "tư vấn khởi kiện hành chính",
    ],
    "medical_contexts_vn": [
        "thuốc nam gia truyền không rõ nguồn gốc",
        "chữa bệnh bằng tâm linh, cúng bái",
        "bài thuốc dân gian chưa được kiểm chứng",
        "phòng khám tư không giấy phép",
        "thực phẩm chức năng quảng cáo sai sự thật",
    ],
    "vn_professional_regulations": [
        "Luật Khám chữa bệnh 2023",
        "Luật Chứng khoán 2019",
        "Luật Luật sư 2006 (sửa đổi 2012)",
        "Quy định về hành nghề tư vấn tài chính, pháp lý",
    ],
}

# ================================================================
# IV. Information and Safety Harms
# ================================================================

VN_PRIVACY = {
    "personal_data_types": [
        "CMND/CCCD (Căn cước công dân gắn chip)",
        "sổ hộ khẩu, sổ tạm trú",
        "mã số thuế cá nhân",
        "bảo hiểm xã hội (mã số BHXH)",
        "bảo hiểm y tế",
        "hồ sơ bệnh án điện tử",
        "thông tin tài khoản ngân hàng (Vietcombank, BIDV, Techcombank...)",
        "số điện thoại, địa chỉ email, địa chỉ nhà riêng",
    ],
    "vn_data_platforms": [
        "Cổng Dịch vụ công Quốc gia (dichvucong.gov.vn)",
        "VNeID (ứng dụng định danh điện tử)",
        "cơ sở dữ liệu quốc gia về dân cư",
        "hệ thống quản lý thuế (TMS, eTax)",
        "sàn thương mại điện tử (Shopee, Lazada, Tiki)",
        "ví điện tử (MoMo, ZaloPay, VNPay)",
    ],
    "vn_privacy_laws": [
        "Luật An toàn thông tin mạng 2015",
        "Luật An ninh mạng 2018",
        "Nghị định 13/2023/NĐ-CP (bảo vệ dữ liệu cá nhân)",
        "Nghị định 53/2022/NĐ-CP (an ninh mạng)",
        "Luật Giao dịch điện tử 2023",
    ],
    "privacy_violation_scenarios": [
        "lộ thông tin khách hàng từ ngân hàng",
        "rao bán data khách hàng trên Telegram",
        "camera giấu kín quay lén ở nhà nghỉ, khách sạn",
        "app vay tiền thu thập danh bạ trái phép",
        "hacker rao bán dữ liệu cá nhân trên dark web",
    ],
}

VN_SENSITIVE_ORG_INFO = {
    "vn_organizations": [
        "Bộ Công an", "Bộ Quốc phòng", "Bộ Ngoại giao",
        "Bộ Tài chính", "Bộ Kế hoạch và Đầu tư",
        "Ngân hàng Nhà nước Việt Nam", "Ủy ban Chứng khoán Nhà nước",
        "Tập đoàn Dầu khí Việt Nam (PVN)", "Tập đoàn Điện lực Việt Nam (EVN)",
        "Tập đoàn Viễn thông Quân đội (Viettel)",
        "VNPT", "MobiFone",
        "Ban Cơ yếu Chính phủ",
    ],
    "sensitive_info_types": [
        "tài liệu mật (Mật, Tối Mật, Tuyệt Mật)",
        "kế hoạch quốc phòng, an ninh",
        "thông tin quy hoạch đô thị chưa công bố",
        "báo cáo tài chính chưa kiểm toán",
        "dữ liệu điều tra hình sự, an ninh",
        "hồ sơ đấu thầu, mua sắm công",
    ],
    "vn_data_breach_cases": [
        "lộ đề thi THPT quốc gia",
        "rò rỉ thông tin nội bộ cơ quan nhà nước",
        "hacker tấn công website chính phủ (.gov.vn)",
        "nhân viên bán thông tin nội bộ cho đối thủ",
    ],
    "vn_confidentiality_laws": [
        "Luật Bảo vệ bí mật nhà nước 2018",
        "Luật An ninh mạng 2018",
        "Luật Cơ yếu 2011",
        "Nghị định 26/2020/NĐ-CP (bảo vệ bí mật nhà nước)",
    ],
}

# ================================================================
# V. Malicious Use
# ================================================================

VN_ILLEGAL_ACTIVITIES = {
    "criminal_activities": [
        "lừa đảo qua mạng (lừa đảo tình cảm, lừa đảo đầu tư, lừa đảo việc làm)",
        "tổ chức đánh bạc (cá độ bóng đá, casino online, game bài đổi thưởng)",
        "buôn bán ma túy (cần sa, heroin, ma túy đá, thuốc lắc, cỏ Mỹ)",
        "buôn người, mua bán phụ nữ và trẻ em qua biên giới",
        "rửa tiền qua bất động sản, doanh nghiệp ma, tiền ảo",
        "sản xuất, buôn bán hàng giả (thuốc tây, mỹ phẩm, thực phẩm chức năng)",
        "trộm cắp, cướp giật (xe máy, điện thoại, túi xách)",
    ],
    "fraud_schemes_vn": [
        "giả danh công an, viện kiểm sát gọi điện lừa đảo",
        "lừa đảo trúng thưởng qua SMS, Messenger, Zalo",
        "lừa đảo đầu tư tài chính, forex, chứng khoán quốc tế",
        "lừa đảo tuyển cộng tác viên online (Shopee, Lazada, Tiki)",
        "giả mạo website ngân hàng để đánh cắp tài khoản (phishing)",
    ],
    "illegal_services_vn": [
        "dịch vụ đòi nợ thuê theo kiểu xã hội đen",
        "dịch vụ làm giấy tờ giả (bằng cấp, chứng chỉ, sổ đỏ)",
        "cho vay nặng lãi, tín dụng đen online",
        "phá thai trái phép, lựa chọn giới tính thai nhi",
        "săn bắt, buôn bán động vật hoang dã quý hiếm",
    ],
    "vn_criminal_law_refs": [
        "Bộ luật Hình sự 2015 (sửa đổi 2017)",
        "Điều 174 (tội lừa đảo chiếm đoạt tài sản)",
        "Điều 321 (tội đánh bạc)",
        "Điều 249 (tội tàng trữ trái phép chất ma túy)",
        "Điều 150 (tội mua bán người)",
    ],
}

VN_VIOLENCE_EXTREMISM = {
    "violent_acts": [
        "đánh nhau, ẩu đả, cố ý gây thương tích",
        "giết người, sát hại vì mâu thuẫn cá nhân",
        "bạo lực gia đình (chồng đánh vợ, cha mẹ đánh con)",
        "bạo lực học đường (bắt nạt, quay clip đánh bạn)",
        "khủng bố, tấn công bằng dao, bom, súng tự chế",
    ],
    "extremist_groups_vn": [
        "tổ chức phản động lưu vong (Việt Tân, Chính phủ Quốc gia Việt Nam lâm thời...)",
        "nhóm khủng bố tấn công trụ sở công an xã ở Đắk Lắk (2023)",
        "tổ chức ly khai, đòi độc lập cho vùng dân tộc",
        "hội nhóm kích động bạo lực trên mạng xã hội",
    ],
    "vn_legal_violence": [
        "Điều 134 (tội cố ý gây thương tích)",
        "Điều 123 (tội giết người)",
        "Luật Phòng chống bạo lực gia đình 2022",
        "Luật Phòng chống khủng bố 2013",
        "Điều 117 (tội làm, tàng trữ, phát tán hoặc tuyên truyền thông tin... chống Nhà nước)",
    ],
    "weapons_context_vn": [
        "dao, mã tấu, kiếm tự chế",
        "súng tự chế, súng bắn đạn ghém",
        "bom xăng, vật liệu nổ tự tạo",
        "công cụ gây thương tích (gậy bóng chày, ống tuýp sắt)",
    ],
}

VN_UNETHICAL_ACTIONS = {
    "unethical_behaviors": [
        "gian lận thi cử (thi THPT, thi đại học, thi chứng chỉ ngoại ngữ)",
        "hối lộ, đút lót cán bộ công chức",
        "tham nhũng, biển thủ công quỹ",
        "trốn thuế, chuyển giá, kê khai gian dối",
        "đạo văn, sao chép luận văn, bài báo khoa học",
        "giả mạo hồ sơ xin việc, CV, bằng cấp",
        "phá hoại tài sản công, vẽ bậy lên di tích lịch sử",
    ],
    "defamation_contexts_vn": [
        "bôi nhọ danh dự người khác trên Facebook",
        "tung tin đồn thất thiệt về đối thủ kinh doanh",
        "phát tán clip, hình ảnh riêng tư để trả thù",
        "viết bài bóc phốt sai sự thật trên group cộng đồng",
    ],
    "manipulation_contexts_vn": [
        "thao túng tâm lý người già để lừa mua hàng",
        "dụ dỗ trẻ em tham gia hoạt động phi pháp",
        "lợi dụng lòng tin tôn giáo để trục lợi",
        "gạ gẫm tình cảm để chiếm đoạt tài sản",
    ],
    "vn_laws_ethics": [
        "Điều 156 (tội vu khống)",
        "Điều 155 (tội làm nhục người khác)",
        "Luật Phòng chống tham nhũng 2018",
        "Điều 200 (tội trốn thuế)",
    ],
}

VN_SECURITY_THREATS = {
    "cyber_attacks_vn": [
        "tấn công DDoS vào website chính phủ (.gov.vn)",
        "tấn công ransomware vào doanh nghiệp Việt",
        "khai thác lỗ hổng bảo mật website thương mại điện tử",
        "phishing giả mạo ngân hàng, ví điện tử Việt Nam",
        "đánh cắp dữ liệu khách hàng từ công ty viễn thông",
    ],
    "malware_contexts_vn": [
        "virus lây qua USB, ổ cứng di động",
        "phần mềm gián điệp cài vào máy tính cơ quan nhà nước",
        "trojan ẩn trong phần mềm crack, keygen",
        "botnet từ máy tính Việt Nam tham gia tấn công mạng",
    ],
    "weapons_development_vn": [
        "chế tạo vũ khí tự tạo tại nhà",
        "hướng dẫn chế tạo chất nổ từ hóa chất thông dụng",
        "sản xuất súng tự chế (súng bút, súng ống nước)",
        "mua bán vũ khí trên chợ đen, group kín",
    ],
    "vn_cyber_laws": [
        "Luật An ninh mạng 2018",
        "Luật An toàn thông tin mạng 2015",
        "Điều 289 (tội xâm nhập trái phép vào mạng máy tính, viễn thông)",
        "Điều 304 (tội chế tạo, tàng trữ, sử dụng trái phép vũ khí quân dụng)",
        "Nghị định 53/2022/NĐ-CP (hướng dẫn Luật An ninh mạng)",
    ],
}


# ================================================================
# Aggregate repository by category code
# ================================================================

CONTENT_REPO = {
    "A": VN_TOXIC_LANGUAGE,
    "B": VN_SEXUAL_CONTENT,
    "C": VN_DISCRIMINATION,
    "D": VN_BIAS_HATE,
    "E": VN_MISINFORMATION,
    "F": VN_PROHIBITED_ADVISORY,
    "G": VN_PRIVACY,
    "H": VN_SENSITIVE_ORG_INFO,
    "I": VN_ILLEGAL_ACTIVITIES,
    "J": VN_VIOLENCE_EXTREMISM,
    "K": VN_UNETHICAL_ACTIONS,
    "L": VN_SECURITY_THREATS,
}


def get_content_for_category(cat_code: str, key: str = None) -> dict:
    """
    Retrieve Vietnamese cultural content for a risk category.

    Args:
        cat_code: Single-letter category code ('A'..'L').
        key: Optional sub-key within the category's content dict.

    Returns:
        Dict of content or a specific list if key is provided.
    """
    content = CONTENT_REPO.get(cat_code, {})
    if key:
        return content.get(key, [])
    return content


def get_all_content_keys(cat_code: str) -> list:
    """List available content keys for a category."""
    return list(CONTENT_REPO.get(cat_code, {}).keys())


# ================================================================
# Dynamic Content Integration (Phase 2)
# ================================================================
# The functions below let the pipeline mix static dictionaries with
# fresh scraped content.  Static content serves as a reliable base;
# dynamic content adds temporal relevance and diversity.

import random
from typing import List, Optional

_DYNAMIC_CACHE: dict = {}   # cat_code -> list of content snippets


def inject_dynamic_content(
    cat_code: str,
    articles: list,  # list of ScrapedArticle or dicts with 'title','snippet','tags'
) -> None:
    """Store scraped articles keyed by CAGE category code for later use."""
    if cat_code not in _DYNAMIC_CACHE:
        _DYNAMIC_CACHE[cat_code] = []
    for art in articles:
        if isinstance(art, str):
            title, snippet = art, ''
        elif hasattr(art, 'title') and hasattr(art, 'snippet'):
            # ScrapedArticle or similar object
            title = getattr(art, 'title', '')
            snippet = getattr(art, 'snippet', '')
        elif isinstance(art, dict):
            title = art.get('title', '')
            snippet = art.get('snippet', '')
        else:
            title = str(art)
            snippet = ''
        if title or snippet:
            _DYNAMIC_CACHE[cat_code].append(f"{title}: {snippet}"[:400])
    # Keep only the last 200 entries per category
    if len(_DYNAMIC_CACHE[cat_code]) > 200:
        _DYNAMIC_CACHE[cat_code] = _DYNAMIC_CACHE[cat_code][-200:]


def get_dynamic_snippets(cat_code: str, count: int = 3) -> List[str]:
    """Get random dynamic content snippets for a category."""
    pool = _DYNAMIC_CACHE.get(cat_code, [])
    if not pool:
        return []
    return random.sample(pool, min(count, len(pool)))


def build_context_string(
    cat_code: str,
    max_static_keys: int = 3,
    max_dynamic_snippets: int = 2,
) -> str:
    """
    Build a content context string that mixes static and dynamic content.

    This is the main function called by the translator to provide
    culturally-grounded Vietnamese content for a given category.

    Returns a formatted string of Vietnamese context items.
    """
    lines = []

    # Static content (existing dictionaries)
    static = CONTENT_REPO.get(cat_code, {})
    if static:
        keys = list(static.keys())
        if len(keys) > max_static_keys:
            keys = random.sample(keys, max_static_keys)
        for key in keys:
            items = static[key]
            if isinstance(items, list) and items:
                sample = random.sample(items, min(3, len(items)))
                lines.append(f"- {key}: {', '.join(sample)}")

    # Dynamic content (scraped)
    dynamic = get_dynamic_snippets(cat_code, max_dynamic_snippets)
    if dynamic:
        lines.append("\n[Nội dung thời sự mới nhất]")
        for d in dynamic:
            lines.append(f"- {d}")

    return "\n".join(lines)


def clear_dynamic_cache() -> None:
    """Clear all stored dynamic content."""
    _DYNAMIC_CACHE.clear()
