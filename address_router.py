# -*- coding: utf-8 -*-
"""
주소 자동파싱 + 유형판별 + 분기 라우팅 (이 프로그램의 핵심)

사용자는 유형(토지/단독/공동주택)을 직접 고르지 않는다.
주소를 통째로 붙여넣으면 아래 흐름으로 알아서 처리한다.

  1) 입력 파싱 : "OO동 OO호"(숫자+동/호)를 분리 → 아파트 동/호로 보관, 나머지는 기본주소
  2) PNU 변환 : 기본주소 → PNU (pnu_util, VWorld 검색 API)
  3) 유형 판별 : PNU로 공동주택가격 데이터가 있으면 '공동주택', 없으면 '토지/단독'
  4) 분기 처리 :
       - 공동주택 → apt_api (동/호로 세대 특정. 동/호가 없으면 안내)
       - 토지/단독 → land_api + house_api 병합
  5) 결과 반환 : 유형에 맞는 dict

반환 예:
  {
    "ok": True,
    "type": "apartment" | "land_house",
    "input": "...", "base_address": "...", "pnu": "...",
    "apt_dong": "27", "apt_ho": "1401",
    "needs_dong_ho": False,   # 공동주택인데 동/호 미입력이면 True
    "data": {...} 또는 [...],
    "message": None 또는 "안내문구",
  }
  실패 시: {"ok": False, "message": "..."}
"""

import re

import pnu_util
import land_api
import house_api
import apt_api
import region_fallback

# 아파트 동/호/층 패턴.
#  - 앞에 "제"가 붙는 등기부 표기("제3동 제1층 제103호")를 허용한다.
#  - 동/호 뒤에 한글이 이어지면(예: "동림그린파크"의 "동") 단지명으로 보고 제외한다
#    (음의 전방탐색 (?![가-힣])). 이렇게 해야 "288-2 동림그린파크"의 "2 동"을
#    아파트 동으로 잘못 잡지 않는다.
#  - 법정동(역삼동/대치동 등 한글+동)도 숫자가 없으므로 걸리지 않는다.
_DONG_RE = re.compile(r"(?:제\s*)?(\d+)\s*동(?![가-힣])")          # 숫자 동: 3동, 제27동
# 한글 라벨 동(가/나/다동 등)은 '뒤에 호/층이 바로 이어질 때만' 건물 동으로 본다.
# 이렇게 해야 지번이 뒤따르는 법정동('제기동 100', '사동 1543 …')을 오인식하지 않는다.
_DONG_KR_CTX = r"(?=\s*(?:제\s*)?\d+\s*[호층])"
_DONG_KR_RE = re.compile(r"제\s*([가-힣])\s*동(?![가-힣])" + _DONG_KR_CTX)   # 제가동 (등기부: '제'+한글)
_DONG_KR_LOOSE_RE = re.compile(r"(?:^|\s)([가-힣])\s*동(?![가-힣])" + _DONG_KR_CTX)  # 가동 (제 없음)
_HO_RE = re.compile(r"(?:제\s*)?(\d+)\s*호(?![가-힣])")                       # 숫자 호
_HO_KR_RE = re.compile(r"제\s*([가-힣])\s*(\d+)\s*호(?![가-힣])")              # 제비02호/제비 02호
_HO_KR_BARE_RE = re.compile(r"(?<![가-힣제])(?!제)([가-힣])\s*(\d+)\s*호(?![가-힣])")  # 비02호(제 없음, '제'는 접두 아님)
# 층: 숫자층 + '지하/반지하/옥탑'층까지 제거(값은 안 쓰고 기본주소 정리용)
_FLOOR_RE = re.compile(r"(?:제\s*)?(?:지하|반지하|옥탑|\d+)\s*층")
_ETC_PARCEL_RE = re.compile(r"외\s*\d+\s*필지")  # "1230-1외 4필지"의 '외 4필지' 노이즈 제거


def parse_address(raw: str) -> tuple[str, str | None, str | None]:
    """
    주소 문자열에서 아파트 동/호를 분리한다.
    반환: (기본주소, 동 or None, 호 or None)  — 동은 "27" 또는 "가"처럼 라벨 그대로.

    예) "서울특별시 강남구 대치동 316 27동 1401호"
        -> ("서울특별시 강남구 대치동 316", "27", "1401")
    예) "경상남도 통영시 용남면 삼화리 288-2 동림그린파크 제3동 제1층 제103호"
        -> ("경상남도 통영시 용남면 삼화리 288-2 동림그린파크", "3", "103")
    예) "제주특별자치도 서귀포시 동홍동 1230-1외 4필지 동홍반석아르미 제가동 제6층 제703호"
        -> ("제주특별자치도 서귀포시 동홍동 1230-1 동홍반석아르미", "가", "703")
    """
    text = raw.strip()

    # 호 인식: 1)제+한글 호(제비02호)  2)맨 한글 호(비02호)  3)숫자 호
    ho = None
    m = _HO_KR_RE.search(text)
    if m:
        ho = m.group(1) + m.group(2)          # '비' + '02' = '비02'
    else:
        m = _HO_KR_BARE_RE.search(text)
        if m:
            ho = m.group(1) + m.group(2)
        else:
            m = _HO_RE.search(text)
            if m:
                ho = m.group(1)

    # 동 인식: 1)숫자 동  2)제+한글 동  3)(호가 있으면) 맨 한글 동
    dong = None
    m = _DONG_RE.search(text)
    if m:
        dong = m.group(1)
        base = _DONG_RE.sub(" ", text)
    else:
        m = _DONG_KR_RE.search(text)
        if m:
            dong = m.group(1)
            base = _DONG_KR_RE.sub(" ", text)
        else:
            m = _DONG_KR_LOOSE_RE.search(text) if ho else None
            if m:
                dong = m.group(1)
                base = _DONG_KR_LOOSE_RE.sub(" ", text, count=1)
            else:
                base = text

    # 호/층/‘외 N필지’ 노이즈 제거 → 기본주소 (단지명은 남겨도 VWorld가 지번을 찾는다)
    base = _HO_KR_RE.sub(" ", base)
    base = _HO_KR_BARE_RE.sub(" ", base)
    base = _HO_RE.sub(" ", base)
    base = _FLOOR_RE.sub(" ", base)
    base = _ETC_PARCEL_RE.sub(" ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base, dong, ho


def _land_section(pnu: str) -> dict:
    return land_api.get_land_info(pnu)   # jimok/area/jiga_yeondo/jiga


def _house_section(pnu: str) -> dict:
    return house_api.get_house_info(pnu)  # price_yeondo/price/lot_area/bld_area


def _apt_section(pnu: str, dong, ho, extra_parcels: int = 0) -> dict:
    """공동주택 섹션. 아파트가 아니면 not_apt=True.

    extra_parcels: 주소의 '외 N필지' 개수. 여러 필지에 걸친 집합건물은 공동주택가격이
      '대표지번'에만 등록되므로, 입력 필지에 데이터가 없으면 인접 부번(±N)에서 대표지번을 찾는다.
    """
    if not apt_api.is_apartment(pnu):
        # 주소가 '외 N필지' 형태로 들어온 경우에만: 여러 필지에 걸친 집합건물인데
        # 입력 지번엔 데이터가 없는 상황. 자동 조회하지 않고, 인접 필지에서 '예상 지번'
        # 후보를 찾아 사용자가 직접 고르게 한다.
        if extra_parcels and ho:
            cands = apt_api.nearby_apt_candidates(pnu, span=extra_parcels)
            if cands:
                return {"not_apt": False, "rows": [], "needs_dong_ho": False,
                        "apt_candidates": cands,
                        "message": ("입력한 지번에는 공시가격 데이터가 없습니다.\n"
                                    "이 단지는 여러 필지(외 %d필지)에 걸쳐 있어, 데이터가 있는 다른 "
                                    "지번으로 조회해야 합니다.\n아래 예상 지번 중 하나를 선택하세요."
                                    % extra_parcels)}
        return {"not_apt": True, "rows": [], "needs_dong_ho": False,
                "message": "이 주소는 공동주택(아파트/연립/다세대)이 아닙니다."}
    rows = apt_api.get_apt_info(pnu, dong, ho)

    # 세대 특정 성공: 호가 있고, (동 지정됐거나 결과가 1건) → 그 세대를 보여준다
    if ho and rows and (dong or len(rows) == 1):
        return {"not_apt": False, "rows": rows, "message": None}

    # 여기부터는 세대를 못 짚음 → '아파트는 맞음(True)'이므로, 사용자가 동/호를 수동 선택하게 한다.
    # 단지 전체 세대를 한 번 가져와 동/호 목록을 구성한다.
    all_units = apt_api.get_apt_info(pnu)
    danji = (rows[0] if rows else (all_units[0] if all_units else {})).get("danji_name") \
        or apt_api.apt_name(pnu)
    dongs = apt_api.unit_dongs(all_units)
    tdong = apt_api._norm_dong(dong) if dong else None

    def pick(level, cur_dong, options, message):
        return {"not_apt": False, "rows": [], "message": message,
                "apt_pick": {"level": level, "danji": danji,
                             "dong": cur_dong, "options": options}}

    # 동이 유효(단지에 존재)하거나, 애초에 '동이 없는 단지'면 → 호만 선택하는 화면
    if (tdong and tdong in dongs) or (not dongs and dong is not None) \
            or (not dongs and ho):
        hos = apt_api.unit_hos(all_units, dong if (tdong and tdong in dongs) else None)
        head = (f"{dong}동에 '{ho}호'가 없습니다. " if ho else
                (f"{dong}동의 " if dong else "")) + "호를 선택하세요."
        return pick("ho", tdong, hos, head)

    # 그 외(동 미지정/동 불일치) → 동을 먼저 선택하는 화면
    if dong:
        msg = f"'{dong}동'을 이 단지에서 찾지 못했습니다. 동을 선택하세요."
    elif ho:
        msg = f"'{ho}호'가 여러 동에 있거나 확인이 필요합니다. 동을 선택하세요."
    else:
        msg = "동을 선택하세요."
    return pick("dong", None, dongs, msg)


def _run_sections(pnu: str, sel: str | None, dong, ho, extra_parcels: int = 0) -> dict:
    """주어진 PNU로 유형에 맞는 섹션들을 조회해 dict 로 반환."""
    sec: dict = {}
    if sel == "apt":
        sec["apt"] = _apt_section(pnu, dong, ho, extra_parcels)
    elif sel == "land":
        sec["land"] = _land_section(pnu)
    elif sel == "house":
        sec["house"] = _house_section(pnu)
    else:
        # 전체/자동: 공동주택이면 공동주택만, 아니면 토지 + 단독주택
        apt = _apt_section(pnu, dong, ho, extra_parcels)
        if not apt.get("not_apt"):
            sec["apt"] = apt
        else:
            sec["land"] = _land_section(pnu)
            sec["house"] = _house_section(pnu)
    return sec


def _sections_empty(sec: dict) -> bool:
    """조회된 섹션에 실제 데이터가 하나도 없는지(= NED 미조회) 판단."""
    for name, d in sec.items():
        if name == "land" and any(d.get(k) is not None for k in ("jiga", "jimok", "area")):
            return False
        if name == "house" and d.get("price") is not None:
            return False
        # 공동주택: 단지로 인식됐고(세대/동·호선택/예상지번후보) 뭔가 있으면 비어있지 않음
        if name == "apt" and not d.get("not_apt") and (
                d.get("rows") or d.get("apt_pick") or d.get("apt_candidates")):
            return False
    return True


def _flag_no_data(out: dict, pnu: str) -> None:
    """
    PNU 변환은 됐지만 공시가격 API(NED)에서 이 필지 데이터를 하나도 못 가져온
    경우를 감지해 out["no_data"]=True + 안내 메시지를 단다.

    판별: 개별공시지가/지목/면적(토지특성)이 전부 없고 주택가격도 없으면
          '필지 유형 문제(나대지·상가)'가 아니라 'NED 미등재(신설·개편 행정구역 등)'로 본다.
          (나대지·상가는 주택가격만 없고 토지 데이터는 나온다.)
    """
    sec = out.get("sections", {})
    if "apt" in sec:                     # 공동주택 경로는 별도 안내를 이미 함
        return
    house = sec.get("house")
    if house and house.get("price") is not None:
        return                            # 주택가격이 나왔으면 정상

    land = sec.get("land")
    if land is not None:
        got_land = any(land.get(k) is not None for k in ("jiga", "jimok", "area"))
    else:
        # 주택 단독조회 등 land 섹션이 없으면 토지특성으로 등재 여부만 확인
        try:
            lc = land_api.get_land_char(pnu)
            got_land = any(lc.get(k) is not None for k in ("jimok", "area"))
        except Exception:
            got_land = True               # 확인 불가 시 오탐 방지 위해 기존 동작 유지

    if not got_land:
        out["no_data"] = True
        out["message"] = (
            "이 주소의 공시가격 데이터를 가져오지 못했습니다.\n"
            "최근 신설·개편된 행정구역(예: 인천 제물포구·영종구)은 공시가격 API에\n"
            "아직 반영되지 않았을 수 있습니다.\n"
            "부동산공시가격알리미(realtyprice.kr)에서 직접 확인하세요."
        )


def lookup(raw_address: str, sel: str | None = None) -> dict:
    """
    주소 한 줄을 받아 조회 결과를 반환한다.

    sel: 조회할 유형 (None=전체/자동)
      - None   : 자동 — 공동주택이면 공동주택만, 아니면 토지+단독주택
      - "land" : 토지(개별공시지가)만
      - "house": 단독주택가격만
      - "apt"  : 공동주택가격만

    반환:
      {
        "ok": True/False, "message": str|None,
        "input":.., "base_address":.., "pnu":.., "apt_dong":.., "apt_ho":..,
        "sections": {              # 있는 것만 (렌더 순서: land→house→apt)
          "land":  {jimok, area, jiga_yeondo, jiga},
          "house": {price_yeondo, price, lot_area, bld_area},
          "apt":   {not_apt, rows, needs_dong_ho, message},
        }
      }
    """
    if not raw_address or not raw_address.strip():
        return {"ok": False, "message": "주소를 입력하세요."}

    base, dong, ho = parse_address(raw_address)
    m = _ETC_PARCEL_RE.search(raw_address)     # "외 N필지" → 집합건물 연접 필지 수
    extra_parcels = int(re.search(r"\d+", m.group()).group()) if m else 0

    try:
        pnu = pnu_util.address_to_pnu(base)
    except Exception as e:  # 네트워크/응답 오류
        return {"ok": False, "message": f"주소→PNU 변환 중 오류: {e}"}
    if not pnu:
        return {"ok": False,
                "message": f"주소를 PNU로 변환하지 못했습니다.\n입력 주소를 확인하세요: '{base}'"}

    out = {"ok": True, "input": raw_address, "base_address": base, "pnu": pnu,
           "apt_dong": dong, "apt_ho": ho, "sections": {}, "message": None,
           "legacy_pnu": None}

    try:
        # 1) 항상 '새 PNU'로 먼저 조회한다. (VWorld가 새 코드로 반영되면 여기서 성공)
        eff_pnu = pnu
        sec = _run_sections(pnu, sel, dong, ho, extra_parcels)

        # 2) 데이터가 하나도 없고, 통합으로 새 코드가 부여된 시도(전남광주통합 등)라면
        #    옛 행정코드 PNU로 딱 한 번 재시도한다. (지금처럼 새 코드 미반영 기간의 임시 폴백)
        if _sections_empty(sec) and region_fallback.is_merged_new_code(pnu):
            legacy = region_fallback.legacy_pnu(pnu, base)
            if legacy:
                sec2 = _run_sections(legacy, sel, dong, ho, extra_parcels)
                if not _sections_empty(sec2):
                    sec = sec2
                    eff_pnu = legacy
                    out["legacy_pnu"] = legacy
        out["sections"] = sec
    except Exception as e:
        return {"ok": False, "message": f"조회 중 오류: {e}",
                "input": raw_address, "base_address": base, "pnu": pnu}

    _flag_no_data(out, eff_pnu)
    return out


if __name__ == "__main__":
    tests = [
        ("서울특별시 강남구 역삼동 808", None),                       # 토지(상업건물)
        ("서울특별시 종로구 가회동 11", None),                        # 단독주택
        ("경상남도 통영시 용남면 삼화리 288-2 3동 103호", None),      # 공동주택
        ("서울특별시 강남구 역삼동 808", "house"),                    # 단독주택만 강제
    ]
    import json
    for t, s in tests:
        print("입력:", t, "| sel:", s)
        print(json.dumps(lookup(t, s), ensure_ascii=False, indent=2))
        print("-" * 60)
