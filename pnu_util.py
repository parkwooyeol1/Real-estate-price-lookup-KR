# -*- coding: utf-8 -*-
"""
주소 -> PNU(19자리 필지고유번호) 변환

브이월드 지오코더/검색 API를 이용해 지번주소를 PNU로 바꿉니다.
PNU가 있어야 개별공시지가, 개별단독주택가격 API를 호출할 수 있습니다.

주의: 브이월드 API 응답 구조는 검색 결과 형태에 따라 조금씩 다를 수 있습니다.
      실제 인증키로 테스트해보면서 아래 파싱 부분은 확인/조정이 필요할 수 있습니다.
"""

# -*- coding: utf-8 -*-
"""
주소 -> PNU(19자리 필지고유번호) 변환

주의: 브이월드는 "지오코더 API"와 "검색 API"가 별도 서비스임.
- 지오코더 API(getcoord): 주소 -> 좌표(위도/경도)만 반환. PNU 없음. (스펙 확인 완료)
- 검색 API(search): 주소/지번 검색 결과에 id(PNU)가 포함되는 걸로 추정. (스펙 아직 미확인 -> 확인 후 아래 address_to_pnu 완성할 것)
"""

import re

import requests
from config import VWORLD_API_KEY, VWORLD_DOMAIN

# ---- 확인 완료: 주소 -> 좌표 변환 (지오코더 API 2.0) ----
GEOCODER_URL = "https://api.vworld.kr/req/address"


def address_to_coord(address: str, addr_type: str = "PARCEL") -> tuple[float, float] | None:
    """
    주소를 좌표(경도, 위도)로 변환.
    addr_type: "PARCEL"(지번주소) 또는 "ROAD"(도로명주소)
    """
    params = {
        "service": "address",
        "request": "getcoord",
        "version": "2.0",
        "crs": "epsg:4326",
        "address": address,
        "refine": "true",
        "simple": "false",
        "format": "json",
        "type": addr_type,
        "key": VWORLD_API_KEY,
    }
    res = requests.get(GEOCODER_URL, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    try:
        if data["response"]["status"] != "OK":
            return None
        point = data["response"]["result"]["point"]
        return float(point["x"]), float(point["y"])  # (경도, 위도)
    except (KeyError, TypeError):
        return None


# ---- 확인 완료: 주소 -> PNU (검색 API 2.0) ----
# 지번주소와 도로명주소 모두 지원.
#  - category="parcel" : 지번주소 (예: 서울특별시 강남구 역삼동 737)
#  - category="road"   : 도로명주소 (예: 서울특별시 강남구 테헤란로 152)
# 두 방식 모두 items[0].id 로 동일한 PNU(19자리)를 돌려준다.
# 카테고리가 맞지 않으면 NOT_FOUND 가 오므로, 추정한 카테고리로 먼저 조회하고
# 결과가 없으면 반대 카테고리로 자동 재시도(폴백)한다.
VWORLD_SEARCH_URL = "https://api.vworld.kr/req/search"

# "○○로 12", "○○길 3-4" 처럼 도로명(로/길 + 숫자)이 있으면 도로명주소로 본다.
_ROAD_RE = re.compile(r"(로|길)\s*\d")


def _search_pnu(address: str, category: str) -> str | None:
    """지정한 category(parcel/road)로 검색해 PNU를 반환. 없으면 None."""
    params = {
        "service": "search",
        "request": "search",
        "version": "2.0",
        "size": "1",
        "page": "1",
        "query": address,
        "type": "address",
        "category": category,
        "format": "json",
        "errorformat": "json",
        "key": VWORLD_API_KEY,
    }
    res = requests.get(VWORLD_SEARCH_URL, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()
    try:
        if data["response"]["status"] != "OK":
            return None
        items = data["response"]["result"]["items"]
        return items[0].get("id") if items else None
    except (KeyError, IndexError, TypeError):
        return None


def address_to_pnu(address: str) -> str | None:
    """
    지번주소 또는 도로명주소를 입력받아 PNU(19자리)를 반환한다.
    도로명 패턴이면 road → parcel 순으로, 아니면 parcel → road 순으로 시도한다.
    """
    if not address or not address.strip():
        return None

    # 도로명 패턴이면 road 를 먼저, 아니면 parcel 을 먼저 시도
    primary, fallback = ("road", "parcel") if _ROAD_RE.search(address) else ("parcel", "road")

    pnu = _search_pnu(address, primary)
    if pnu:
        return pnu
    return _search_pnu(address, fallback)


if __name__ == "__main__":
    for test_addr in ["서울특별시 강남구 역삼동 737",      # 지번
                      "서울특별시 강남구 테헤란로 152"]:    # 도로명
        print(test_addr, "-> PNU:", address_to_pnu(test_addr))

