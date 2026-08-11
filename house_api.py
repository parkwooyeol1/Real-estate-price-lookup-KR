# -*- coding: utf-8 -*-
"""
개별단독주택가격 조회

브이월드 국가중점데이터(NED) API 사용.
개별주택가격속성조회: https://api.vworld.kr/ned/data/getIndvdHousingPriceAttr

※ 실제 응답 구조를 호출로 확인해서 반영함(2026-07 기준).
  응답: {"indvdHousingPrices": {"field": [ ...연도별... ]}}
  - field 는 과거→현재 순 정렬 → 최신 연도를 골라야 함.
  - 가격 필드명은 housePc (원). (초안의 indvdHusingPrc 아님)
"""

import requests
from config import VWORLD_API_KEY, VWORLD_DOMAIN

HOUSE_PRICE_URL = "https://api.vworld.kr/ned/data/getIndvdHousingPriceAttr"


def _pick_latest(fields: list[dict], year_key: str = "stdrYear") -> dict | None:
    if not fields:
        return None
    try:
        return max(fields, key=lambda f: int(f.get(year_key, 0) or 0))
    except (ValueError, TypeError):
        return fields[-1]


def get_house_info(pnu: str, stdr_year: str | None = None) -> dict:
    """
    PNU로 개별단독주택가격을 조회한다.

    반환 예:
    {
        "pnu": "1111014600100110001",
        "price_yeondo": "2026",
        "price": 579000000,     # 개별단독주택가격(원)
        "lot_area": 132.2,      # 대지면적(㎡)
        "bld_area": 267.63,     # 건물 연면적(㎡)
    }
    """
    result = {"pnu": pnu, "price_yeondo": None, "price": None,
              "lot_area": None, "bld_area": None}

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

    res = requests.get(HOUSE_PRICE_URL, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    fields = data.get("indvdHousingPrices", {}).get("field") \
        if isinstance(data.get("indvdHousingPrices"), dict) else None
    item = _pick_latest(fields)
    if item:
        result["price_yeondo"] = item.get("stdrYear")
        try:
            result["price"] = int(item.get("housePc", 0))
        except (ValueError, TypeError):
            pass
        for src, dst in (("ladRegstrAr", "lot_area"), ("buldCalcTotAr", "bld_area")):
            try:
                result[dst] = float(item.get(src)) if item.get(src) else None
            except (ValueError, TypeError):
                pass

    return result


if __name__ == "__main__":
    # 종로구 가회동 11 (단독주택)
    print(get_house_info("1111014600100110001"))
