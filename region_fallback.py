# -*- coding: utf-8 -*-
"""
통합 광역시도(2026-07-01) 신규 행정코드 → 옛 코드 폴백.

2026-07-01 전라남도 + 광주광역시가 '전남광주통합특별시'(새 시도코드 12)로 통합되면서
VWorld 검색은 새 코드로 PNU를 돌려주지만, NED 공시가격 데이터는 아직 옛 코드
(전남 46 / 광주 29)로만 저장돼 있어 새 PNU로는 0건이 나온다.

통합 시 **시도+시군구(PNU 앞 5자리)만 바뀌고 읍면동·리·지번(뒤 14자리)은 그대로**이므로,
새 PNU로 데이터가 없을 때 앞 5자리를 옛 시군구코드 후보로 바꿔가며 NED를 조회하고,
**실제 데이터가 나오고 읍면동·리 이름까지 일치하는** 코드만 채택한다.
(잘못된 후보는 데이터가 없거나 이름이 안 맞아 자동 배제되므로 오조회 위험이 없다.)

주의:
- 이건 '새 코드 미반영' 동안의 임시 폴백이다. VWorld가 NED를 새 코드로 재적재하면
  새 PNU 조회가 바로 성공하므로 이 폴백은 애초에 호출되지 않는다(= 자동으로 새 코드 사용).
- 인천 신설구(제물포·영종·검단)는 옛 코드에도 데이터가 없어 여기 대상이 아니다(계속 no_data).
- 대전충남특별시는 현재 VWorld가 옛 코드(대전 30 / 충남 44)로 조회해줘 폴백이 필요 없다.
"""

import re
import requests
from config import VWORLD_API_KEY, VWORLD_DOMAIN

_NED_LAND = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"

# 새 시도코드 → 그 지역에 속하는 '옛 시군구코드(5자리)' 후보 목록.
_LEGACY_SGG = {
    "12": [  # 전남광주통합특별시 = 옛 광주광역시(29) + 옛 전라남도(46)
        # 옛 광주광역시 자치구
        "29110", "29140", "29155", "29170", "29200",
        # 옛 전라남도 시/군
        "46110", "46130", "46150", "46170", "46230",
        "46710", "46720", "46730", "46770", "46780", "46790",
        "46800", "46810", "46820", "46830", "46840", "46860",
        "46870", "46880", "46890", "46900", "46910",
    ],
}

# 같은 지역을 다시 조회할 때 빠르게: 신5자리 → 옛5자리(없으면 None)
_cache: dict[str, str | None] = {}

# 주소에서 읍/면/동/가/리 토큰만 뽑아 ldCodeNm 검증에 쓴다.
_TOKEN_RE = re.compile(r"[가-힣]+(?:읍|면|동|가|리)")


def _dong_ri_tokens(address: str | None) -> list[str]:
    return _TOKEN_RE.findall(address or "")


def _ned_ldcodenm(pnu: str) -> str | None:
    """PNU로 개별공시지가를 조회해 데이터가 있으면 법정동명(ldCodeNm)을 반환."""
    params = {
        "key": VWORLD_API_KEY, "domain": VWORLD_DOMAIN, "pnu": pnu,
        "format": "json", "numOfRows": "1", "pageNo": "1",
    }
    try:
        data = requests.get(_NED_LAND, params=params, timeout=10).json()
    except Exception:
        return None
    node = data.get("indvdLandPrices")
    if isinstance(node, dict) and node.get("field"):
        return node["field"][0].get("ldCodeNm")
    return None


def is_merged_new_code(pnu: str | None) -> bool:
    """이 PNU가 폴백 대상(통합으로 새 코드가 부여된 시도)인지."""
    return bool(pnu and len(pnu) == 19 and pnu[:2] in _LEGACY_SGG)


def legacy_pnu(new_pnu: str | None, address: str | None = None) -> str | None:
    """
    새 코드 PNU를 옛 코드 PNU로 변환한다. 대상이 아니거나 찾지 못하면 None.
    실제 NED 데이터가 나오고(존재) 읍면동·리 이름이 주소와 일치하는 코드만 채택.
    """
    if not is_merged_new_code(new_pnu):
        return None

    new5, tail = new_pnu[:5], new_pnu[5:]
    if new5 in _cache:
        old5 = _cache[new5]
        return (old5 + tail) if old5 else None

    want = _dong_ri_tokens(address)
    for old5 in _LEGACY_SGG[new_pnu[:2]]:
        cand = old5 + tail
        nm = _ned_ldcodenm(cand)
        if nm and (not want or all(t in nm for t in want)):
            _cache[new5] = old5
            return cand

    _cache[new5] = None
    return None


if __name__ == "__main__":
    tests = [
        ("1275025024101990001", "전남광주통합특별시 보성군 보성읍 봉산리 199-1"),
        ("1221012200101000001", "전남광주통합특별시 광주 동구 학동 100"),
        ("1230010900101400000", "전남광주통합특별시 광주 북구 운암동 100"),
    ]
    for pnu, addr in tests:
        print(addr)
        print("   신:", pnu, "-> 옛:", legacy_pnu(pnu, addr))
