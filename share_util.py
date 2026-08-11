# -*- coding: utf-8 -*-
"""
소유지분(공유지분) 파싱 및 계산

등기부에는 소유지분이 보통 "1123 분의 112.5" 처럼 적혀 있다.
이것은 분수로 112.5 / 1123 (분모가 앞, 분자가 뒤) 을 뜻한다.

이 모듈은 그 표기를 그대로 입력받아
- 분자/분모/비율(ratio) 로 파싱하고
- 전체 값(면적·가격)에 비율을 곱해 '내 지분에 해당하는 값'을 구한다.
"""

import re

# "1123 분의 112.5" / "1123분의112.5"  → (분모=1123, 분자=112.5)
_BUNUI_RE = re.compile(r"([\d.,]+)\s*분의\s*([\d.,]+)")
# "112.5/1123" 형태 → (분자=112.5, 분모=1123)
_SLASH_RE = re.compile(r"([\d.,]+)\s*/\s*([\d.,]+)")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_share(text: str) -> dict | None:
    """
    소유지분 문자열을 파싱한다. 지원 형식:
      - "1123 분의 112.5"   (등기부 표기, 분모 분의 분자)
      - "112.5/1123"        (분자/분모)
      - "112.5"             (분자만? → 지분 아님으로 간주하고 None 대신 무시)
    반환: {"numerator": 112.5, "denominator": 1123, "ratio": 0.10018...} 또는 None
    """
    if not text or not text.strip():
        return None
    t = text.strip()

    m = _BUNUI_RE.search(t)
    if m:
        den, num = _num(m.group(1)), _num(m.group(2))
    else:
        m = _SLASH_RE.search(t)
        if m:
            num, den = _num(m.group(1)), _num(m.group(2))
        else:
            return None

    if den == 0:
        return None
    return {"numerator": num, "denominator": den, "ratio": num / den}


def share_from_parts(denominator, numerator) -> dict | None:
    """
    분모/분자를 각각 받아 지분 dict 를 만든다.
    등기부 표기 "1123 분의 112.5" 이면 denominator=1123, numerator=112.5.
    둘 중 하나라도 비어 있거나 분모가 0이면 None(지분 미적용).
    """
    def _to_num(x):
        if x is None:
            return None
        s = str(x).strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    den = _to_num(denominator)
    num = _to_num(numerator)
    if den is None or num is None or den == 0:
        return None
    return {"numerator": num, "denominator": den, "ratio": num / den}


def apply_share(value, ratio: float | None):
    """value(면적/가격)에 지분비율을 곱한다. ratio가 None이면 원값 그대로."""
    if value is None or ratio is None:
        return value
    return value * ratio


def format_share(share: dict) -> str:
    """'112.5 / 1123  (10.0178%)' 형태 문자열."""
    num = share["numerator"]
    den = share["denominator"]

    def _trim(x: float) -> str:
        return str(int(x)) if float(x).is_integer() else f"{x:g}"

    return f"{_trim(num)} / {_trim(den)}  ({share['ratio'] * 100:.4f}%)"


if __name__ == "__main__":
    for t in ["1123 분의 112.5", "1123분의112.5", "112.5/1123", "1/2", ""]:
        s = parse_share(t)
        print(repr(t), "->", (format_share(s) if s else None))
