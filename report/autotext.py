# -*- coding: utf-8 -*-
"""자동으로 쓰는 장의 본문 조립과, 사람이 쓰는 장의 작성 가이드.

sections.py 의 _s1~_s7 이 여기를 부른다. 조립 로직이 길어 파일을 나눴다.

────────────────────────────────────────────────────────────────────
여기서 지키는 것 셋.

    1. 값은 metrics 가 계산한 것만 쓴다. 여기서 다시 계산하지 않는다.
    2. 못 믿을 조건에 걸린 항목은 **사유와 표본 수만** 적는다.
       전환율·증감은 애초에 계산되지 않았고, 문서에도 넣지 않는다.
    3. 인과를 단정하지 않는다. "A가 낮다" 까지만 쓴다.
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pandas as pd

from core import config as C, metrics as M, validate as V

NL = "\n"

# 코드가 모르는 한계. 사람이 적는다 —
# 데이터에 아예 없어서 못 본 것 · 찾아봤는데 신호가 없던 것 · 조직 사정으로 못 한 것.
HUMAN_LIMITS = [
    "검사 항목이 공복혈당·총콜레스테롤·ALT 셋뿐이라, 그 밖의 항목이 심사유의 판정에 "
    "어떻게 쓰였는지는 이 데이터로 볼 수 없다.",
    "재검이 별도 검진 건으로 남지 않고 플래그로만 있어, 재검 이후의 경과는 추적하지 못한다.",
    "검진기관별·연령대별 격차를 확인했으나 신호가 없었다 "
    "(검진기관 유의확률 0.208 · 연령대 0.499). 방문진단군만 유의했다(1.27e-11).",
]

GUIDE_NOTE = ("이 내용은 **가이드라인일 뿐입니다.** 담당자가 최종 작성 후 확정해야 합니다. "
              "아래 문장을 그대로 옮기지 마십시오 — 가이드는 문서에 들어가지 않습니다.")


def _bottleneck(t):
    f = M.funnel(t[C.FUNNEL_TABLE])
    i = int(f.index[f.is_bottleneck][0])
    return f, f.iloc[i], f.iloc[max(i - 1, 0)]


def _split(t, dim=None):
    dim = dim or C.DIMS[0]
    S = C.FUNNEL_STEPS
    g = M.funnel_by(t[C.FUNNEL_TABLE], t[C.TABLES[0]], dim, S[2], S[3])
    return dim, g, g[g.사유.isna()], g[g.사유.notna()]


# ── 자동으로 쓰는 장 ──────────────────────────────────────────────
def summary(t: dict) -> str:
    """1. 요약 — 무슨 값이 나왔는가. 원인은 쓰지 않는다."""
    k, m = M.kpis(t), M.monthly(t)
    f, bn, prev = _bottleneck(t)

    줄 = [f"기간 {C.PERIOD[0]} ~ {C.PERIOD[1]}. 분석 단위는 검진 건 1회이며 "
          f"대상은 {len(t[C.TABLES[0]]):,}건이다."]
    for 이름, v in k.items():
        변화 = ""
        if 이름 in m.columns and len(m) >= 2:
            a, b = m[이름].iloc[-2], m[이름].iloc[-1]
            if not (pd.isna(a) or pd.isna(b)):
                변화 = f" 직전 분기 대비 {b - a:+.2f}%p."
        줄.append(f"{이름}은 {v['fmt'].format(v['value'])}다.{변화}")
    줄.append(f"단계별로는 {prev.label} → {bn.label} 구간이 가장 낮다 — "
              f"{prev.n:,}건 중 {bn.n:,}건이 넘어갔다({bn.step_rate * 100:.2f}%).")
    return NL.join(줄)


def method(t: dict) -> str:
    """3. 방법 — 무엇을 어떻게 셌는가. 그레인을 반드시 밝힌다."""
    return f"""분석 단위(그레인)는 검진 건 1회이며 식별자는 {C.EVENT_ID_COL} 다.
행이 아니라 고유값으로 센다 — 이벤트 표에 완전중복이 있어 행으로 세면 분모가 부푼다.
사람(피검자ID)이 아니라 건으로 세므로, 한 사람이 재검을 받으면 두 건이 된다.

기간은 {C.PERIOD[0]} ~ {C.PERIOD[1]} 이다.

유효 구간은 지표마다 다르다. 퍼널 전환율은 의뢰일 2026-08-16까지만 본다 —
의뢰부터 결과 수신까지 최대 34일이 걸리므로 그보다 최근 건은 아직 갈 시간이 없다.
재작업률은 수신일 2026-06-21까지만 본다 — 재검 관측 창이 90일이다.
심사유의율은 수신 시점에 판정이 확정되므로 자르지 않는다.

판정은 분기 단위로 한다. 월 단위로는 한 칸의 표본이 최소 기준({C.MIN_SAMPLE:,}건)에
못 미쳐 변동이 표본 노이즈와 구분되지 않는다.

못 믿을 조건에 걸린 항목은 지표를 계산하지 않는다. 조건은 셋이다 —
표본 {C.MIN_SAMPLE:,}건 미만, 관측 {C.MIN_DAYS}일 미만, 유효 구간 밖 건의 혼입.
걸리면 사유와 표본 수만 남기고 값은 남기지 않는다.

주지표는 심사유의율이며 양방향이다. 낮아지는 것도 높아지는 것도 신호로 본다.
직전 분기 대비 {C.MOVE_MIN:.0f}%p 이상 움직였을 때만 가드레일을 확인한다."""


def results(t: dict) -> str:
    """4. 결과 — 값을 나열한다. "왜"는 쓰지 않는다(해석은 6장)."""
    dim, g, 믿, 감춤 = _split(t)
    f, _, _ = _bottleneck(t)
    r = M.retention_funnel(t)

    줄 = ["단계별 값"]
    for _, x in f.iterrows():
        sr = "—" if pd.isna(x.step_rate) else f"{x.step_rate * 100:.2f}%"
        줄.append(f"- {x.label} {x.n:,}건 (전 단계 대비 {sr})")

    줄 += ["", f"{dim}별 분해 — {f.label.iloc[2]} → {f.label.iloc[3]}"]
    for _, x in g.sort_values("전환율", na_position="last").iterrows():
        if pd.isna(x.전환율):
            # 못 믿을 조건에 걸린 칸. 사유와 표본만 적는다.
            줄.append(f"- {x[dim]} — 판정 보류 ({x.사유}). "
                      f"이 구간 도달의 {x.비중 * 100:.1f}%")
        else:
            줄.append(f"- {x[dim]} {x.전환율 * 100:.2f}% "
                      f"(도달 {int(x.도달):,}건 · 비중 {x.비중 * 100:.1f}%)")

    줄 += ["", "유지 퍼널"]
    for _, x in r.iterrows():
        sr = "—" if pd.isna(x.step_rate) else f"{x.step_rate * 100:.2f}%"
        줄.append(f"- {x.label} {x.n:,}건 (전 단계 대비 {sr})")
    return NL.join(줄)


def before_after(t: dict) -> str:
    """5. 전후 비교 — 실험이 없는 도메인. 인과 문구를 첫 문단에 둔다."""
    줄 = ["이 분석에는 무작위 배정 실험이 없다. 아래는 인접한 두 분기를 견준 것이다. "
          "무작위 배정이 없었으므로 인과를 주장할 수 없다 — 두 분기는 시간 순서로 "
          "나뉜 것일 뿐이고, 차이의 원인은 이 데이터로 가릴 수 없다.", ""]
    for k in M.judge_pairs(t):
        줄.append(f"{k['앞']} → {k['뒤']} · {k['판정']} "
                  f"(모수 {k['모수'][0]:,}건 → {k['모수'][1]:,}건)")
        if "주지표" in k:
            j = k["주지표"]
            줄.append(f"- {j['이름']} {j['앞']:.2f}% → {j['뒤']:.2f}% "
                      f"({j['변화']:+.2f}%p, 움직임 기준 {j['기준']:.0f}%p)")
            for gr in k["가드레일"]:
                if gr.get("확인불가"):
                    줄.append(f"- 가드레일 {gr['이름']} — 관측 창이 닫히지 않아 "
                              f"확인하지 못했다")
                else:
                    줄.append(f"- 가드레일 {gr['이름']} {gr['앞']:.2f}% → "
                              f"{gr['뒤']:.2f}% ({gr['변화']:+.2f}%p)")
        else:
            # 못 믿을 조건에 걸린 카드. 사유만 적고 수치는 적지 않는다.
            줄.append(f"- {k['사유']} — {k['설명']}")
        줄.append("")
    return NL.join(줄).strip()


def limits(t: dict, extra: list[str] | None = None) -> str:
    """7. 한계 — 세 곳에서 조립한다. 사람이 매번 쓰지 않는다."""
    항목 = []

    # ① 검증 경고 — 난 경고를 한계에 안 옮기면 그 경고는 사라진 것과 같다.
    for r in V.run_checks(t):
        if r["level"] == "warn":
            항목.append(f"[검증 경고] {r['name']}: {r['detail']}")

    # ② 못 한 것 — 표본이 모자라 판정하지 않은 것. 사유와 표본만.
    for d in C.DIMS:
        _, g, _, 감춤 = _split(t, d)
        if len(감춤):
            칸 = " · ".join(f"{r[d]} {int(r.도달):,}건" for _, r in 감춤.iterrows())
            항목.append(f"[못 한 것] {d}로 쪼갠 {len(g)}칸 중 {len(감춤)}칸이 "
                        f"최소 표본({C.MIN_SAMPLE:,}건) 미달로 판정 보류 — {칸}")
    for k in M.judge_pairs(t):
        if k["판정"] == "무효":
            항목.append(f"[못 한 것] {k['앞']} → {k['뒤']} 비교는 {k['사유']}로 "
                        f"판정하지 않음")
        for gr in k.get("가드레일", []):
            if gr.get("확인불가"):
                항목.append(f"[못 한 것] {k['앞']} → {k['뒤']} 의 가드레일 "
                            f"{gr['이름']}은 관측 창이 닫히지 않아 확인하지 못함")

    # ③ 항상 넣는 두 문장
    항목.append("[공통] 관측 데이터이므로 인과를 주장할 수 없다. 무작위 배정이 없어 "
                "다른 요인의 영향을 배제하지 못한다.")
    항목.append(f"[공통] 기간이 {C.PERIOD[0]} ~ {C.PERIOD[1]} 이므로 "
                f"그보다 긴 주기의 변화는 관측되지 않는다.")

    # ④ 코드가 모르는 것 — 사람이 적는다. 화면에서 더한 것이 있으면 그것을 쓴다.
    for x in (extra if extra is not None else HUMAN_LIMITS):
        항목.append(f"[직접 적음] {x}")

    return NL.join(f"{i}. {x}" for i, x in enumerate(항목, 1))


# ── 사람이 쓰는 장의 가이드 ───────────────────────────────────────
# ⚠ 가이드는 **화면에만** 보인다. 문서에는 들어가지 않는다.
#   해석과 제안을 자동화하면 책임의 주체가 사라지므로 **완성 문장을 주지 않는다.**
#   재료와 물어볼 것까지만 준다. 사람이 안 쓰면 문서에는 "(작성되지 않음)"이 찍힌다.
def guide_for(title: str, t: dict) -> dict | None:
    dim, g, 믿, 감춤 = _split(t)
    f, bn, prev = _bottleneck(t)
    hi = 믿.loc[믿.전환율.idxmax()] if len(믿) else None
    lo = 믿.loc[믿.전환율.idxmin()] if len(믿) else None
    warn = [r for r in V.run_checks(t) if r["level"] == "warn"]
    무효 = [x for x in M.judge_pairs(t) if x["판정"] == "무효"]

    if title.startswith("2."):
        return {
            "지금 데이터가 말하는 것": [
                f"기간 {C.PERIOD[0]} ~ {C.PERIOD[1]} · 검진건 {len(t[C.TABLES[0]]):,}건",
                f"가장 많이 빠지는 구간은 {prev.label} → {bn.label} "
                f"({prev.n:,}건 중 {bn.n:,}건, {(1 - bn.step_rate) * 100:.1f}% 이탈)",
                (f"{dim}으로 쪼개면 {hi[dim]}군 {hi.전환율:.1%} · {lo[dim]}군 {lo.전환율:.1%}"
                 if hi is not None else ""),
            ],
            "스스로 물어볼 것": [
                "이 숫자를 보고 **무엇을 결정하려 하는가** — 배차·인력 배분? 기관 선정? 판정 기준?",
                "그 결정의 기한은 언제이고 누가 내리는가",
                "이 분석이 없었다면 무엇을 근거로 정했을 것인가",
            ],
            "쓰지 말 것": ["결과를 미리 적지 않는다. 배경은 **왜 봤는가**까지다"],
        }

    if title.startswith("6."):
        관측 = " · ".join(f"{r[dim]}군 {r.전환율:.1%}(비중 {r.비중:.1%})"
                          for _, r in 믿.sort_values("전환율").iterrows())
        return {
            "지금 데이터가 말하는 것": [
                f"관측된 값 — {관측}",
                (f"가장 높은 칸과 낮은 칸의 격차 {(hi.전환율 - lo.전환율) * 100:.1f}%p"
                 if hi is not None else ""),
                (f"표본이 모자라 판정하지 못한 칸 {len(감춤)}개 — 값이 없다"
                 if len(감춤) else ""),
            ],
            "스스로 물어볼 것": [
                "이 격차가 **업무적으로 큰가** — 몇 %p부터 손을 쓸 만한가",
                "이 데이터로 **가릴 수 없는 것**은 무엇인가 "
                "(이동 거리·출장 일정·인력 배치는 데이터에 없다)",
                "다음에 무엇을 더 보면 갈릴 것인가",
            ],
            "쓰지 말 것": [
                "원인을 단정하지 않는다 — "
                "`4군은 멀어서 낮다`(X) → `4군에서 낮게 관측됐고 원인은 이 데이터로 "
                "가릴 수 없다`(O)",
                "금지어가 걸린다: " + " · ".join(BANNED_PREVIEW),
            ],
        }

    if title.startswith("8."):
        잠재 = int(lo.도달 * (hi.전환율 - lo.전환율)) if hi is not None else 0
        return {
            "지금 데이터가 말하는 것": [
                (f"가장 낮은 칸({lo[dim]}군)은 이 구간 도달의 {lo.비중:.1%}"
                 if lo is not None else ""),
                (f"그 칸이 가장 높은 칸 수준이 되면 산술적으로 +{잠재}건 "
                 f"(도달 {int(lo.도달):,}건 기준). **실행 가능성은 별개다**"
                 if hi is not None else ""),
                f"판정하지 못한 것: 무효 비교 {len(무효)}건 · 검증 경고 {len(warn)}건",
            ],
            "스스로 물어볼 것": [
                "**무엇을 할 것인가** — 누가, 언제까지",
                "**무엇을 하지 않을 것인가** — 이게 빠지면 제안이 아니라 보고다",
                "표본이 모자라 판정 못 한 것은 **언제 다시 볼 것인가**",
            ],
            "쓰지 말 것": [
                "산술 잠재값을 목표로 쓰지 않는다. 실행 가능성은 데이터 밖에 있다",
                "전부 다 하자는 것은 제안이 아니다. 우선순위는 사람이 정한다",
            ],
        }
    return None


BANNED_PREVIEW = ["때문에", "덕분에", "효과로", "원인이다", "유발", "기인"]
