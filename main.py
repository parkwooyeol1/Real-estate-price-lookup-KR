# -*- coding: utf-8 -*-
"""
부동산 공시가격 통합조회 - GUI (customtkinter, 애플 스타일)

주소 한 줄만 입력하고 [조회]를 누르면
개별공시지가 / 개별단독주택가격 / 공동주택가격을 자동 판별해 보여준다.

- 지번주소 / 도로명주소 모두 입력 가능
- 유형(토지/단독주택/공동주택) 선택 조회, 선택 안 하면 전체(자동)
- 공시가격 × 1.3 환산액을 함께 표시
- 조회 후 [소유지분] 버튼으로 지분(분모/분자)을 입력하면 지분 몫을 함께 표시
- 라이트/다크 모드 자동

실행:  python main.py   (필요: pip install customtkinter)
"""

import os
import re
import sys
import threading
import customtkinter as ctk

import address_router
import share_util


def resource_path(name: str) -> str:
    """개발 실행/ PyInstaller onefile 번들 양쪽에서 리소스 경로를 반환."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


ICON_PATH = resource_path("app-icon.ico")

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

MULT = 1.3                       # 공시가격 환산 배율(고정)
MAX_ADDR = 10                    # 동시에 조회할 수 있는 최대 주소 개수
FONT = "맑은 고딕"

# 애플풍 무채색 색상 (라이트, 다크)
BG        = ("#F5F5F7", "#000000")
CARD      = ("#FFFFFF", "#1C1C1E")
FIELD     = ("#FFFFFF", "#2C2C2E")
TEXT      = ("#1D1D1F", "#F5F5F7")
SUB       = ("#86868B", "#98989D")
LINE      = ("#E5E5EA", "#3A3A3C")
BORDER    = ("#D2D2D7", "#48484A")   # 아웃라인 버튼 공통 테두리(깔끔·일정하게)
RADIUS    = 10                        # 버튼 공통 라운드
ACCENT    = ("#1D1D1F", "#F5F5F7")   # 무채색 강조(버튼/선택 배경)
ACCENT_H  = ("#3A3A3C", "#D1D1D6")   # hover
ON_ACCENT = ("#FFFFFF", "#000000")   # 강조 배경 위 글자
SEG_SEL   = ("#FFFFFF", "#636366")   # iOS식 선택 세그먼트(흰색)
BAND      = ("#111111", "#F5F5F7")   # 결과값 강조 밴드 배경(블랙 카드)
ON_BAND   = ("#FFFFFF", "#111111")   # 밴드 위 글자
ON_BAND_S = ("#B0B0B5", "#6B6B70")   # 밴드 위 계산식(연한 글자)

SEL_MAP = {"전체": None, "토지": "land", "단독주택": "house", "공동주택": "apt"}


def _fmt4(v) -> str:
    """소수점 최대 4자리 + 천단위 콤마, 뒤쪽 0은 정리 (예: 6,159,951.024)."""
    return f"{float(v):,.4f}".rstrip("0").rstrip(".")


def won(v) -> str:
    """표시용 금액 — 소수점 4자리까지."""
    if v is None:
        return "-"
    try:
        return _fmt4(v) + "원"
    except (ValueError, TypeError):
        return str(v)


def won_copy(v) -> str:
    """복사용 금액 — 소수점 버림(정수), '원' 없이 숫자만 복사."""
    try:
        return f"{int(float(v)):,}"     # int(): 양수 기준 버림, 단위(원) 제외
    except (ValueError, TypeError):
        return str(v)


def area(v) -> str:
    return _fmt4(v) + "㎡" if isinstance(v, (int, float)) else "-"


def bunui(share) -> str:
    """지분 dict → '1123 분의 112.5' (분모 분의 분자)."""
    def t(x):
        return str(int(x)) if float(x).is_integer() else f"{x:g}"
    return f"{t(share['denominator'])} 분의 {t(share['numerator'])}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("부동산 공시가격 조회")
        self.geometry("560x700")
        self.minsize(480, 600)
        self.configure(fg_color=BG)
        self._set_icon()

        self._shares = {}              # row_index -> 소유지분 dict (주소별 개별 적용)
        self._cur_share = None         # 현재 렌더 중인 블록의 지분(임시)
        self._last_results = None      # [(row_index, address, result_dict), ...]

        self.f_h1    = ctk.CTkFont(family=FONT, size=23, weight="bold")
        self.f_title = ctk.CTkFont(family=FONT, size=15, weight="bold")
        self.f_key   = ctk.CTkFont(family=FONT, size=13)
        self.f_band_l = ctk.CTkFont(family=FONT, size=13, weight="bold")
        self.f_band  = ctk.CTkFont(family=FONT, size=24, weight="bold")
        self.f_sub   = ctk.CTkFont(family=FONT, size=12)
        self.f_btn   = ctk.CTkFont(family=FONT, size=14, weight="bold")
        self.f_field = ctk.CTkFont(family=FONT, size=14)
        # 결과 정보 행 통일용 (라벨·숫자 동일 크기 14: 최종가격만 크게, 나머지는 한 크기)
        self.f_info   = ctk.CTkFont(family=FONT, size=14)
        self.f_info_b = ctk.CTkFont(family=FONT, size=14, weight="bold")

        # ── 헤더 ─────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 0))

        ctk.CTkLabel(header, text="부동산 공시가격 조회",
                     font=self.f_h1, text_color=TEXT).pack(anchor="w")

        # 주소 입력 행들(최대 MAX_ADDR 개) — + 버튼으로 추가, ✕ 로 제거.
        # 행이 많아져도 헤더가 무한정 커지지 않도록 높이 제한 스크롤 영역에 담는다.
        self.rows = []
        self.addr_box = ctk.CTkScrollableFrame(header, fg_color="transparent", height=118)
        self.addr_box.pack(fill="x", pady=(14, 0))

        crow = ctk.CTkFrame(header, fg_color="transparent")
        crow.pack(fill="x", pady=(8, 0))
        self.add_btn = ctk.CTkButton(crow, text="+ 주소 추가", width=120, height=44,
                                     corner_radius=12, font=self.f_key,
                                     fg_color="transparent", border_width=1,
                                     border_color=BORDER, text_color=TEXT, hover_color=CARD,
                                     command=self._add_row)
        self.add_btn.pack(side="left")
        self.btn = ctk.CTkButton(crow, text="조회", width=90, height=44,
                                 corner_radius=12, font=self.f_btn,
                                 fg_color=ACCENT, hover_color=ACCENT_H,
                                 text_color=ON_ACCENT, command=self.on_search)
        self.btn.pack(side="right")
        self._add_row()          # 첫 입력줄

        srow = ctk.CTkFrame(header, fg_color="transparent")
        srow.pack(fill="x", pady=(14, 0))
        self.type_seg = ctk.CTkSegmentedButton(
            srow, values=["전체", "토지", "단독주택", "공동주택"],
            font=self.f_key, height=34, corner_radius=10,
            fg_color=LINE, selected_color=SEG_SEL, selected_hover_color=SEG_SEL,
            unselected_color=LINE, unselected_hover_color=LINE, text_color=TEXT)
        self.type_seg.set("전체")
        self.type_seg.pack(side="left")

        # 소유지분은 결과 블록마다 개별 버튼으로 제공한다(주소별 각각 적용).
        self.reset_btn = ctk.CTkButton(
            srow, text="초기화", width=64, height=34, corner_radius=10,
            font=self.f_key, fg_color="transparent", border_width=1,
            border_color=BORDER, text_color=TEXT, hover_color=CARD,
            command=self.on_reset)
        self.reset_btn.pack(side="right")

        # 여러 주소 환산가격을 한 창에 모아 보는 요약 버튼
        self.summary_btn = ctk.CTkButton(
            srow, text="한눈에 보기", width=100, height=34, corner_radius=10,
            font=self.f_key, fg_color="transparent", border_width=1,
            border_color=BORDER, text_color=TEXT, hover_color=CARD,
            command=self.open_summary)
        self.summary_btn.pack(side="right", padx=(0, 8))

        # ── 상태 ─────────────────────────────
        self.status = ctk.CTkLabel(self, text="주소를 입력하고 조회하세요.",
                                   font=self.f_sub, text_color=SUB, anchor="w")
        self.status.pack(fill="x", padx=26, pady=(16, 0))

        # ── 결과 ─────────────────────────────
        self.results = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.results.pack(fill="both", expand=True, padx=20, pady=(8, 20))
        self._empty_state("주소를 입력하면 여기에 결과가 표시됩니다.")

    def _apply_icon(self, win):
        """주어진 창(win)에 앱 아이콘을 건다. customtkinter가 초기화 중 자체
        아이콘으로 덮어쓰므로, 즉시 + 지연 두 번 적용해 확실히 반영한다."""
        if not os.path.exists(ICON_PATH):
            return

        def apply():
            try:
                if win.winfo_exists():
                    win.iconbitmap(ICON_PATH)
            except Exception:
                pass
        apply()
        win.after(300, apply)

    def _set_icon(self):
        """메인 창/작업표시줄 아이콘 설정."""
        self._apply_icon(self)

    def _empty_state(self, text):
        self._clear_results()
        ctk.CTkLabel(self.results, text=text, font=self.f_key,
                     text_color=SUB).pack(pady=70)

    # ── 주소 입력행 관리 ─────────────────────────────
    def _add_row(self, text=""):
        if len(self.rows) >= MAX_ADDR:
            return
        fr = ctk.CTkFrame(self.addr_box, fg_color="transparent")
        fr.pack(fill="x", pady=3)
        var = ctk.StringVar(value=text)
        entry = ctk.CTkEntry(fr, textvariable=var, placeholder_text="주소를 입력하세요",
                             height=44, corner_radius=12, border_width=0,
                             fg_color=FIELD, font=self.f_field)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.on_search())
        xbtn = ctk.CTkButton(fr, text="✕", width=40, height=44, corner_radius=12,
                             font=self.f_key, fg_color="transparent", border_width=1,
                             border_color=BORDER, text_color=SUB, hover_color=CARD,
                             command=lambda: self._remove_row(fr))
        xbtn.pack(side="left", padx=(8, 0))
        self.rows.append({"frame": fr, "var": var, "entry": entry})
        self._update_add_btn()
        entry.focus()

    def _remove_row(self, fr):
        if len(self.rows) <= 1:
            self.rows[0]["var"].set("")     # 마지막 한 줄은 비우기만
            return
        self.rows = [r for r in self.rows if r["frame"] is not fr]
        fr.destroy()
        self._update_add_btn()

    def _update_add_btn(self):
        n = len(self.rows)
        self.add_btn.configure(
            text=f"+ 주소 추가 ({n}/{MAX_ADDR})",
            state="normal" if n < MAX_ADDR else "disabled")

    # ── 조회 ─────────────────────────────
    def on_search(self):
        addrs = [(i, r["var"].get().strip()) for i, r in enumerate(self.rows)]
        addrs = [(i, a) for i, a in addrs if a]
        if not addrs:
            self.status.configure(text="주소를 입력하세요.")
            return
        sel = SEL_MAP.get(self.type_seg.get())
        self.btn.configure(state="disabled")
        self.status.configure(text=f"조회 중… ({len(addrs)}건)")
        self._clear_results()
        threading.Thread(target=self._work, args=(addrs, sel), daemon=True).start()

    def on_reset(self):
        """입력행·결과·소유지분·유형선택을 초기 상태로 되돌린다."""
        for r in self.rows[1:]:
            r["frame"].destroy()
        self.rows = self.rows[:1]
        self.rows[0]["var"].set("")
        self._update_add_btn()
        self.type_seg.set("전체")
        self._shares = {}
        self._last_results = None
        self.status.configure(text="주소를 입력하고 조회하세요.")
        self._empty_state("주소를 입력하면 여기에 결과가 표시됩니다.")
        self.rows[0]["entry"].focus()

    def _apply_row(self, row_index, address):
        """지정한 입력행의 주소를 바꾸고 전체 재조회한다(다중 조회 상태 유지)."""
        if not (0 <= row_index < len(self.rows)):
            row_index = 0
        self.rows[row_index]["var"].set(address)
        self.on_search()

    @staticmethod
    def _parcel_addr(r, jibun):
        """결과 r 의 기본주소에서 지번만 바꾼 재조회 주소를 만든다."""
        base = (r or {}).get("base_address", "")
        addr = re.sub(r"\s*\d+(-\d+)?\s*$", "", base).strip() + f" {jibun}"
        if r.get("apt_dong"):
            addr += f" {r['apt_dong']}동"
        if r.get("apt_ho"):
            addr += f" {r['apt_ho']}호"
        return addr.strip()

    @staticmethod
    def _pick_addr(r, dong=None, ho=None):
        """결과 r 의 기본주소(지번·단지명)에 선택한 동/호를 붙인 재조회 주소를 만든다."""
        addr = (r or {}).get("base_address", "")
        if dong:
            addr += f" {dong}동"
        if ho:
            addr += f" {ho}호"
        return addr.strip()

    def _work(self, addrs, sel):
        results = []
        for idx, addr in addrs:
            try:
                res = address_router.lookup(addr, sel)
            except Exception as e:
                res = {"ok": False, "message": f"오류가 발생했습니다: {e}"}
            results.append((idx, addr, res))
        self.after(0, self._render_all, results)

    # ── 소유지분 다이얼로그 (주소별) ─────────────────────────────
    def open_share_dialog(self, row_index):
        cur = self._shares.get(row_index)
        win = ctk.CTkToplevel(self)
        win.title("소유지분")
        win.geometry("340x180")
        win.resizable(False, False)
        win.configure(fg_color=BG)
        win.transient(self)
        self._apply_icon(win)          # 왼쪽 상단바 아이콘을 메인과 동일하게
        win.after(60, lambda: win.grab_set() if win.winfo_exists() else None)

        frm = ctk.CTkFrame(win, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=22, pady=18)

        # 어느 주소에 적용되는지 표시
        addr = ""
        for idx, a, _ in (self._last_results or []):
            if idx == row_index:
                addr = a
                break
        ctk.CTkLabel(frm, text=addr, font=self.f_sub, text_color=SUB, anchor="w",
                     justify="left", wraplength=296).pack(fill="x", pady=(0, 10))

        irow = ctk.CTkFrame(frm, fg_color="transparent")
        irow.pack(pady=(0, 14))
        den = ctk.StringVar(value=str(int(cur["denominator"])) if cur else "")
        num = ctk.StringVar(value=f"{cur['numerator']:g}" if cur else "")
        de = ctk.CTkEntry(irow, textvariable=den, width=96, height=40, corner_radius=10,
                          justify="center", fg_color=FIELD, border_width=0, font=self.f_field)
        de.pack(side="left")
        ctk.CTkLabel(irow, text="분의", font=self.f_key, text_color=TEXT).pack(side="left", padx=12)
        ne = ctk.CTkEntry(irow, textvariable=num, width=96, height=40, corner_radius=10,
                          justify="center", fg_color=FIELD, border_width=0, font=self.f_field)
        ne.pack(side="left")

        brow = ctk.CTkFrame(frm, fg_color="transparent")
        brow.pack(fill="x", pady=(4, 0))

        def apply_():
            share = share_util.share_from_parts(den.get(), num.get())
            if share:
                self._shares[row_index] = share
            else:
                self._shares.pop(row_index, None)
            win.destroy()
            self._render_all(self._last_results or [])

        def clear_():
            self._shares.pop(row_index, None)
            win.destroy()
            self._render_all(self._last_results or [])

        ctk.CTkButton(brow, text="적용", height=38, corner_radius=10, font=self.f_btn,
                      fg_color=ACCENT, hover_color=ACCENT_H, text_color=ON_ACCENT,
                      command=apply_).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(brow, text="지분 해제", height=38, corner_radius=10, font=self.f_key,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=TEXT, hover_color=CARD, command=clear_
                      ).pack(side="left", expand=True, fill="x", padx=(5, 0))
        win.bind("<Return>", lambda e: apply_())
        win.bind("<Escape>", lambda e: win.destroy())
        de.focus()

    # ── 환산가격 한눈에 보기 ─────────────────────────────
    @staticmethod
    def _summary_lines(r, share):
        """결과 r 에서 (항목, 환산최종액, 계산식) 목록을 뽑는다. share 있으면 반영."""
        ratio = share["ratio"] if share else 1
        subf = f" × 소유지분({bunui(share)})" if share else ""
        out = []
        sec = r.get("sections", {})
        land = sec.get("land") or {}
        if land.get("jiga") and land.get("area"):
            base = land["jiga"] * land["area"]
            out.append(("토지 공시가격", base * MULT * ratio, f"{won(base)} × 1.3{subf}"))
        house = sec.get("house") or {}
        if house.get("price") is not None:
            base = house["price"]
            out.append(("주택가격", base * MULT * ratio, f"{won(base)} × 1.3{subf}"))
        apt = sec.get("apt") or {}
        for row in (apt.get("rows") or []):
            if row.get("price") is not None:
                base = row["price"]
                dong = row.get("dong")
                # 데이터의 동이 '108동'처럼 이미 '동'을 포함할 수 있어 중복 방지
                dd = dong if (dong and dong.endswith("동")) else (f"{dong}동" if dong else "")
                dh = (f"{dd} " if dong else "") + f"{row.get('ho')}호"
                out.append((f"공동주택 {dh}", base * MULT * ratio, f"{won(base)} × 1.3{subf}"))
        return out

    def open_summary(self):
        """모든 조회 주소의 환산가격(계산과정·소유지분 반영)을 한 창에 모아 보여준다."""
        results = self._last_results or []
        win = ctk.CTkToplevel(self)
        win.title("환산가격 한눈에 보기")
        win.geometry("500x640")
        win.minsize(380, 400)
        win.configure(fg_color=BG)
        win.transient(self)
        self._apply_icon(win)

        ctk.CTkLabel(win, text="환산가격 한눈에 보기", font=self.f_h1,
                     text_color=TEXT).pack(anchor="w", padx=22, pady=(20, 0))
        ctk.CTkLabel(win, text="공시가격 × 1.3 (소유지분 입력 시 반영) · 금액을 누르면 복사",
                     font=self.f_sub, text_color=SUB).pack(anchor="w", padx=22, pady=(2, 10))

        box = ctk.CTkScrollableFrame(win, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        if not results:
            ctk.CTkLabel(box, text="먼저 주소를 조회하세요.",
                         font=self.f_key, text_color=SUB).pack(pady=50)
            return

        for idx, addr, r in results:
            card = ctk.CTkFrame(box, corner_radius=14, fg_color=CARD,
                                border_width=1, border_color=LINE)
            card.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(card, text="📍 " + addr, font=self.f_info_b, text_color=TEXT,
                         anchor="w", justify="left", wraplength=420).pack(
                fill="x", padx=16, pady=(12, 6))

            lines = self._summary_lines(r, self._shares.get(idx)) if r.get("ok") else []
            if not lines:
                if not r.get("ok"):
                    msg = r.get("message") or "조회 실패"
                elif r.get("no_data"):
                    msg = "공시가격 미조회 (신설·개편 행정구역 등)"
                else:
                    msg = r.get("message") or "환산할 가격이 없습니다."
                ctk.CTkLabel(card, text=msg.split("\n")[0], font=self.f_sub,
                             text_color=SUB, anchor="w", justify="left",
                             wraplength=420).pack(fill="x", padx=16, pady=(0, 12))
                continue

            for label, final, formula in lines:
                blk = ctk.CTkFrame(card, fg_color="transparent")
                blk.pack(fill="x", padx=16, pady=(0, 10))
                top = ctk.CTkFrame(blk, fg_color="transparent")
                top.pack(fill="x")
                ctk.CTkLabel(top, text=label, font=self.f_info,
                             text_color=SUB, anchor="w").pack(side="left")
                cp = won_copy(final)
                ctk.CTkButton(top, text=won(final), font=self.f_info_b, text_color=TEXT,
                              fg_color="transparent", hover_color=("#ECECEF", "#2A2A2C"),
                              corner_radius=8, height=30, cursor="hand2",
                              command=lambda c=cp: self._copy(c)).pack(side="right")
                ctk.CTkLabel(blk, text=formula, font=self.f_sub, text_color=SUB,
                             anchor="w", justify="left", wraplength=420).pack(fill="x")

    # ── 결과 위젯 헬퍼 ─────────────────────────────
    def _clear_results(self):
        for w in self.results.winfo_children():
            w.destroy()

    def _card(self, title):
        card = ctk.CTkFrame(self.results, corner_radius=16, fg_color=CARD,
                            border_width=1, border_color=LINE)
        card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(card, text=title, font=self.f_title, text_color=TEXT,
                     anchor="w").pack(fill="x", padx=20, pady=(16, 8))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=20, pady=(0, 18))
        return body

    def _row(self, body, key, value, value_color=TEXT):
        """정보 행: 라벨·값 모두 동일 크기(f_info 14)로 통일. 값만 볼드로 구분."""
        r = ctk.CTkFrame(body, fg_color="transparent")
        r.pack(fill="x", pady=4)
        ctk.CTkLabel(r, text=key, font=self.f_info, text_color=SUB,
                     anchor="w").pack(side="left")
        ctk.CTkLabel(r, text=value, font=self.f_info_b,
                     text_color=value_color, anchor="e", justify="right").pack(side="right")

    def _divider(self, body):
        ctk.CTkFrame(body, height=1, fg_color=LINE).pack(fill="x", pady=(8, 6))

    def _copy(self, text):
        """클립보드로 복사 + 상태줄에 잠깐 피드백."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            return
        prev = self.status.cget("text")
        self.status.configure(text=f"✓ 복사됨: {text}")
        self.after(1600, lambda: self.status.winfo_exists()
                   and self.status.configure(text=prev))

    def _result_band(self, body, label, value, sub=None):
        """결과값을 크게 강조(배경 없이 큰 검은 숫자 + 계산식).
        결과값 글자를 클릭하면 클립보드로 복사된다."""
        inner = ctk.CTkFrame(body, fg_color="transparent")
        inner.pack(fill="x", pady=(4, 2))
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=label, font=self.f_band_l,
                     text_color=TEXT, anchor="w").pack(side="left")
        # 값 = 클릭하면 복사되는 버튼(표시는 소수점 4자리, 복사는 소수점 버림)
        disp = won(value)
        cp = won_copy(value)
        ctk.CTkButton(top, text=disp, font=self.f_band, text_color=TEXT,
                      fg_color="transparent", hover_color=("#ECECEF", "#2A2A2C"),
                      corner_radius=8, height=34, cursor="hand2",
                      command=lambda: self._copy(cp)).pack(side="right")
        if sub:
            ctk.CTkLabel(inner, text=sub, font=self.f_sub, text_color=SUB,
                         anchor="w", justify="left", wraplength=430).pack(fill="x", pady=(2, 0))

    def _note(self, body, text, color=SUB):
        ctk.CTkLabel(body, text=text, font=self.f_sub, text_color=color, anchor="w",
                     justify="left", wraplength=440).pack(fill="x", pady=2)

    def _area_row(self, body, key, value):
        txt = area(value)
        if self._cur_share and isinstance(value, (int, float)):
            txt += f"   ·   지분 {area(value * self._cur_share['ratio'])}"
        self._row(body, key, txt)

    def _money(self, body, label, value, name=None):
        name = name or label
        # 공시가격 원금 — 나머지 정보와 동일 크기로 통일(최종 ×1.3 값만 크게 강조)
        self._row(body, label, won(value))
        if not isinstance(value, (int, float)):
            return
        self._divider(body)
        if self._cur_share:
            # 소유지분 반영 최종값만 표시 (1.3은 한 번만: 공시가격 × 1.3 × 지분)
            final = value * MULT * self._cur_share["ratio"]
            self._result_band(body, "× 1.3 × 소유지분", final,
                              sub=f"{name} × {MULT:g} × 소유지분 ({bunui(self._cur_share)})")
        else:
            # 지분 미입력 시 × 1.3 환산 표시
            self._result_band(body, f"× {MULT:g} 환산", value * MULT,
                              sub=f"{name} × {MULT:g}")

    # ── 렌더 ─────────────────────────────
    def _render_all(self, results):
        """여러 주소의 조회 결과를 주소별 블록으로 쌓아 표시한다."""
        self.btn.configure(state="normal")
        self._last_results = results
        self._clear_results()
        if not results:
            self._empty_state("주소를 입력하면 여기에 결과가 표시됩니다.")
            return

        n_share = sum(1 for i in self._shares if any(idx == i for idx, _, _ in results))
        base = f"조회 완료 ({len(results)}건)"
        self.status.configure(
            text=base + (f" · 소유지분 {n_share}건 적용" if n_share else ""))

        for k, (idx, addr, res) in enumerate(results):
            if k > 0:
                ctk.CTkFrame(self.results, height=2, fg_color=LINE).pack(
                    fill="x", pady=(4, 14))
            self._render_one(res, idx, addr)

    def _render_one(self, r, row_index, input_addr=""):
        """결과 하나를 렌더(주소 헤더 + 섹션). row_index: 재조회/지분이 적용될 입력행."""
        # 이 블록에 적용할 소유지분(주소별 개별)
        self._cur_share = self._shares.get(row_index)

        # 주소 헤더 (실패 포함 항상 표시). 값이 있으면 우측에 이 주소용 소유지분 버튼.
        if r.get("ok"):
            addr = r.get("base_address") or r.get("input") or input_addr or ""
            if r.get("apt_dong"):
                addr += f" {r['apt_dong']}동"
            if r.get("apt_ho"):
                addr += f" {r['apt_ho']}호"
        else:
            addr = input_addr or r.get("input") or ""

        sec = r.get("sections", {})
        has_value = bool(r.get("ok") and sec and not r.get("no_data"))
        if addr:
            hdr = ctk.CTkFrame(self.results, fg_color="transparent")
            hdr.pack(fill="x", padx=4, pady=(0, 10))
            ctk.CTkLabel(hdr, text="📍 " + addr, font=self.f_info_b, text_color=TEXT,
                         anchor="w", justify="left", wraplength=360).pack(
                side="left", fill="x", expand=True)
            if has_value:
                on = self._cur_share is not None
                ctk.CTkButton(
                    hdr, text=("지분 적용중" if on else "소유지분"),
                    width=86, height=32, corner_radius=10, font=self.f_key,
                    fg_color=(ACCENT if on else "transparent"),
                    border_width=(0 if on else 1), border_color=BORDER,
                    text_color=(ON_ACCENT if on else TEXT),
                    hover_color=(ACCENT_H if on else CARD),
                    command=lambda ri=row_index: self.open_share_dialog(ri),
                ).pack(side="right", padx=(8, 0))

        if not r.get("ok"):
            self._note(self._card("조회 실패"),
                       r.get("message") or "알 수 없는 오류", color=TEXT)
            return

        if not sec:
            self._note(self._card("결과 없음"),
                       r.get("message") or "조회 결과가 없습니다.")
            return

        if r.get("no_data"):
            self._note(self._card("조회하지 못했습니다"),
                       r.get("message") or "공시가격 데이터를 가져오지 못했습니다.", color=TEXT)
            return

        if "land" in sec:
            self._render_land(sec["land"])
        if "house" in sec:
            self._render_house(sec["house"])
        if "apt" in sec:
            self._render_apt(sec["apt"], row_index, r)

    def _render_land(self, d):
        body = self._card("토지 · 개별공시지가")
        self._row(body, "지목", d.get("jimok") or "-")
        self._area_row(body, "면적", d.get("area"))
        self._row(body, f"개별공시지가 {d.get('jiga_yeondo') or '-'}",
                  f"{d['jiga']:,} 원/㎡" if d.get("jiga") else "-")
        if d.get("jiga") and d.get("area"):
            self._money(body, "토지 공시가격", d["jiga"] * d["area"],
                        name="토지공시가격")

    def _render_house(self, d):
        body = self._card("개별단독주택가격")
        if d.get("price") is not None:
            self._money(body, f"주택가격 {d.get('price_yeondo') or '-'}", d.get("price"),
                        name="주택가격")
            self._area_row(body, "대지면적", d.get("lot_area"))
            self._row(body, "건물연면적", area(d.get("bld_area")))
        else:
            self._note(body, "해당 없음 (단독주택이 아닌 필지 · 나대지/상업건물/공동주택 등)")

    def _render_apt(self, sec, row_index=0, r=None):
        r = r or {}
        rows = sec.get("rows") or []
        if sec.get("not_apt"):
            self._note(self._card("공동주택가격"), sec.get("message"))
            return

        # 여러 필지(외 N필지)라 입력 지번으로는 알 수 없는 경우 — 예상 지번 후보를 눌러 재조회
        cands = sec.get("apt_candidates")
        if cands:
            body = self._card("공동주택가격 · 지번 선택")
            self._note(body, sec.get("message")
                       or "데이터가 있는 다른 지번을 선택해 조회하세요.")
            for c in cands:
                ctk.CTkButton(
                    body, text=f"{c['jibun']}   ·   {c['name']}",
                    height=40, corner_radius=10, font=self.f_info_b, anchor="w",
                    fg_color="transparent", border_width=1, border_color=BORDER,
                    text_color=TEXT, hover_color=CARD,
                    command=lambda jb=c["jibun"]: self._apply_row(
                        row_index, self._parcel_addr(r, jb)),
                ).pack(fill="x", pady=4)
            return

        # 단지는 맞는데 동/호를 못 짚은 경우 — 실제 동 또는 호 목록을 눌러 수동 선택 → 재조회
        pick = sec.get("apt_pick")
        if pick:
            level = pick.get("level")
            title = "공동주택가격 · " + ("동 선택" if level == "dong" else "호 선택")
            body = self._card(title)
            if pick.get("danji"):
                self._row(body, "단지명", pick["danji"])
            self._note(body, sec.get("message")
                       or ("동을 선택하세요." if level == "dong" else "호를 선택하세요."))
            cur_dong = pick.get("dong")
            entered_ho = r.get("apt_ho")
            grid = ctk.CTkFrame(body, fg_color="transparent")
            grid.pack(fill="x", pady=(6, 0))
            cols = 4
            for i, opt in enumerate(pick.get("options") or []):
                if level == "dong":
                    label = f"{opt}동"
                    cmd = (lambda d=opt: self._apply_row(
                        row_index, self._pick_addr(r, dong=d, ho=entered_ho)))
                else:
                    label = f"{opt}호"
                    cmd = (lambda hh=opt: self._apply_row(
                        row_index, self._pick_addr(r, dong=cur_dong, ho=hh)))
                btn = ctk.CTkButton(grid, text=label, height=34, corner_radius=10,
                                    font=self.f_info, fg_color="transparent", border_width=1,
                                    border_color=BORDER, text_color=TEXT, hover_color=CARD, command=cmd)
                btn.grid(row=i // cols, column=i % cols, padx=3, pady=3, sticky="ew")
            for c in range(cols):
                grid.grid_columnconfigure(c, weight=1)
            return

        if not rows:
            self._note(self._card("공동주택가격"),
                       sec.get("message") or "해당 세대를 찾지 못했습니다.", color=TEXT)
            return

        for row in rows:
            body = self._card(f"공동주택가격 · {row.get('danji_name') or ''}".strip(" ·"))
            dong = row.get("dong")
            # 데이터의 동이 '108동'처럼 이미 '동'을 포함할 수도, '3'/'가'처럼 없을 수도 있다.
            dong_disp = dong if (dong and dong.endswith("동")) else (f"{dong}동" if dong else "")
            unit = f"{dong_disp} {row.get('ho')}호" if dong else f"{row.get('ho')}호"
            if row.get("floor"):
                unit += f"  ({row.get('floor')}층)"
            self._row(body, "동/호" if dong else "호", unit)
            self._area_row(body, "전용면적", row.get("prvuse_area"))
            self._money(body, f"공동주택가격 {row.get('price_yeondo') or '-'}",
                        row.get("price"), name="공동주택가격")


if __name__ == "__main__":
    App().mainloop()
