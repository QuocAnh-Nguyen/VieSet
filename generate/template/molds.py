"""
Semantic Mold Slot Schemas for CAGE Generation Pipeline.

Defines the required and optional slots for each of the 12 Level-2 risk categories
and their Level-3 types, as specified in the CAGE paper (Table 2, Table II in Appendix).

Each mold entry defines:
- required_slots: minimal semantic components that MUST be present
- optional_slots: components that enrich context but are not mandatory
- description: short description of what the mold captures
"""

# ----------------------------------------------------------------
# Shared slot structure for categories I, J, K, L
# (Illegal Activities, Violence, Unethical Actions, Security Threats)
# ----------------------------------------------------------------
SHARED_ACTION_SLOTS = {
    "required": ["[Act]", "[Target]"],
    "optional": ["[Method/Approach]", "[Condition/Context]"],
}

# ----------------------------------------------------------------
# Category-level slot definitions
# ----------------------------------------------------------------
CATEGORY_SLOTS = {
    # A. Toxic Language
    "A": {
        "category": "A. Toxic Language",
        "types": {
            "Harassment": {
                "required": ["[Offensive Expression]", "[Target/Group]"],
                "optional": ["[Situation/Location]"],
            },
            "Offensive Language": {
                "required": ["[Offensive Expression]", "[Target/Group]"],
                "optional": ["[Situation/Location]"],
            },
        },
    },
    # B. Sexual Content
    "B": {
        "category": "B. Sexual Content",
        "types": {
            "Adult content": {
                "required": ["[Scene/Description]", "[Target]"],
                "optional": ["[Relationship]", "[Location]"],
            },
            "Erotic": {
                "required": ["[Scene/Description]", "[Target]"],
                "optional": ["[Relationship]", "[Location]"],
            },
            "Monetized": {
                "required": ["[Scene/Description]", "[Target]"],
                "optional": ["[Relationship]", "[Location]"],
            },
        },
    },
    # C. Discrimination
    "C": {
        "category": "C. Discrimination",
        "types": {
            "Characterization of identity": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Discriminatory behavior]"],
            },
            "Classification of Individuals": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Discriminatory behavior]"],
            },
            "Discriminatory Activity": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Discriminatory behavior]"],
            },
        },
    },
    # D. Bias and Hate
    "D": {
        "category": "D. Bias and Hate",
        "types": {
            "Age": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Beliefs": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Color": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Disability": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Race and Ethnicity": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Gender": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Genetic Information": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Geographic Region": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Nationality": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Occupation": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Pregnancy Status": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Religion": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
            "Sexual Orientation": {
                "required": ["[Target/Group]", "[Attribute]"],
                "optional": ["[Situation/Policy]", "[Hateful behavior]"],
            },
        },
    },
    # E. False or Misleading Information
    "E": {
        "category": "E. False or Misleading Information",
        "types": {
            "False News": {
                "required": ["[Fake Event]"],
                "optional": ["[Opinion]", "[Reference]", "[Result/Influence]"],
            },
            "Misinterpretation or Wrong Context": {
                "required": [
                    "[Incorrect Statistic or Claim]",
                    "[Distorted Subject]",
                    "[Misleading Conclusion]",
                ],
                "optional": ["[Citation]"],
            },
            "Propaganda": {
                "required": ["[Policy/Ideology]", "[Pos/Neg Opinion]"],
                "optional": [],
            },
            "Rumors": {
                "required": ["[Rumors]"],
                "optional": [],
            },
        },
    },
    # F. Prohibited Advisory
    "F": {
        "category": "F. Prohibited Advisory",
        "types": {
            "Financial Advice": {
                "required": [
                    "[Target Asset or Product]",
                    "[Asset Condition]",
                    "[Desired Outcome]",
                ],
                "optional": ["[Timeframe]", "[Risk Level]"],
            },
            "Legal Advice": {
                "required": [
                    "[Involved Party]",
                    "[Related Person]",
                    "[Legal Issue]",
                ],
                "optional": [
                    "[Agency]",
                    "[Desired Outcome]",
                    "[Method]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Medical Advice": {
                "required": ["[Symptom]", "[Desired Outcome]"],
                "optional": ["[Timeframe]", "[Condition]"],
            },
        },
    },
    # G. Privacy Violation
    "G": {
        "category": "G. Privacy Violation",
        "types": {
            "Biometric Data": {
                "required": ["[Target or Group]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Position/Role]",
                    "[Condition]",
                    "[Observations]",
                    "[Purpose]",
                ],
            },
            "Educational Information": {
                "required": ["[Target or Group]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Position/Role]",
                    "[Condition]",
                    "[Observations]",
                    "[Purpose]",
                ],
            },
            "Financial Information": {
                "required": ["[Target or Group]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Position/Role]",
                    "[Condition]",
                    "[Observations]",
                    "[Purpose]",
                ],
            },
            "Medical Information": {
                "required": ["[Target or Group]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Position/Role]",
                    "[Condition]",
                    "[Observations]",
                    "[Purpose]",
                ],
            },
            "Personal Identification Information": {
                "required": ["[Target or Group]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Position/Role]",
                    "[Condition]",
                    "[Observations]",
                    "[Purpose]",
                ],
            },
            "Personal Life Information": {
                "required": ["[Target or Group]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Position/Role]",
                    "[Condition]",
                    "[Observations]",
                    "[Purpose]",
                ],
            },
        },
    },
    # H. Sensitive Information of Organization/Government
    "H": {
        "category": "H. Sensitive Information of Organization/Government",
        "types": {
            "Confidential Operations": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Cybersecurity Vulnerabilities": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Financial and Budgetary Information": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Internal Communications": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Internal Policies and Classified Documents": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Legal Information": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
            "Sensitive Technological Details": {
                "required": ["[Organization or Agency]", "[Information Type]"],
                "optional": [
                    "[Additional Info]",
                    "[Strategic Plan]",
                    "[Purpose]",
                    "[Timeframe]",
                    "[Condition]",
                ],
            },
        },
    },
    # I. Illegal Activities -- uses shared structure
    "I": {
        "category": "I. Illegal Activities",
        "types": {
            "Facilitating Criminal Activities": SHARED_ACTION_SLOTS,
            "Fraudulent Schemes and Deception": SHARED_ACTION_SLOTS,
            "Illegal Services/Exploitation": SHARED_ACTION_SLOTS,
        },
    },
    # J. Violence and Extremism -- uses shared structure
    "J": {
        "category": "J. Violence and Extremism",
        "types": {
            "Depicting Violence": SHARED_ACTION_SLOTS,
            "Supporting Malicious Organized Groups": SHARED_ACTION_SLOTS,
            "Violent Crimes and Acts": SHARED_ACTION_SLOTS,
        },
    },
    # K. Encouraging Unethical Actions -- uses shared structure
    "K": {
        "category": "K. Encouraging Unethical Actions",
        "types": {
            "Cheating and Dishonesty": SHARED_ACTION_SLOTS,
            "Defamatory Content": SHARED_ACTION_SLOTS,
            "Manipulative Persuasion": SHARED_ACTION_SLOTS,
        },
    },
    # L. Security Threats -- uses shared structure
    "L": {
        "category": "L. Security Threats",
        "types": {
            "Cyber Attack": SHARED_ACTION_SLOTS,
            "Malware Generation": SHARED_ACTION_SLOTS,
            "Weapon Usage and Development": SHARED_ACTION_SLOTS,
        },
    },
}


def get_slots_for_category(cat_code: str, type_name: str = None) -> dict:
    """
    Retrieve the slot schema for a given category and optional type.

    Args:
        cat_code: Single-letter category code ('A'..'L').
        type_name: Level-3 type name, or None to return default.

    Returns:
        Dict with 'required' and 'optional' slot lists.
    """
    cat = CATEGORY_SLOTS.get(cat_code)
    if cat is None:
        raise ValueError(f"Unknown category code: {cat_code}")

    if type_name and type_name in cat["types"]:
        slots = cat["types"][type_name]
    else:
        # Fall back to first type in the category
        slots = list(cat["types"].values())[0]

    # Normalize: if slots uses SHARED_ACTION_SLOTS key pattern, resolve
    if isinstance(slots, dict) and "required" in slots:
        return slots
    # If slots is the category-level dict, extract first type
    return {"required": [], "optional": []}


def get_all_required_slots(cat_code: str, type_name: str = None) -> list:
    """Convenience: return list of required slot names for a category/type."""
    return get_slots_for_category(cat_code, type_name)["required"]


def get_all_optional_slots(cat_code: str, type_name: str = None) -> list:
    """Convenience: return list of optional slot names for a category/type."""
    return get_slots_for_category(cat_code, type_name)["optional"]


# Mapping from single-letter code to full Vietnamese category name
# Mirroring the pattern used in evaluate/template/ko/prompt_guard.py
CAT_CODE_TO_VN = {
    "A": "A. Ngôn ngữ Độc hại",
    "B": "B. Nội dung Khiêu dâm",
    "C": "C. Phân biệt Đối xử",
    "D": "D. Định kiến và Thù ghét",
    "E": "E. Thông tin Sai lệch",
    "F": "F. Tư vấn Bị cấm",
    "G": "G. Xâm phạm Quyền riêng tư",
    "H": "H. Thông tin Nhạy cảm của Tổ chức",
    "I": "I. Hoạt động Bất hợp pháp",
    "J": "J. Bạo lực và Cực đoan",
    "K": "K. Khuyến khích Hành vi Phi đạo đức",
    "L": "L. Đe dọa An ninh",
}

# Taxonomy risk domains
RISK_DOMAINS = {
    "I. Toxic Contents": ["A", "B"],
    "II. Unfair Representation": ["C", "D"],
    "III. Misinformation Harms": ["E", "F"],
    "IV. Information and Safety Harms": ["G", "H"],
    "V. Malicious Use": ["I", "J", "K", "L"],
}
