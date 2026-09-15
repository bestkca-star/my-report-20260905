# -*- coding: utf-8 -*-
"""제안서에 들어갈 그림 (인라인 SVG).

**화면은 Plotly, 인쇄는 matplotlib, 제안서는 SVG 문자열.**
제안서는 파일 하나로 끝나야 한다 — 메일에 붙이든 USB 로 옮기든 같은 문서여야 하므로
외부 CDN·이미지 파일·폰트 링크를 쓰지 않는다. 그래서 PNG 가 아니라 SVG 문자열이다.
돌려주는 것을 HTML 에 그대로 박으면 된다.

────────────────────────────────────────────────────────────────────
색은 셋뿐이다.

    강조  config.COLORS["block"]   문제인 칸 하나 (병목 · 최저)
    기본  config.BRAND["primary"]  그 밖의 값
    회색  config.COLORS["none"]    비교 대상이 아닌 칸

  ★ 기본색을 COLORS 에서 안 가져온 이유: COLORS 는 **상태 색**이고
    의미가 고정돼 있다(config 주석). 평범한 막대를 "ok"(초록)로 칠하면
    그 칸이 정상이라고 주장하는 것이 된다. primary 는 상태가 아니고,
    제안서 템플릿이 이미 막대 기본색으로 쓰던 값이다.

  ★ 색은 **혼자 뜻을 지지 않는다.** 강조한 막대에는 "병목"·"최저" 같은
    글자 딱지를 함께 붙인다. 흑백 인쇄와 색각 이상에서 색만 남으면 못 읽는다.
────────────────────────────────────────────────────────────────────

지키는 것 셋.

    1. 길이와 좌표는 **실제 값에서** 계산한다. 예시 숫자를 남기지 않는다.
    2. **값이 없는 계열은 그리지 않는다.** 0 으로 그리면 "0 이다"가 된다.
       못 믿을 값도 그리지 않는다 — 사람은 본 숫자를 기억한다.
    3. 눈금과 값 라벨을 넣는다. 라벨 없는 막대는 못 읽는다.

그릴 것이 없으면 **None** 을 돌려준다. 왜 없는지는 topic_evidence() 가 준
같은 칸의 "사유" 에 이미 있다 — 여기서 사유를 다시 만들지 않는다.
"""
from __future__ import annotations

import math

import pandas as pd

from core import config as C

# ── 색 셋 ─────────────────────────────────────────────────────────
강조 = C.COLORS["block"]
기본 = C.BRAND["primary"]
회색 = C.COLORS["none"]

먹 = C.BRAND["ink"]
연먹 = C.BRAND["muted"]
선 = C.BRAND["line"]

FONT = ("-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif")


def _esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _num(v) -> float | None:
    """그릴 수 있는 수인가. None·NaN 은 **값이 없는 것**이다."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _ticks(hi: float, n: int = 4) -> list[float]:
    """0 부터 hi 까지 읽기 좋은 눈금. hi 는 실제 최대값에서 온다."""
    if hi <= 0:
        return [0.0]
    거친 = hi / n
    자릿 = 10 ** math.floor(math.log10(거친))
    간격 = next((s * 자릿 for s in (1, 2, 2.5, 5, 10) if s * 자릿 >= 거친), 10 * 자릿)
    끝 = math.ceil(hi / 간격) * 간격
    return [i * 간격 for i in range(int(round(끝 / 간격)) + 1)]


def _grain(그레인: str | None) -> str:
    """caption 에 들어갈 그레인 한 줄. **무엇을 하나로 셌는지 반드시 적는다.**"""
    return 그레인 or (f"{C.EVENT_ID_COL} 하나를 한 건으로 센다 — "
                      f"행이 아니라 고유값으로 세며, 한 사람이 여러 건일 수 있다")


def _wrap(내용: str, w: int, h: int, 제목: str, 설명: str, caption: str) -> str:
    """그림 하나. <figure> 로 감싸고 caption 을 아래에 붙인다."""
    return (
        f'<figure style="margin:18px 0">'
        f'<svg role="img" width="100%" viewBox="0 0 {w} {h}" '
        f'aria-label="{_esc(제목)}" style="font-family:{FONT};display:block">'
        f"<title>{_esc(제목)}</title><desc>{_esc(설명)}</desc>{내용}</svg>"
        f'<figcaption style="font-size:11.5px;color:{연먹};margin-top:7px;'
        f'line-height:1.6">{_esc(caption)}</figcaption></figure>')


def _axis_x(x0: int, x1: int, y: int, ticks: list[float], 최대: float,
            단위: str) -> str:
    """가로 눈금자. 눈금선은 뒤로 물러나 있어야 막대가 읽힌다."""
    쪽 = []
    for t in ticks:
        gx = x0 + (x1 - x0) * (t / 최대 if 최대 else 0)
        쪽.append(f'<line x1="{gx:.1f}" y1="28" x2="{gx:.1f}" y2="{y}" '
                  f'stroke="{선}" stroke-width="1"/>')
        라벨 = f"{t:,.0f}" if 단위 != "%" else f"{t:g}"
        쪽.append(f'<text x="{gx:.1f}" y="{y + 15}" fill="{연먹}" font-size="11" '
                  f'text-anchor="middle">{라벨}{_esc(단위)}</text>')
    return "".join(쪽)


def _bar(x: int, y: int, w: float, h: int, color: str, 툴팁: str) -> str:
    """막대 하나. 끝을 4px 둥글게 — 축에 붙은 쪽은 각지게 둔다."""
    w = max(float(w), 0.0)
    r = min(4.0, w)
    if w <= r:
        d = f"M{x} {y}h{w:.1f}v{h}h-{w:.1f}z"
    else:
        d = (f"M{x} {y}h{w - r:.1f}a{r} {r} 0 0 1 {r} {r}"
             f"v{h - 2 * r}a{r} {r} 0 0 1 -{r} {r}h-{w - r:.1f}z")
    return f'<path d="{d}" fill="{color}"><title>{_esc(툴팁)}</title></path>'


# ── 1) 현황 — 단계별 도달 ─────────────────────────────────────────
def funnel_svg(현황, 그레인: str | None = None) -> str | None:
    """단계별 도달 막대. **병목 구간 하나만 강조색, 나머지는 기본색.**

    현황: topic_evidence()["현황"] 또는 그 "표" DataFrame.
          열 — 단계 · 도달 · 단계 전환율 · 병목 (· 이 주제)

    그릴 것이 없으면 None.
    """
    표 = 현황.get("표") if isinstance(현황, dict) else 현황
    if 표 is None or len(표) == 0:
        return None
    행 = [r for _, r in 표.iterrows() if _num(r.get("도달")) is not None]
    if not 행:
        return None

    최대 = max(_num(r["도달"]) for r in 행)
    ticks = _ticks(최대)
    끝눈금 = ticks[-1] or 최대
    라벨폭, 값폭, W = 118, 96, 640
    x0, x1 = 라벨폭, W - 값폭
    바h, 간격, 위 = 26, 12, 34
    본문h = len(행) * (바h + 간격)
    축y = 위 + 본문h
    H = 축y + 26

    쪽 = [_axis_x(x0, x1, 축y, ticks, 끝눈금, "건")]
    for i, r in enumerate(행):
        v = _num(r["도달"])
        y = 위 + i * (바h + 간격)
        병목 = bool(r.get("병목"))
        색 = 강조 if 병목 else 기본
        w = (x1 - x0) * (v / 끝눈금)
        율 = _num(r.get("단계 전환율"))
        딱지 = " · 병목" if 병목 else ""
        쪽.append(f'<text x="{x0 - 10}" y="{y + 18}" fill="{먹}" font-size="12.5" '
                  f'text-anchor="end">{_esc(r["단계"])}</text>')
        쪽.append(_bar(x0, y, w, 바h, 색,
                       f'{r["단계"]} {v:,.0f}건'
                       + (f" · 직전 단계의 {율:.2f}%" if 율 is not None else "")))
        # 값 라벨은 **글자색**을 쓴다. 막대 색을 글자에 쓰면 색이 뜻을 둘로 진다.
        쪽.append(f'<text x="{x0 + w + 8:.1f}" y="{y + 18}" fill="{먹}" '
                  f'font-size="12" font-weight="700">{v:,.0f}건</text>')
        if 율 is not None:
            쪽.append(f'<text x="{x0 + w + 8:.1f}" y="{y + 18}" fill="{연먹}" '
                      f'font-size="11" dx="{len(f"{v:,.0f}건") * 7.4:.0f}">'
                      f"{율:.2f}%{딱지}</text>")
        elif 병목:
            쪽.append(f'<text x="{x0 + w + 8:.1f}" y="{y + 18}" fill="{연먹}" '
                      f'font-size="11" dx="{len(f"{v:,.0f}건") * 7.4:.0f}">병목</text>')

    병목단계 = next((r["단계"] for r in 행 if r.get("병목")), None)
    cap = (f"막대 길이는 각 단계에 **도달한 건수**에 비례한다"
           + (f". 강조한 칸이 병목({병목단계})이다" if 병목단계 else "")
           + f". {_grain(그레인)}.")
    return _wrap("".join(쪽), W, H, "단계별 도달 건수",
                 f"{len(행)}개 단계의 도달 건수 막대. 병목 단계만 색으로 강조.",
                 cap.replace("**", ""))


# ── 2) 원인 — 축별 전환율 ─────────────────────────────────────────
def gap_svg(원인, 그레인: str | None = None) -> str | None:
    """축별 전환율 가로 막대. **최고·최저만 색, 나머지는 회색.**

    원인: topic_evidence()["원인"] (표 · 축 · 구간 · 비중_분모 · 감춘_칸).

    **감춘 칸은 막대를 안 그린다.** 전환율이 없는 칸이라 0 으로 그리면
    "전환율 0%"가 된다. 대신 몇 칸을 감췄는지 caption 에 적는다.
    """
    if not isinstance(원인, dict) or 원인.get("표") is None:
        return None
    표, 축 = 원인["표"], 원인.get("축")
    if 축 is None or 축 not in 표.columns:
        return None
    행 = [r for _, r in 표.iterrows() if _num(r.get("전환율")) is not None]
    if not 행:
        return None

    최대 = max(_num(r["전환율"]) for r in 행)
    ticks = _ticks(최대)
    끝눈금 = ticks[-1] or 최대
    라벨폭, 값폭, W = 118, 150, 640
    x0, x1 = 라벨폭, W - 값폭
    바h, 간격, 위 = 24, 11, 34
    축y = 위 + len(행) * (바h + 간격)
    H = 축y + 26

    쪽 = [_axis_x(x0, x1, 축y, ticks, 끝눈금, "%")]
    for i, r in enumerate(행):
        v = _num(r["전환율"])
        표시 = str(r.get("표시") or "")
        색 = 강조 if 표시 == "최저" else 기본 if 표시 == "최고" else 회색
        y = 위 + i * (바h + 간격)
        w = (x1 - x0) * (v / 끝눈금)
        도달 = _num(r.get("도달"))
        전환 = _num(r.get("전환"))
        분자 = (f'{전환:,.0f}/{도달:,.0f}' if None not in (전환, 도달) else "")
        쪽.append(f'<text x="{x0 - 10}" y="{y + 17}" fill="{먹}" font-size="12.5" '
                  f'text-anchor="end">{_esc(r[축])}</text>')
        쪽.append(_bar(x0, y, w, 바h, 색,
                       f'{r[축]} {v:.2f}%' + (f" ({분자})" if 분자 else "")))
        꼬리 = f"  {표시}" if 표시 in ("최고", "최저") else ""
        쪽.append(f'<text x="{x0 + w + 8:.1f}" y="{y + 17}" fill="{먹}" '
                  f'font-size="12" font-weight="700">{v:.2f}%'
                  f'<tspan fill="{연먹}" font-weight="400" font-size="11">'
                  f"{_esc((' (' + 분자 + ')') if 분자 else '')}{_esc(꼬리)}"
                  f"</tspan></text>")

    감춤 = int(원인.get("감춘_칸") or 0)
    분모 = 원인.get("비중_분모")
    cap = (f"{축} 별 전환율 — 구간 {원인.get('구간', '')}. "
           f"막대 길이는 전환율에 비례하고, 괄호 안은 분자/분모다"
           + (f". 분모 합계 {분모:,}건" if 분모 else "")
           + (f". 표본이 모자라 계산하지 않은 {감춤}칸은 **막대를 그리지 않았다** — "
              f"0 이라는 뜻이 아니라 값이 없다는 뜻이다" if 감춤 else "")
           + f". {_grain(그레인)}.")
    return _wrap("".join(쪽), W, H, f"{축}별 전환율",
                 f"{len(행)}개 칸의 전환율 막대. 최고·최저만 색으로 강조.",
                 cap.replace("**", ""))


# ── 3) 추세 — 최근 구간 ───────────────────────────────────────────
def trend_svg(추세, 지표: str | None = None, 그레인: str | None = None):
    """최근 구간 꺾은선. **임계선이 있으면 점선으로.**

    추세: topic_evidence()["추세"] (표 — 분기 · 값 · 분모 · 믿을만 · 사유).

    **못 믿을 점은 그리지 않는다.** 표본이 모자라 못 믿는 값을 회색으로라도
    찍으면 사람은 그 숫자를 기억한다. 남는 점이 두 개 미만이면 None 이다 —
    선은 두 점이 있어야 그어진다.

    단위는 **분기**다. monthly() 가 분기로 자르고 그 근거가 config 에 있다.
    """
    if not isinstance(추세, dict) or 추세.get("표") is None:
        return None
    표 = 추세["표"]
    쓸 = [r for _, r in 표.iterrows()
          if _num(r.get("값")) is not None and bool(r.get("믿을만"))]
    버린 = len(표) - len(쓸)
    if len(쓸) < 2:
        return None

    th = C.THRESHOLDS.get(지표 or "", {}) or {}
    임계 = [(k, float(v)) for k, v in th.items() if _num(v) is not None]
    값들 = [_num(r["값"]) for r in 쓸] + [v for _, v in 임계]
    lo, hi = min(값들), max(값들)
    여백 = max((hi - lo) * 0.18, 1.0)
    lo, hi = max(lo - 여백, 0.0), hi + 여백

    W, H = 640, 260
    x0, x1, y0, y1 = 58, W - 118, 28, H - 42
    sx = lambda i: x0 + (x1 - x0) * (i / (len(쓸) - 1))
    sy = lambda v: y1 - (y1 - y0) * ((v - lo) / (hi - lo) if hi > lo else 0.5)

    쪽 = []
    for t in _ticks(hi)[:-1] + [hi]:
        if t < lo:
            continue
        gy = sy(t)
        쪽.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" '
                  f'stroke="{선}" stroke-width="1"/>')
        쪽.append(f'<text x="{x0 - 8}" y="{gy + 4:.1f}" fill="{연먹}" '
                  f'font-size="11" text-anchor="end">{t:g}%</text>')
    for 이름, v in 임계:
        if not lo <= v <= hi:
            continue
        gy = sy(v)
        쪽.append(f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" '
                  f'stroke="{강조}" stroke-width="1.5" stroke-dasharray="5 4"/>')
        쪽.append(f'<text x="{x1 + 8}" y="{gy + 4:.1f}" fill="{강조}" '
                  f'font-size="11">{_esc(이름)} {v:g}%</text>')

    점 = [(sx(i), sy(_num(r["값"]))) for i, r in enumerate(쓸)]
    쪽.append('<polyline points="'
              + " ".join(f"{x:.1f},{y:.1f}" for x, y in 점)
              + f'" fill="none" stroke="{기본}" stroke-width="2" '
                'stroke-linejoin="round"/>')
    for (x, y), r in zip(점, 쓸):
        v, n = _num(r["값"]), _num(r.get("분모"))
        쪽.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{기본}" '
                  f'stroke="#ffffff" stroke-width="2"><title>'
                  f'{_esc(r["분기"])} {v:.2f}%'
                  + (f" (분모 {n:,.0f}건)" if n else "") + "</title></circle>")
        쪽.append(f'<text x="{x:.1f}" y="{y - 12:.1f}" fill="{먹}" font-size="11.5" '
                  f'font-weight="700" text-anchor="middle">{v:.2f}%</text>')
        쪽.append(f'<text x="{x:.1f}" y="{y1 + 18:.1f}" fill="{연먹}" '
                  f'font-size="11" text-anchor="middle">{_esc(r["분기"])}</text>')

    이름 = 지표 or "지표"
    cap = (f"{이름} 의 최근 {len(쓸)}{추세.get('단위') or '구간'} 값"
           + (f". 점선은 임계선({' · '.join(k for k, _ in 임계)})이다" if 임계 else
              ". 임계값이 정해지지 않아 기준선이 없다")
           + (f". 표본이 모자란 {버린}개 구간은 **그리지 않았다**" if 버린 else "")
           + f". {_grain(그레인)}.")
    return _wrap("".join(쪽), W, H, f"{이름} 추세",
                 f"{len(쓸)}개 구간의 {이름} 꺾은선"
                 + (f". 임계선 {len(임계)}개를 점선으로 표시." if 임계 else "."),
                 cap.replace("**", ""))
