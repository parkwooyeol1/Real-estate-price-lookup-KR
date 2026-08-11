# -*- coding: utf-8 -*-
"""
개별공시지가 + 토지특성(지목/면적) 조회

브이월드 국가중점데이터(NED) API 사용:
- 개별공시지가속성조회: https://api.vworld.kr/ned/data/getIndvdLandPriceAttr
- 토지임야정보조회:     https://api.vworld.kr/ned/data/ladfrlList

※ 실제 응답 구조를 호출로 확인해서 반영함(2026-07 기준).
  - 개별공시지가 응답: {"indvdLandPrices": {"field": [ ...연도별... ]}}
    → field 는 과거→현재 순으로 정렬되어 있어 '최신 연도'를 골라야 함.
  - 토지임야 응답:     {"ladfrlVOList": {"ladfrlVOList": [ ... ]}}
"""

import requests
from config import VWORLD_API_KEY, VWORLD_DOMAIN

LAND_JIGA_URL = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"
LAND_CHAR_URL = "https://api.vworld.kr/ned/data/ladfrlList"


def _pick_latest(fields: list[dict], year_key: str = "stdrYear") -> dict | None:
    """연도별로 여러 건인 목록에서 기준연도가 가장 최신인 항목을 반환."""
    if not fields:
        return None
    try:
        return max(fields, key=lambda f: int(f.get(year_key, 0) or 0))
    except (ValueError, TypeError):
        return fields[-1]


def get_individual_land_price(pnu: str, stdr_year: str | None = None) -> dict:
    """
    PNU(19자리)로 개별공시지가를 조회한다.

    반환 예:
    {
        "pnu": "1168010100108080000",
        "jiga_yeondo": "2026",
        "jiga": 80031000,   # 개별공시지가(원/㎡)
    }
    """
    result = {"pnu": pnu, "jiga_yeondo": None, "jiga": None}

    params = {
        "key": VWORLD_API_KEY,
        "domain": VWORLD_DOMAIN,
        "pnu": pnu,
        "format": "json",
        "numOfRows": "100",  
        "pageNo": "1",
    }
    if stdr_year:
        params["stdrYear"] = stdr_year

    res = requests.get(LAND_JIGA_URL, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    fields = data.get("indvdLandPrices", {}).get("field") \
        if isinstance(data.get("indvdLandPrices"), dict) else None
    item = _pick_latest(fields)
    if item:
        result["jiga_yeondo"] = item.get("stdrYear")
        try:
            result["jiga"] = int(item.get("pblntfPclnd", 0))
        except (ValueError, TypeError):
            pass

    return result


def get_land_char(pnu: str) -> dict:
    """
    PNU로 토지임야정보를 조회해 지목/면적을 가져온다.

    반환 예:
    {"jimok": "대", "area": 738.1}   # area 단위: ㎡
    """
    result = {"jimok": None, "area": None}

    params = {
        "key": VWORLD_API_KEY,
        "domain": VWORLD_DOMAIN,
        "pnu": pnu,
        "format": "json",
        "numOfRows": "10",
        "pageNo": "1",
    }
    res = requests.get(LAND_CHAR_URL, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    # 실제 응답: {"ladfrlVOList": {"ladfrlVOList": [ {...} ], ...}}
    try:
        outer = data.get("ladfrlVOList", {})
        rows = outer.get("ladfrlVOList") if isinstance(outer, dict) else None
        if rows:
            item = rows[0]
            result["jimok"] = item.get("lndcgrCodeNm")
            try:
                result["area"] = float(item.get("lndpclAr", 0))
            except (ValueError, TypeError):
                pass
    except (KeyError, IndexError, TypeError):
        pass

    return result


def get_land_info(pnu: str) -> dict:
    """지목/면적 + 개별공시지가를 합쳐서 반환."""
    result = get_individual_land_price(pnu)
    result.update(get_land_char(pnu))
    return result


if __name__ == "__main__":
    print(get_land_info("1168010100108080000"))
