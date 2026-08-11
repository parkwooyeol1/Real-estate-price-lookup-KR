# -*- coding: utf-8 -*-
"""
API 인증키 설정

■ 키를 새로 발급받아 갱신하는 방법 (2가지)

  방법 A) 재빌드 없이 — 권장, exe 배포본에 적합
    실행파일(부동산공시가격조회.exe / .app) 과 같은 폴더에
    `vworld_key.txt` 파일을 만들고 아래처럼 적으면 됩니다.
        1줄: 새 인증키
        2줄: (선택) 도메인 — 키 발급 시 등록한 URL. 생략하면 localhost.
      예)
        2E9BB59C-XXXX-XXXX-XXXX-XXXXXXXXXXXX
        localhost
    프로그램을 다시 실행하면 이 파일의 키를 우선 사용합니다. (재빌드 불필요)

  방법 B) 소스에서 직접 — 개발/재빌드 시
    아래 _DEFAULT_VWORLD_KEY 값을 바꾸고 다시 빌드하세요.

■ 브이월드(VWorld) 인증키
   - 발급/재발급: https://www.vworld.kr → 로그인 → 마이페이지 → 인증키 관리
   - 용도: 주소 → PNU 변환(검색 API) 및 공시가격(NED) 조회
   - 주의: 아래 도메인(VWORLD_DOMAIN)은 '키 발급 시 등록한 URL' 과 정확히 같아야 함(예: localhost).
     도메인이 다르면 정상 키라도 요청이 거부됩니다.

■ 공공데이터포털 인증키 (현재 미사용)
   - 발급: https://www.data.go.kr
"""

import os
import sys

# ── 내장 기본값 (외부 vworld_key.txt 가 없을 때 사용) ─────────────────
_DEFAULT_VWORLD_KEY = "여기에_VWORLD_인증키_입력"
_DEFAULT_VWORLD_DOMAIN = "localhost"

KEY_FILENAME = "vworld_key.txt"


def _app_dir() -> str:
    """키 파일을 찾을 폴더. 빌드된 실행파일이면 그 실행파일이 있는 폴더,
    개발 실행이면 이 소스가 있는 폴더."""
    if getattr(sys, "frozen", False):        # PyInstaller 로 빌드된 상태
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _load_vworld() -> tuple[str, str]:
    """실행파일 옆 vworld_key.txt 가 있으면 그 키(+도메인)를, 없으면 내장 기본값을 반환."""
    key, domain = _DEFAULT_VWORLD_KEY, _DEFAULT_VWORLD_DOMAIN
    path = os.path.join(_app_dir(), KEY_FILENAME)
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f
                         if ln.strip() and not ln.strip().startswith("#")]
            if lines:
                key = lines[0]
            if len(lines) > 1:
                domain = lines[1]
    except Exception:
        pass                                  # 파일 문제 시 조용히 기본값 사용
    return key, domain


VWORLD_API_KEY, VWORLD_DOMAIN = _load_vworld()

DATA_GO_KR_API_KEY = "여기에_공공데이터포털_인증키_입력"
