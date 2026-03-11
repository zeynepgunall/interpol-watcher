"""Interpol API tarama pass planı.

Her pass bir (etiket, parametre-listesi) çiftidir. Veri yapısı kullanmak
yeni pass ekleme/çıkarmayı tek satıra indirger.
"""
from __future__ import annotations

from typing import Any

# Tüm ülke kodları (ISO 3166-1 alpha-2)
ALL_NATIONALITIES: list[str] = [
    "AF","AL","DZ","AD","AO","AG","AR","AM","AU","AT","AZ","BS","BH","BD","BB",
    "BY","BE","BZ","BJ","BT","BO","BA","BW","BR","BN","BG","BF","BI","CV","KH",
    "CM","CA","CF","TD","CL","CN","CO","KM","CG","CD","CR","HR","CU","CY","CZ",
    "DK","DJ","DM","DO","EC","EG","SV","GQ","ER","EE","SZ","ET","FJ","FI","FR",
    "GA","GM","GE","DE","GH","GR","GD","GT","GN","GW","GY","HT","HN","HU","IS",
    "IN","ID","IR","IQ","IE","IL","IT","JM","JP","JO","KZ","KE","KI","KP","KR",
    "KW","KG","LA","LV","LB","LS","LR","LY","LI","LT","LU","MG","MW","MY","MV",
    "ML","MT","MH","MR","MU","MX","FM","MD","MC","MN","ME","MA","MZ","MM","NA",
    "NR","NP","NL","NZ","NI","NE","NG","NO","OM","PK","PW","PA","PG","PY","PE",
    "PH","PL","PT","QA","RO","RU","RW","KN","LC","VC","WS","SM","ST","SA","SN",
    "RS","SC","SL","SG","SK","SI","SB","SO","ZA","SS","ES","LK","SD","SR","SE",
    "CH","SY","TW","TJ","TZ","TH","TL","TG","TO","TT","TN","TR","TM","TV","UG",
    "UA","AE","GB","US","UY","UZ","VU","VE","VN","YE","ZM","ZW",
]

# Yüksek notice sayısına sahip ülkeler — daha ince granülarite gerektiren ülkeler
HIGH_COUNT: list[str] = ["RU", "SV", "IN", "AR", "PK", "GT"]

# En yüksek kayıt yoğunluğuna sahip ülkeler — yıl bazında yaş taraması yapılır
VERY_HIGH: list[str] = ["RU", "SV"]

PassDef = tuple[str, list[dict[str, Any]]]


def _age_ranges(step: int, lo: int = 10, hi: int = 99) -> list[tuple[int, int]]:
    """Verilen adım büyüklüğüyle yaş aralıkları üretir. Örn: step=5 → (10,14),(15,19)..."""
    return [(a, min(a + step - 1, hi)) for a in range(lo, hi + 1, step)]


def full_scan_passes() -> list[PassDef]:
    """Tam tarama pass tanımları — fetch_all_red_notices tarafından kullanılır."""
    """Pass tanımları — her pass farklı parametre kombinasyonlarıyla API'yi tarar. Pass'ler sırayla çalışır, her biri farklı bir parametre setiyle. İlk pass en geniş kapsamlıdır, sonraki pass'ler daha spesifik kombinasyonlarla kalan boşlukları doldurur."""
    age5 = _age_ranges(5)
    passes: list[PassDef] = [
        ("Pass 2 — nationality",
         [{"nationality": n} for n in ALL_NATIONALITIES]),
        ("Pass 3 — arrestWarrantCountryId",
         [{"arrestWarrantCountryId": c} for c in ALL_NATIONALITIES]),
        ("Pass 4 — M+nationality",
         [{"sexId": "M", "nationality": n} for n in ALL_NATIONALITIES]),
        ("Pass 5 — F+nationality",
         [{"sexId": "F", "nationality": n} for n in ALL_NATIONALITIES]),
        ("Pass 6 — M+arrestWarrant",
         [{"sexId": "M", "arrestWarrantCountryId": c} for c in ALL_NATIONALITIES]),
        ("Pass 7 — F+arrestWarrant",
         [{"sexId": "F", "arrestWarrantCountryId": c} for c in ALL_NATIONALITIES]),
        ("Pass 8 — M+age",
         [{"sexId": "M", "ageMin": a, "ageMax": b} for a, b in age5]),
        ("Pass 9 — F+age",
         [{"sexId": "F", "ageMin": a, "ageMax": b} for a, b in age5]),
        ("Pass 10 — M+highNat+age",
         [{"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": b}
          for nat in HIGH_COUNT for a, b in age5]),
        ("Pass 11 — F+highNat+age",
         [{"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": b}
          for nat in HIGH_COUNT for a, b in age5]),
        ("Pass 12 — M+nat+arrestWarrant",
         [{"sexId": "M", "nationality": nat, "arrestWarrantCountryId": c}
          for nat in HIGH_COUNT for c in ALL_NATIONALITIES]),
        ("Pass 13 — F+nat+arrestWarrant",
         [{"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
          for nat in HIGH_COUNT for c in ALL_NATIONALITIES]),
        ("Pass 14 — M+allNat+highAW",
         [{"sexId": "M", "nationality": nat, "arrestWarrantCountryId": c}
          for c in HIGH_COUNT for nat in ALL_NATIONALITIES]),
        ("Pass 15 — F+allNat+highAW",
         [{"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
          for c in HIGH_COUNT for nat in ALL_NATIONALITIES]),
        ("Pass 16 — M+veryHigh+1yrAge",
         [{"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": a}
          for nat in VERY_HIGH for a in range(10, 85)]),
        ("Pass 17 — F+veryHigh+1yrAge",
         [{"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": a}
          for nat in VERY_HIGH for a in range(10, 85)]),
        ("Pass 18 — M+highCount+1yrAge",
         [{"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": a}
          for nat in HIGH_COUNT if nat not in VERY_HIGH for a in range(10, 85)]),
        ("Pass 19 — F+highCount+1yrAge",
         [{"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": a}
          for nat in HIGH_COUNT if nat not in VERY_HIGH for a in range(10, 85)]),
        ("Pass 20 — M+1yrAge",
         [{"sexId": "M", "ageMin": a, "ageMax": a} for a in range(18, 71)]),
        ("Pass 21 — F+1yrAge",
         [{"sexId": "F", "ageMin": a, "ageMax": a} for a in range(18, 71)]),
        ("Pass 22 — U",      [{"sexId": "U"}]),
        ("Pass 22b — U+nat", [{"sexId": "U", "nationality": n} for n in ALL_NATIONALITIES]),
        ("Pass 23 — age0-9",    [{"ageMin": 0, "ageMax": 9}]),
        ("Pass 23b — M+age0-9", [{"sexId": "M", "ageMin": 0, "ageMax": 9}]),
        ("Pass 23c — F+age0-9", [{"sexId": "F", "ageMin": 0, "ageMax": 9}]),
        ("Pass 24 — age100+",   [{"ageMin": 100, "ageMax": 120}]),
        ("Pass 24b — M+age100+", [{"sexId": "M", "ageMin": 100, "ageMax": 120}]),
        ("Pass 24c — F+age100+", [{"sexId": "F", "ageMin": 100, "ageMax": 120}]),
    ]
    return passes


def extended_passes(
    enable_age_0_9: bool = True,
    enable_in_pk_1yr: bool = True,
    nationalities_1yr: list[str] | None = None,
    age_1yr_min: int = 10,
    age_1yr_max: int = 99,
) -> list[PassDef]:
    """Genişletilmiş pass tanımları — tam tarama sonrası ek derinlik sağlar."""
    if nationalities_1yr is None:
        nationalities_1yr = ["IN", "PK"]

    age5 = _age_ranges(5)
    age1_standard = [(i, i) for i in range(10, 85)]

    passes: list[PassDef] = [
        ("Pass 13 — F+nat+arrestWarrant",
         [{"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
          for nat in HIGH_COUNT for c in ALL_NATIONALITIES]),
        ("Pass 14 — M+allNat+highAW",
         [{"sexId": "M", "nationality": nat, "arrestWarrantCountryId": c}
          for c in HIGH_COUNT for nat in ALL_NATIONALITIES]),
        ("Pass 15 — F+allNat+highAW",
         [{"sexId": "F", "nationality": nat, "arrestWarrantCountryId": c}
          for c in HIGH_COUNT for nat in ALL_NATIONALITIES]),
        ("Pass 16 — M+veryHighNat+1yrAge",
         [{"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": b}
          for nat in VERY_HIGH for a, b in age1_standard]),
        ("Pass 17 — F+veryHighNat+1yrAge",
         [{"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": b}
          for nat in VERY_HIGH for a, b in age1_standard]),
        ("Pass 18 — M+veryHighNat+AW+5yrAge",
         [{"sexId": "M", "nationality": nat, "arrestWarrantCountryId": nat, "ageMin": a, "ageMax": b}
          for nat in VERY_HIGH for a, b in age5]),
        ("Pass 19 — sexId=U",   [{"sexId": "U"}]),
        ("Pass 19b — U+allNat", [{"sexId": "U", "nationality": n} for n in ALL_NATIONALITIES]),
        ("Pass 20 — age100+",   [{"ageMin": 100, "ageMax": 120}]),
        ("Pass 20b — M+age100+", [{"sexId": "M", "ageMin": 100, "ageMax": 120}]),
        ("Pass 20c — F+age100+", [{"sexId": "F", "ageMin": 100, "ageMax": 120}]),
    ]

    if enable_age_0_9:
        passes += [
            ("Pass A — age0-9",    [{"ageMin": 0, "ageMax": 9}]),
            ("Pass Ab — M+age0-9", [{"sexId": "M", "ageMin": 0, "ageMax": 9}]),
            ("Pass Ab — F+age0-9", [{"sexId": "F", "ageMin": 0, "ageMax": 9}]),
            ("Pass Ab — U+age0-9", [{"sexId": "U", "ageMin": 0, "ageMax": 9}]),
        ]

    if enable_in_pk_1yr and nationalities_1yr:
        age1b = [(a, a) for a in range(age_1yr_min, age_1yr_max + 1)]
        nat_label = "+".join(nationalities_1yr)
        passes += [
            (f"Pass B — M+{nat_label}+1yrAge",
             [{"sexId": "M", "nationality": nat, "ageMin": a, "ageMax": b}
              for nat in nationalities_1yr for a, b in age1b]),
            (f"Pass B — F+{nat_label}+1yrAge",
             [{"sexId": "F", "nationality": nat, "ageMin": a, "ageMax": b}
              for nat in nationalities_1yr for a, b in age1b]),
        ]

    return passes
