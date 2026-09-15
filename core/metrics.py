# -*- coding: utf-8 -*-
"""지표 계산.

**지표의 정의는 위키가 원본이다.** 이 파일은 위키에 적힌 정의를 코드로 옮긴 것일 뿐,
여기서 정의를 새로 만들지 않는다. 정의가 바뀌면 위키를 먼저 고친다.

────────────────────────────────────────────────────────────────────
★ 이 파일에는 통신사 컬럼명이 박혀 있다.

  billing_amount · is_churned · acquisition_channel · visitor_id ...

config.py 를 다 바꿔도 여기서 깨진다. **깨지는 것이 정상이다.**
컬럼명을 하나씩 내 것으로 맞추는 것이 이식 작업의 절반이다. → DESIGN.md §4-6
────────────────────────────────────────────────────────────────────

계산은 전부 pandas로 한다. 어디서 읽어왔든 입력은 동일한 DataFrame이다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from scipy import stats

from core import config as C
from core.load import to_dt
from core.todo import todo


# ── 퍼널 ──────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def funnel(fe: pd.DataFrame) -> pd.DataFrame:
    """단계별 도달 인원과 전환율.

    ★ Day2 실습 A에서 채웁니다.

    먼저 정할 것은 **그레인**이다.

        한 대상이 같은 단계를 두 번 밟을 수 있는가?
          있다 → 그냥 세면 안 된다. 고유값으로 센다 (nunique)
          없다 → 행을 그대로 세도 된다 (len)

    통신사 데이터에서는 한 사람이 여러 세션에 걸쳐 퍼널을 진행하므로
    세션 단위로 세면 전환율이 실제보다 **낮게** 나온다.

    반환: DataFrame[step, label, n, step_rate, cum_rate, drop, is_bottleneck]

        step           config.FUNNEL_STEPS 의 값
        label          config.FUNNEL_LABELS 의 값 (화면 표시용)
        n              그 단계에 도달한 수
        step_rate      전 단계 대비 비율 (첫 단계는 NaN)
        cum_rate       첫 단계 대비 비율
        drop           전 단계에서 빠진 수
        is_bottleneck  step_rate 가 가장 낮은 구간이면 True

    만들고 나서 **반드시 손계산과 대조한다.** 대조할 값이 없으면
    표본 100건을 눈으로 세어 비율을 낸다. 전수가 아니어도 자릿수는 잡힌다.
    """
    ID, STEP = C.EVENT_ID_COL, C.EVENT_STEP_COL

    # 그레인은 **검진 건 1회**다. 한 건이 같은 단계에 여러 행으로 들어올 수 있으므로
    # (완전중복 188행 — 검증 규칙 4가 경고로 잡는다) 행이 아니라 고유값으로 센다.
    # 행으로 세면 접수가 2,062로 잡혀 분모가 부풀고 전환율이 전부 낮아진다.
    n = {s: fe.loc[fe[STEP] == s, ID].nunique() for s in C.FUNNEL_STEPS}

    rows = []
    first = n[C.FUNNEL_STEPS[0]]
    for i, s in enumerate(C.FUNNEL_STEPS):
        prev = n[C.FUNNEL_STEPS[i - 1]] if i else None
        rows.append({
            "step": s,
            "label": C.FUNNEL_LABELS.get(s, s),
            "n": int(n[s]),
            "step_rate": np.nan if i == 0 else (n[s] / prev if prev else np.nan),
            "cum_rate": n[s] / first if first else np.nan,
            "drop": 0 if i == 0 else int(prev - n[s]),
        })

    out = pd.DataFrame(rows)
    # 병목 = 전 단계 대비 비율이 가장 낮은 구간. 첫 단계는 후보가 아니다(비교 대상이 없다).
    out["is_bottleneck"] = False
    if len(out) > 1:
        out.loc[out["step_rate"].idxmin(), "is_bottleneck"] = True
    return out


@st.cache_data(show_spinner=False)
def funnel_by(fe: pd.DataFrame, se: pd.DataFrame, dim: str,
              step_from: str, step_to: str) -> pd.DataFrame:
    """차원별 특정 구간 전환율. 평균 하나로는 어디를 고칠지 모른다.

    ★ Day3 실습 B에서 채웁니다.

    dim 은 분해 축이다. **무엇으로 쪼갤지는 내가 정한다.**
    기기·채널·지역·요금제·담당자·유입경로 — 도메인마다 다르다.

    쪼개는 기준은 이것이다: 그 축으로 나눴을 때 **손을 쓸 수 있는가.**
    나눠서 격차가 보여도 우리가 못 바꾸는 것이면 분해할 이유가 적다.

    반환: DataFrame[<dim>, 도달, 전환, 전환율, 비중, 사유]

    **못 믿을 칸은 전환을 세지 않는다.** 사유가 있으면 전환·전환율이 NaN 이다.
    계산해 놓고 화면에서 빼는 것이 아니라, 계산 자체를 하지 않는다 —
    값이 변수에 들어 있으면 리포트나 로그로 새어 나간다.
    도달(표본 수)은 **조건 값**이라 감추지 않는다.
    """
    ID, STEP = C.EVENT_ID_COL, C.EVENT_STEP_COL

    # 그레인은 획득 퍼널과 같은 **검진 건 1회**다. 중복 행이 있으므로 고유값으로 센다.
    앞 = set(fe.loc[fe[STEP] == step_from, ID])
    뒤 = set(fe.loc[fe[STEP] == step_to, ID])
    attr = se.set_index(ID)[dim]
    도달 = attr[attr.index.isin(앞)]
    n = 도달.value_counts()
    n = n[n > 0]

    rows = []
    for 칸, 도달수 in n.items():
        # ★ 먼저 묻는다. 걸리면 전환을 **세지 않는다.**
        사유 = trust_check({}, int(도달수))
        if 사유:
            rows.append({dim: 칸, "도달": int(도달수), "전환": np.nan,
                         "전환율": np.nan, "사유": 사유})
            continue
        전환 = len({i for i in 도달.index[도달 == 칸] if i in 뒤})
        rows.append({dim: 칸, "도달": int(도달수), "전환": 전환,
                     "전환율": 전환 / 도달수, "사유": None})

    g = pd.DataFrame(rows)
    # 비중은 도달(표본 수) 기준이라 감추지 않는다. 전환율만 보면 규모를 놓친다.
    g["비중"] = g["도달"] / g["도달"].sum()
    return g.sort_values("전환율", na_position="last").reset_index(drop=True)


# ── 유지 퍼널 ─────────────────────────────────────────────────────
# ── 유지 퍼널 ─────────────────────────────────────────────────────
# 유지 단계의 **조건**. config.RETENTION_STEPS 에 적은 이름이 이 표의 키다.
# 각 조건은 검진건 한 행이 그 단계에 해당하는지를 True/False 로 돌려준다.
# 그레인은 획득 퍼널과 같은 **검진 건 1회**다.
def _t(s):
    """True/False/NULL 이 섞인 컬럼에서 True 만 고른다 (category dtype 안전)."""
    return s.astype("object") == True      # noqa: E712


RETENTION_CONDITIONS = {
    "결과수신":       lambda c: c["_수신"],
    "관측창닫힘":     lambda c: c["_수신"] & c["재검_90일내"].notna(),
    "재검없음":       lambda c: c["재검_90일내"].astype("object") == False,  # noqa: E712
    "재검발생":       lambda c: _t(c["재검_90일내"]),
    "심사유의없음":   lambda c: c["_수신"] & (c["심사유의여부"].astype("object") == False),  # noqa: E712
    "심사유의":       lambda c: _t(c["심사유의여부"]),
    "경계선":         lambda c: _t(c["경계선여부"]),
    "유의항목2개이상": lambda c: c["유의항목수"].fillna(0) >= 2,
}


def _cond(name):
    if name not in RETENTION_CONDITIONS:
        raise KeyError(
            f"유지 단계 '{name}' 의 조건이 없습니다. "
            f"쓸 수 있는 이름: {', '.join(RETENTION_CONDITIONS)}")
    return RETENTION_CONDITIONS[name]


def _retention_base(t: dict) -> pd.DataFrame:
    """검진건 표에 '결과를 수신했는가'를 붙인다. 조건들이 이걸 쓴다."""
    c = t["검진건"].copy()
    e = t[C.FUNNEL_TABLE]
    수신 = set(e.loc[e[C.EVENT_STEP_COL] == C.FUNNEL_STEPS[-1], C.EVENT_ID_COL])
    c["_수신"] = c[C.EVENT_ID_COL].isin(수신)
    return c


@st.cache_data(show_spinner=False)
def retention_funnel(t: dict) -> pd.DataFrame:
    """유지 퍼널. config.RETENTION_STEPS 의 단계대로 센다.

    ★ Day2 실습 D에서 채웁니다.

    획득 퍼널과 다른 점 셋:

        단계    주어지지 않는다. **내가 정의한다**
        방향    한 방향이 아니다. 오갈 수 있다
        시간    며칠이 아니라 몇 달~몇 년

    그래서 그레인이 다르다. 획득은 **대상 하나**지만 유지는 흔히 **대상 × 기간**이다.
    같은 오류의 두 얼굴이다 — 그레인을 잘못 잡으면 둘 다 틀린다.

    **퍼널이 아니면 퍼널이라고 부르지 않는다.** 세 가지를 물어라.

        이 단계는 앞 단계를 반드시 거치는가?  아니면 그냥 분류다
        그레인이 무엇인가?
        기간을 어떻게 자르는가?

    그리고 **관측 기간이 다른 대상을 누적값으로 비교하지 않는다.**
    비교하려면 비율(단위 기간당)로 바꾸거나, 같은 시점에 시작한 것끼리 묶는다.
    7주차 토요일에 겪은 생존 편향이 여기서 다시 나온다.

    반환: DataFrame[step, label, n, step_rate, cum_rate]
    """
    steps = C.RETENTION_STEPS
    if not steps:
        todo("Day2 실습 D", "유지 퍼널",
             "config.RETENTION_STEPS 가 비어 있습니다. 단계 이름과 설명을 "
             "순서대로 넣으십시오. 쓸 수 있는 이름은 RETENTION_CONDITIONS 에 있습니다.",
             "core/config.py  RETENTION_STEPS")

    c = _retention_base(t)
    n = [int(_cond(name)(c).sum()) for name, _ in steps]

    rows, first = [], n[0]
    for i, (name, desc) in enumerate(steps):
        rows.append({
            "step": name,
            "label": desc or name,
            "n": n[i],
            "step_rate": np.nan if i == 0 else (n[i] / n[i-1] if n[i-1] else np.nan),
            "cum_rate": n[i] / first if first else np.nan,
        })
    return pd.DataFrame(rows)


def retention_order_check(t: dict, steps=None) -> pd.DataFrame:
    """**퍼널인지 아닌지를 가른다.**

    앞 단계를 거치지 않고 다음 단계에 나타난 대상이 몇 건인가를 센다.
    많으면 그것은 퍼널이 아니라 그냥 분류다 — 그때는 단계로 쌓지 말고
    분해 축으로 쓴다.

    반환: DataFrame[앞, 뒤, 뒤 건수, 위반, 위반 비율]
    """
    steps = steps if steps is not None else C.RETENTION_STEPS
    c = _retention_base(t)
    ID = C.EVENT_ID_COL
    S = {name: set(c.loc[_cond(name)(c), ID]) for name, _ in steps}

    rows = []
    for (a, _), (b, _) in zip(steps, steps[1:]):
        위반 = S[b] - S[a]
        rows.append({"앞": a, "뒤": b, "뒤 건수": len(S[b]),
                     "위반": len(위반),
                     "위반 비율": len(위반) / len(S[b]) if S[b] else np.nan})
    return pd.DataFrame(rows)


# ── KPI ───────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _kpi_base(t: dict) -> pd.DataFrame:
    """검진건 표에 '수신했는가'와 '언제 수신했는가'를 붙인다."""
    c = _retention_base(t)
    e = t[C.FUNNEL_TABLE].drop_duplicates()
    last = C.FUNNEL_STEPS[-1]
    col = C.DATE_COLS[C.FUNNEL_TABLE]
    수신일 = (e[e[C.EVENT_STEP_COL] == last]
              .groupby(C.EVENT_ID_COL, observed=True)[col].min())
    c["_수신일"] = to_dt(c[C.EVENT_ID_COL].map(수신일))
    return c


def _rates(c: pd.DataFrame) -> dict:
    """지표 셋의 계산식. kpis() 와 monthly() 가 같은 식을 쓴다.

    같은 식을 두 곳에 적으면 반드시 어긋나므로 여기 한 번만 적는다.
    """
    수신 = int(c["_수신"].sum())
    유의 = int(_t(c["심사유의여부"]).sum())
    경계선 = int(_t(c["경계선여부"]).sum())
    닫힘 = int((c["_수신"] & c["재검_90일내"].notna()).sum())
    재검 = int(_t(c["재검_90일내"]).sum())
    return {
        # 주지표 (명세 3행) — 분모는 결과 수신 건. 분자는 검진 측 판정이다.
        "심사유의율": 유의 / 수신 * 100 if 수신 else np.nan,
        # 가드레일 ① — 분모는 수신 건이 아니라 **심사유의 건**이다.
        #   경계선여부는 유의 판정이 있어야 존재한다(구조적 결측).
        "경계선 비율": 경계선 / 유의 * 100 if 유의 else np.nan,
        # 명세 5행 — 분모는 관측 창 90일이 닫힌 건뿐이다.
        #   창이 안 닫힌 건을 분모에 넣으면 재작업률이 실제보다 낮게 나온다.
        "재작업률": 재검 / 닫힘 * 100 if 닫힘 else np.nan,
    }


def kpis(t: dict) -> dict:
    """지표 카드.

    ★ Day2 실습 E에서 채웁니다.

    ★ 아래 컬럼명은 전부 **통신사 것**이다. 내 데이터의 대응 컬럼으로 바꾼다.

        billing_amount  →  금액에 해당하는 컬럼
        is_churned      →  이탈 여부에 해당하는 컬럼

    없는 지표는 **빼면 된다.** 4개일 이유가 없다.

    반환: {"지표이름": {"value": float, "unit": str, "fmt": str}}
          fmt 은 화면 표시 형식이다. 예) "{:.2f}%"  "{:,.0f}원"

    예시 — 통신사:

        f = funnel(t["funnel_events"])
        return {
            "전환율": {"value": f.n.iloc[-1] / f.n.iloc[0] * 100,
                       "unit": "%", "fmt": "{:.2f}%"},
            "ARPU": {"value": float(t["usage_monthly"].billing_amount.mean()),
                     "unit": "원", "fmt": "{:,.0f}원"},
        }
    """
    r = _rates(_kpi_base(t))
    # ⚠ 가드레일 ②③④(건당 유의 항목 수 · 기관별 분산 · 재방문 출장비)는
    #   계산식이 아직 정해지지 않아 넣지 않았다. -> CLAUDE.md 「아직 안 정한 것」
    return {
        "심사유의율":   {"value": r["심사유의율"],   "unit": "%", "fmt": "{:.2f}%"},
        "경계선 비율": {"value": r["경계선 비율"], "unit": "%", "fmt": "{:.2f}%"},
        "재작업률":     {"value": r["재작업률"],     "unit": "%", "fmt": "{:.2f}%"},
    }


@st.cache_data(show_spinner=False)
def monthly(t: dict) -> pd.DataFrame:
    """기간별 추이. 지표 카드의 스파크라인과 아카이브 비교에 쓴다.

    ★ Day2 실습 E에서 채웁니다. (kpis 와 함께)

    kpis() 가 돌려주는 지표 이름과 **열 이름이 대응**되어야 스파크라인이 그려진다.
    기간이 짧아 월별로 나눌 수 없으면 주별로 해도 되고, 아예 빼도 된다.

    반환: 인덱스가 기간(예 "2025-01"), 열이 지표인 DataFrame
    """
    c = _kpi_base(t)
    c = c[c["_수신일"].notna()]
    # **분기로 자른다.** 월로 자르면 수신이 66~100건뿐이라 변동(26.9~48.1%)이
    # 전부 표본 노이즈다(동질성 p=0.271). 판정은 분기 단위로 한다는 것이
    # 이미 정해져 있다. -> CLAUDE.md 「임계값과 근거」
    key = c["_수신일"].dt.to_period("Q").astype(str)
    rows = {g: _rates(sub) for g, sub in c.groupby(key, observed=True)}
    out = pd.DataFrame(rows).T.sort_index()
    out.index.name = "분기"
    return out


def judge_pairs(t: dict) -> list[dict]:
    """인접한 두 분기를 짝지어 **전후 비교** 카드를 만든다.

    실험이 없는 도메인이므로 A/B 대신 구간 비교다. 그래서 **인과를 주장할 수 없다** —
    두 분기는 무작위로 나눈 것이 아니라 시간 순서일 뿐이고, 차이의 원인은
    이 표만으로 알 수 없다. 그 문장을 카드마다 넣는다(각주로 빼면 아무도 안 읽는다).

    판정 순서는 judge() 와 같다: 못 믿을 조건 -> 주지표 -> 가드레일.
    """
    m = monthly(t)
    c = _kpi_base(t)
    q = c.loc[c["_수신일"].notna(), "_수신일"].dt.to_period("Q").astype(str)
    n_by = q.value_counts().to_dict()
    주 = "심사유의율"
    카드 = []
    for 앞, 뒤 in zip(m.index, m.index[1:]):
        n앞, n뒤 = int(n_by.get(앞, 0)), int(n_by.get(뒤, 0))
        row = {"앞": 앞, "뒤": 뒤, "모수": (n앞, n뒤),
               "인과": ("관측 데이터이므로 인과를 주장할 수 없습니다. 두 분기는 무작위로 "
                        "나눈 것이 아니라 시간 순서일 뿐이며, 차이의 원인은 이 표만으로 "
                        "알 수 없습니다.")}

        # ① 못 믿을 조건 — 양쪽 분기 모두 표본을 넘어야 비교할 수 있다.
        사유 = trust_check({}, min(n앞, n뒤))
        if 사유:
            모자란 = 앞 if n앞 <= n뒤 else 뒤
            row.update(판정="무효", 색="block",
                       사유=f"{모자란}: {사유}",
                       설명="못 믿을 조건에 걸려 지표를 계산하지 않았습니다.")
            카드.append(row)
            continue

        # ② 주지표
        a, b = m[주].iloc[m.index.get_loc(앞)], m[주].iloc[m.index.get_loc(뒤)]
        d = b - a
        row.update(주지표={"이름": 주, "앞": a, "뒤": b, "변화": d, "기준": C.MOVE_MIN})

        # ③ 가드레일 — 주지표가 움직였을 때만 본다.
        가드 = []
        for 이름, 한계 in C.GUARDRAILS.items():
            ga = m[이름].iloc[m.index.get_loc(앞)]
            gb = m[이름].iloc[m.index.get_loc(뒤)]
            if pd.isna(ga) or pd.isna(gb):
                가드.append({"이름": 이름, "확인불가": True}); continue
            가드.append({"이름": 이름, "앞": ga, "뒤": gb, "변화": gb - ga,
                         "기준": 한계, "악화": (gb - ga) >= 한계})
        row["가드레일"] = 가드

        if abs(d) < C.MOVE_MIN:
            row.update(판정="차이 없음", 색="none")
        elif any(g.get("악화") for g in 가드):
            row.update(판정="주의 필요", 색="warn")
        else:
            row.update(판정="주목할 만함", 색="ok")
        카드.append(row)
    return 카드


def judge(t: dict) -> dict:
    """직전 분기 대비 최근 분기 판정. **순서가 곧 설계다.**

        1. 믿을 수 있는가   -> 아니면 여기서 끝. 지표를 계산하지 않는다
        2. 주지표가 움직였는가 -> 아니면 "차이 없음"
        3. 가드레일은 괜찮은가 -> 나빠졌으면 "주의 필요"
        4. 다 통과          -> "주목할 만함"

    3번을 2번 뒤에 두는 것이 핵심이다. 주지표가 좋으면 거기서 멈추고 싶어지는데
    코드는 멈추지 않는다. 이 도메인의 주지표는 양방향이라 "성공"이라 부르지 않는다.

    반환: {판정, 색, 단계[...], 사유}  — 못 믿으면 주지표·가드레일 값이 없다.
    """
    m = monthly(t)
    단계 = []

    # ① 믿을 수 있는가. 최근 분기의 표본으로 묻는다.
    c = _kpi_base(t)
    최근 = m.index[-1]
    n = int((c["_수신일"].dt.to_period("Q").astype(str) == 최근).sum())
    사유 = trust_check({}, n)
    if 사유 or len(m) < 2:
        사유 = 사유 or f"비교할 직전 분기가 없음 (분기 {len(m)}개)"
        단계.append({"이름": "못 믿을 조건 확인", "통과": False, "값": 사유})
        단계.append({"이름": "주지표", "통과": None, "값": "계산하지 않음"})
        단계.append({"이름": "가드레일", "통과": None, "값": "계산하지 않음"})
        return {"판정": "판정 보류", "색": "block", "단계": 단계, "사유": 사유,
                "기간": f"{최근}", "표본": n}
    단계.append({"이름": "못 믿을 조건 확인", "통과": True,
                 "값": f"표본 {n:,}건 (최소 {C.MIN_SAMPLE:,}) · 통과"})

    직전 = m.index[-2]
    주 = "심사유의율"
    변화 = m[주].iloc[-1] - m[주].iloc[-2]
    단계.append({"이름": f"주지표 · {주}", "통과": abs(변화) >= C.MOVE_MIN,
                 "값": f"{m[주].iloc[-2]:.2f}% -> {m[주].iloc[-1]:.2f}% ({변화:+.2f}%p)"})

    # ② 움직였는가. 평소 변동 폭 안이면 여기서 끝.
    if abs(변화) < C.MOVE_MIN:
        단계.append({"이름": "가드레일", "통과": None,
                     "값": "주지표가 안 움직여 확인하지 않음"})
        return {"판정": "차이 없음", "색": "none", "단계": 단계, "사유": None,
                "기간": f"{직전} -> {최근}", "표본": n, "주지표": 변화}

    # ③ 가드레일. 주지표가 움직였어도 여기서 멈추지 않는다.
    악화, 확인불가 = [], []
    for 이름, 한계 in C.GUARDRAILS.items():
        a, b = m[이름].iloc[-2], m[이름].iloc[-1]
        if pd.isna(a) or pd.isna(b):
            확인불가.append(이름)
            단계.append({"이름": f"가드레일 · {이름}", "통과": None,
                         "값": "관측 창이 안 닫혀 확인할 수 없음"})
            continue
        d = b - a
        나쁨 = d >= 한계          # 둘 다 높을수록 나쁜 지표다
        if 나쁨: 악화.append(f"{이름} {a:.2f}% -> {b:.2f}% ({d:+.2f}%p)")
        단계.append({"이름": f"가드레일 · {이름}", "통과": not 나쁨,
                     "값": f"{a:.2f}% -> {b:.2f}% ({d:+.2f}%p, 한계 {한계}%p)"})

    if 악화:
        return {"판정": "주의 필요", "색": "warn", "단계": 단계,
                "사유": " · ".join(악화), "기간": f"{직전} -> {최근}",
                "표본": n, "주지표": 변화}
    return {"판정": "주목할 만함", "색": "ok", "단계": 단계,
            "사유": (f"가드레일 {', '.join(확인불가)} 확인 불가 — "
                     "무엇을 희생했는지 일부만 확인됨") if 확인불가 else None,
            "기간": f"{직전} -> {최근}", "표본": n, "주지표": 변화}


def status_of(name: str, value: float) -> str:
    """지표 값을 상태 색으로 판정한다. 임계값은 config.THRESHOLDS 에 있다.

    이 함수는 **그대로 쓴다.** 판정 규칙이지 도메인이 아니다.
    THRESHOLDS 가 비어 있으면 전부 "ok"로 나온다 — 채우면 색이 갈린다.
    """
    th = C.THRESHOLDS.get(name)
    if not th:
        return "ok"
    # 양방향 지표 — 위쪽 경계도 본다. 상한이 없는 지표는 이 두 줄을 그냥 지나간다.
    # 이게 없으면 "경고 29 / 위험 25"만 보고 48%도 정상으로 판정한다.
    if "위험_상한" in th and value > th["위험_상한"]:
        return "block"
    if "경고_상한" in th and value > th["경고_상한"]:
        return "warn"

    # ★ 높을수록 나쁜 지표. 내 지표 이름을 넣는다.
    higher_is_worse = {"이탈률", "이탈율", "해지율", "불량률", "반품률",
                       "재작업률", "경계선 비율"}
    if name in higher_is_worse:
        return ("block" if value > th["위험"]
                else "warn" if value > th["경고"] else "ok")
    return ("block" if value < th["위험"]
            else "warn" if value < th["경고"] else "ok")


# ── 실험 ──────────────────────────────────────────────────────────
# ★ 실험별로 어느 구간을 보는지. 도메인이 바뀌면 이 표를 갈아끼운다.
#   실험이 없는 도메인이면 비워 둔다.
EXP_STEPS: dict[str, tuple[str, str]] = {
    "EXP-001": ("랜딩방문", "요금제조회"),
    "EXP-002": ("요금제조회", "신청시작"),
    "EXP-003": ("신청시작", "신청완료"),
    "EXP-004": ("요금제조회", "신청시작"),
    "EXP-005": ("요금제조회", "신청시작"),
}


def _two_prop(sc, nc, stt, nt):
    """두 비율 비교. 차이·신뢰구간·p값을 함께 돌려준다.

    **그대로 쓴다.** 통계 계산은 도메인이 바뀌어도 같다.

    p값만 보면 '유의하지만 실질 효과가 없는' 경우를 놓친다.
    그래서 신뢰구간을 항상 함께 계산해 화면에 그린다.
    """
    rc, rt = sc / nc, stt / nt
    se = np.sqrt(rc * (1 - rc) / nc + rt * (1 - rt) / nt)
    if se == 0:
        return dict(rc=rc, rt=rt, nc=nc, nt=nt, diff=0, lo=0, hi=0, p=1.0, lift=0)
    z = (rt - rc) / se
    return dict(rc=rc, rt=rt, nc=nc, nt=nt, diff=rt - rc,
                lo=(rt - rc) - 1.96 * se, hi=(rt - rc) + 1.96 * se,
                p=2 * (1 - stats.norm.cdf(abs(z))),
                lift=(rt / rc - 1) if rc else 0)


def srm_check(asg: pd.DataFrame, exp_id: str) -> dict:
    """SRM(Sample Ratio Mismatch). 배정이 50:50인지 검정한다.

    **그대로 쓴다.** 7주차에 손으로 해본 그 계산이다.

    배정이 50:50이 아니면 배정 로직에 버그가 있다는 뜻이고,
    그 경우 어떤 효과가 나오든 해석할 수 없다.
    """
    a = asg[asg.experiment_id == exp_id]
    c = int((a.variant == "control").sum())
    t = int((a.variant == "treatment").sum())
    if c + t == 0:
        return {"ok": False, "c": 0, "t": 0, "p": 1.0, "ratio": (0.0, 0.0)}
    p = stats.chisquare([c, t]).pvalue
    return {"ok": p >= 0.001, "c": c, "t": t, "p": float(p),
            "ratio": (c / (c + t), t / (c + t))}


def trust_check(srm: dict, n_total: int, days: int | None = None) -> str | None:
    """이 실험을 믿을 수 있는가. **계산하기 전에** 묻는다.

    ★ Day3 실습 C에서 채웁니다. ← 오늘의 핵심

    ────────────────────────────────────────────────────────────
    오늘의 어려운 일은 계산이 아니다.
    **계산은 이미 할 수 있는데, 화면에 안 그리는 코드를 쓰는 것**이다.
    ────────────────────────────────────────────────────────────

    못 믿을 조건은 셋인데 **분기는 하나**다.

        배정이 깨졌다      srm["ok"] 가 False
                          → 어떤 효과가 나와도 해석할 수 없다
        표본이 모자란다    n_total 이 config.MIN_SAMPLE 미만
                          → 계산해도 못 믿는다. 내 데이터는 대개 여기 걸린다
        기간이 안 찼다     days 가 최소 기간 미만
                          → 초기 효과가 남아 있다

    하나라도 걸리면 **사유 문자열**을 돌려준다. 돌려주면
    experiment_results() 가 거기서 멈추고 **지표를 계산하지 않는다.**
    다 통과하면 None 을 돌려준다.

    "그래도 회색으로라도 보여주면 안 되나요?"

        안 됩니다. **사람은 본 숫자를 기억합니다.**
        옆에 아무리 경고를 붙여도 회의실에서 인용되는 것은 숫자입니다.

    반환: 못 믿을 이유(str) 또는 None
    """
    # 분기는 하나다. 조건이 셋이라고 분기를 셋으로 만들면 나중에 하나를 빠뜨린다.
    # 걸리면 사유를 돌려주고, 부르는 쪽은 거기서 멈춘다 — 지표를 계산하지 않는다.

    # ① 표본이 모자란다. 이 도메인은 대개 여기 걸린다.
    if n_total < C.MIN_SAMPLE:
        return f"표본 {n_total:,}건 (최소 {C.MIN_SAMPLE:,})"

    # ② 기간이 안 찼다. 아직 다음 단계로 갈 시간이 없는 건이 섞여 있다.
    if days is not None and days < C.MIN_DAYS:
        return (f"관측 {days}일 (최소 {C.MIN_DAYS}일 — "
                f"의뢰부터 결과 수신까지 걸리는 최대 기간)")

    # ③ 비교가 공정하지 않다. 이 도메인엔 실험이 없으므로 배정 비율 대신
    #    "유효 구간 밖 건이 섞였는가"를 본다. 부르는 쪽이 srm 으로 넘긴다.
    if srm and not srm.get("ok", True):
        return srm.get("reason") or "비교 조건이 공정하지 않음"

    return None


@st.cache_data(show_spinner=False)
def experiment_results(t: dict) -> list[dict]:
    """실험 결과와 판정.

    **판정 순서가 이 함수의 전부다.** 믿을 수 있는지 먼저 묻고,
    믿을 수 있을 때만 계산한다.

    좋은 결과를 먼저 보면 경고를 무시하고 싶어진다. 그래서 사람의 규율에
    맡기지 않고 **코드로 순서를 박는다.**

    실험이 없는 도메인이면 이 함수는 빈 목록을 돌려준다. 대신 전후 비교
    카드를 만들되 **"인과 주장 불가"를 카드에 박아 둔다.** → DESIGN.md §4-4
    """
    if "experiments" not in t or "experiment_assignments" not in t:
        return []
    ex, asg, fe = t["experiments"], t["experiment_assignments"], t["funnel_events"]
    reach = {s: set(fe.loc[fe.funnel_step == s, "visitor_id"]) for s in C.FUNNEL_STEPS}
    out = []
    for _, e in ex.iterrows():
        eid = e.experiment_id
        srm = srm_check(asg, eid)
        n_total = int((asg.experiment_id == eid).sum())
        row = {
            "id": eid, "name": e.experiment_name, "hypothesis": e.hypothesis,
            "primary": e.primary_metric, "guardrail": e.guardrail_metric,
            "start": e.start_date, "end": e.end_date, "srm": srm,
        }

        # ★ 판정이 계산보다 먼저다. 못 믿으면 여기서 끝난다.
        reason = trust_check(srm, n_total)
        if reason:
            row["verdict"] = "무효"
            row["color"] = "block"
            row["reason"] = reason
            out.append(row)
            continue        # 지표를 계산하지 않는다. 숨기는 것이 아니다.

        # ── 여기부터 계산 ─────────────────────────────────────────
        if eid not in EXP_STEPS:
            row.update(verdict="데이터 없음", color="none",
                       reason="EXP_STEPS 에 이 실험의 구간이 없습니다.")
            out.append(row)
            continue
        sf, stp = EXP_STEPS[eid]
        a = asg[asg.experiment_id == eid][["visitor_id", "variant", "assigned_at"]]
        a = a[a.visitor_id.isin(reach[sf])]
        a = a.assign(conv=a.visitor_id.isin(reach[stp]).astype(int))
        g = a.groupby("variant", observed=True).conv.agg(["sum", "count"])
        if len(g) < 2:
            row.update(verdict="데이터 없음", color="none")
            out.append(row)
            continue
        r = _two_prop(g.loc["control", "sum"], g.loc["control", "count"],
                      g.loc["treatment", "sum"], g.loc["treatment", "count"])
        row.update(r, step_from=sf, step_to=stp, assignments=a)

        # 가드레일 — 주지표를 올리려 할 때 희생될 수 있는 것
        # ★ 아래는 통신사 컬럼(is_churned)이다. 내 가드레일 지표로 바꾼다.
        row["guard"] = None
        if "유지율" in str(e.guardrail_metric) and "customers" in t:
            cu = t["customers"]
            m = cu.merge(a[["visitor_id", "variant"]], on="visitor_id", how="inner")
            if len(m) and m.variant.nunique() == 2:
                ret = m.groupby("variant", observed=True).is_churned.mean()
                row["guard"] = {
                    "name": e.guardrail_metric,
                    "control": float(1 - ret["control"]),
                    "treatment": float(1 - ret["treatment"]),
                    "delta": float((1 - ret["treatment"]) - (1 - ret["control"])),
                }

        # 판정 — ★ 3%p 는 예시다. 내 가드레일 기준으로 바꾼다.
        sig = r["p"] < 0.05
        guard_bad = row["guard"] is not None and row["guard"]["delta"] < -0.03
        if guard_bad:
            # 주지표가 좋아져도 가드레일이 무너지면 성공이 아니다
            row.update(verdict="주의 필요", color="warn",
                       reason="주지표는 개선됐으나 가드레일이 악화됐습니다.")
        elif sig and r["lift"] > 0:
            row.update(verdict="성공", color="ok", reason="")
        elif sig:
            row.update(verdict="악화", color="block", reason="")
        else:
            row.update(verdict="효과 없음", color="none",
                       reason="통계적으로 유의한 차이가 없습니다.")
        out.append(row)
    return out


def peeking_curve(res: dict, start: str, cuts=(7, 14, 30, 60, 92)) -> pd.DataFrame:
    """관측 시점별 누적 결과. '그때 멈췄다면 무엇을 봤을까'를 재현한다.

    **그대로 쓴다.** 7주차에 겪은 조기 중단이다.
    """
    a = res.get("assignments")
    if a is None:
        return pd.DataFrame()
    a = a.copy()
    a["d"] = (to_dt(a.assigned_at) - pd.Timestamp(start)).dt.days
    rows = []
    for c in cuts:
        s = a[a.d <= c].groupby("variant", observed=True).conv.agg(["sum", "count"])
        if len(s) < 2 or s["count"].min() < 30:
            continue
        r = _two_prop(s.loc["control", "sum"], s.loc["control", "count"],
                      s.loc["treatment", "sum"], s.loc["treatment", "count"])
        rows.append({"cut": c, "lift": r["lift"], "p": r["p"], "sig": r["p"] < 0.05})
    return pd.DataFrame(rows)


def weekly_effect(res: dict, start: str, bucket_days: int = 14) -> pd.DataFrame:
    """기간을 쪼개 효과 추이를 본다. 신규성 효과는 전체 평균에 가려진다.

    **그대로 쓴다.** 7주차에 겪은 그것이다.
    """
    a = res.get("assignments")
    if a is None:
        return pd.DataFrame()
    a = a.copy()
    a["b"] = (to_dt(a.assigned_at) - pd.Timestamp(start)).dt.days // bucket_days
    g = (a[a.b >= 0].groupby(["b", "variant"], observed=True).conv
         .mean().unstack().dropna())
    if g.empty:
        return pd.DataFrame()
    g["lift"] = g.treatment / g.control - 1
    g = g.reset_index()
    g["label"] = g.b.apply(lambda i: f"{int(i)*2+1}~{int(i)*2+2}주")
    return g


# ── 채널 효율 (선택 과제) ─────────────────────────────────────────
@st.cache_data(show_spinner=False)
def channel_efficiency(t: dict) -> pd.DataFrame:
    """비용만 보면 순위가 뒤집힌다. 유지율까지 반영한 유효 비용을 함께 낸다.

    ★ Day3 선택 과제입니다. 안 만들어도 나머지가 돕니다.

    획득 비용이 싼 경로가 실제로 싼 것이 아니다 —
    데려온 대상이 남지 않으면 같은 자리를 다시 채워야 한다.

        유효 비용 = 획득 비용 / 유지율

    비용 개념이 없으면 **투입 공수(인시)**로 해도 된다.
    획득 경로 구분이 없으면 이 함수를 지운다.

    ★ 여기 쓰이는 CHANNEL_CAC 는 **가정값**이다. 광고비 실측 테이블에서
      유도하지 않는다 — 광고비는 개인 단위로 추적되지 않아 가입과 이을 수 없다.
      리포트에 이 값이 들어가면 "가정값 기반"을 문장에 남긴다. → DESIGN.md §4-3

    반환: DataFrame[채널, 방문, 가입, 전환율, CAC, 유지율, 유효CAC, 역전]
    """
    todo("Day3 선택 과제", "채널 효율",
         "내 도메인에 획득 경로 구분이 있습니까? 비용이 없으면 투입 공수로 바꾸십시오.",
         "core/metrics.py  channel_efficiency()")


# ── 제안 주제 후보 ────────────────────────────────────────────────
# **하나를 고르지 않는다.** 고르는 것은 사람이 한다. 여기서는 비교할 수 있는 것을
# 전부 비교해 놓고, 규모로 줄만 세운다.
#
# 임계값을 **새로 만들지 않았다.** 빌려 쓴 것과 그 이유:
#
#   C.MIN_SAMPLE  → trust_check() 를 통해 "비교 자체가 안 되는 칸"을 거른다.
#                   이 파일이 이미 쓰던 그 기준이다.
#   C.MOVE_MIN    → 격차가 작아 기각할 때의 선(5.0%p). 평소 분기간 변동을
#                   실제로 재서 정한 값이고(config §판정 기준), 이 앱에서
#                   "이만큼은 움직여야 움직인 것"을 뜻하는 값은 이것뿐이다.
#                   격차에도 같은 뜻으로 빌려 쓴다.
#   C.GUARDRAILS  → 가드레일 지표의 추세 악화 선. judge_pairs() 가 쓰는 값 그대로.
#   C.THRESHOLDS  → status_of() 를 통해서만 읽는다. 여기서 값을 직접 보지 않는다.
#
# 그리고 "흔들림보다 작은 격차는 격차가 아니다"(판단기준 2026-09-15)를 함께 건다.
# 이건 임계값이 아니라 표본 수에서 나오는 산술이다 — 한 건이 바꾸는 폭의 합.


def _annual(n: float) -> float:
    """기간 건수를 연간으로 환산한다. **현재 시각을 쓰지 않는다.**

    기간은 config.PERIOD 에서만 온다. datetime.now() 를 쓰면 같은 입력에
    다른 결과가 나오고, 어제 만든 문서와 오늘 만든 문서의 숫자가 달라진다.
    """
    a, b = (pd.Timestamp(x) for x in C.PERIOD)
    일수 = (b - a).days + 1
    return float(n) * 365.25 / 일수 if 일수 > 0 else float(n)


def _흔들림(*ns) -> float:
    """비교한 칸들의 '한 건 흔들림' 합(%p). 한 건이 바뀌면 이만큼 움직인다."""
    return sum(100.0 / n for n in ns if n)


def _reject(격차: float, *ns) -> str | None:
    """기각 사유. **기각은 '비교했는데 차이가 작다'이다.**

    비교 자체가 안 되는 칸(표본 미달)은 여기 오기 전에 이미 빠져 있다.
    """
    흔 = _흔들림(*ns)
    if 격차 < C.MOVE_MIN:
        return (f"격차 {격차:.2f}%p — 최소 움직임 {C.MOVE_MIN:.1f}%p"
                f"(config.MOVE_MIN) 미만이다")
    if 격차 <= 흔:
        return (f"격차 {격차:.2f}%p — 한 건 흔들림 합 {흔:.2f}%p 이하다. "
                f"몇 건이면 사라진다")
    return None


def _topic(키, 제목, 한줄, 규모, 근거축, 구간, 기각사유=None) -> dict:
    return {"키": 키, "제목": 제목, "한줄": 한줄,
            "규모_연간건수": 규모, "근거축": 근거축,
            "구간": 구간, "기각사유": 기각사유}


# 분기별 분모. **지표마다 분모가 다르다** — 수신 건수 하나로 표본을 재면
# 재작업률(관측 창이 닫힌 건)과 경계선 비율(심사유의 건)이 미달인데도 통과한다.
# ⚠ 아래 네 식은 _rates() 안의 것과 **같은 식**이다. 한쪽만 고치면 어긋난다.
#    (_rates() 가 분모까지 돌려주게 고치는 편이 옳지만, 그건 monthly() 의
#     열 이름에 영향을 주므로 지시를 받고 한다.)
def _counts(c: pd.DataFrame) -> dict:
    return {"심사유의율": int(c["_수신"].sum()),
            "경계선 비율": int(_t(c["심사유의여부"]).sum()),
            "재작업률": int((c["_수신"] & c["재검_90일내"].notna()).sum())}


def proposal_topics(t: dict, recent: int = 1) -> list[dict]:
    """제안서로 쓸 만한 주제 후보를 **가능한 만큼** 뽑는다.

    ★ 하나를 고르지 않는다. 고르는 것은 사람이 한다.

    후보를 만드는 곳 넷:

        ① 퍼널 구간   전환율을 낮은 순으로 세우고 **이웃한 두 구간의 격차**
        ② 분해 축     config.DIMS 각 축에서 **최고 칸과 최저 칸**의 전환율 격차
        ③ 임계값      status_of() 가 "ok" 가 아닌 지표
        ④ 추세        최근 구간 평균이 직전 구간 평균보다 나빠진 지표

    두 가지는 지시와 다르게 했다. **없는 것을 지어내지 않으려고 그랬다.**

      · `config.FUNNEL_DIMS` 는 이 앱에 없다. 분해 축은 `config.DIMS` 다.
      · ④ 의 단위는 **개월이 아니라 분기**다. monthly() 가 분기로 자르고,
        그렇게 정한 이유가 config 에 적혀 있다 — 월 수신이 66~100건뿐이라
        월별 변동이 전부 표본 노이즈다(동질성 p=0.271). `recent` 는 분기 수다.

    **기각과 '비교 불가'는 다르다.**

        기각      비교는 했는데 차이가 작다 → 목록에 **남기고** 기각사유를 적는다
        비교 불가 표본이 모자라 비교 자체가 안 된다 → **후보로 만들지 않는다**

    비교 불가를 후보로 만들면, 못 믿을 값이 제목을 달고 목록에 남는다.
    화면에서 감춘 값을 제안 목록으로 돌려보내는 셈이다.

    반환: 규모_연간건수 내림차순. **기각된 것은 맨 뒤로.**
          한 후보의 모양은
          {"키", "제목", "한줄", "규모_연간건수", "근거축", "구간", "기각사유"}
    """
    후보: list[dict] = []
    fe = t[C.FUNNEL_TABLE]
    se = t[C.TABLES[0]]
    f = funnel(fe)
    S, L = C.FUNNEL_STEPS, C.FUNNEL_LABELS
    첫단계 = int(f.n.iloc[0])

    # ── ① 퍼널 구간 ───────────────────────────────────────────────
    # 구간(i-1 → i)을 전환율 낮은 순으로 세우고, **이웃한 두 구간**을 견준다.
    # 낮은 쪽이 후보다 — 높은 쪽과 견주면 어느 구간이든 격차가 생겨 버린다.
    구간들 = [{"from": S[i - 1], "to": S[i],
               "도달": int(f.n.iloc[i - 1]), "율": float(f.step_rate.iloc[i]) * 100}
              for i in range(1, len(S))]
    구간들.sort(key=lambda x: x["율"])
    for 낮, 다음 in zip(구간들, 구간들[1:]):
        # 못 믿을 조건 — 도달이 모자라면 비교 자체가 안 된다.
        if trust_check({}, 낮["도달"]) or trust_check({}, 다음["도달"]):
            continue
        격차 = 다음["율"] - 낮["율"]
        이름 = f'{L.get(낮["from"], 낮["from"])} → {L.get(낮["to"], 낮["to"])}'
        후보.append(_topic(
            키=f'구간:{낮["from"]}>{낮["to"]}',
            제목=f"{이름} 구간의 이탈을 줄인다",
            한줄=(f'{낮["율"]:.2f}% ({int(낮["도달"] * 낮["율"] / 100):,}/'
                  f'{낮["도달"]:,}) vs 다음으로 낮은 구간 {다음["율"]:.2f}% '
                  f"— 격차 {격차:.2f}%p"),
            규모=격차 / 100 * _annual(낮["도달"]),
            근거축="퍼널 구간",
            구간=이름,
            기각사유=_reject(격차, 낮["도달"], 다음["도달"])))

    # ── ② 분해 축 ─────────────────────────────────────────────────
    # 어느 구간을 쪼갤지는 이미 정해져 있다 — 병목 구간이다(판단기준 2026-09-03
    # "보는 구간 → 전체가 아니라 병목 한 구간"). 여기서 새로 정하지 않는다.
    bi = max(int(f.index[f.is_bottleneck][0]), 1)
    s_from, s_to = S[bi - 1], S[bi]
    구간이름 = f"{L.get(s_from, s_from)} → {L.get(s_to, s_to)}"
    for dim in C.DIMS:                       # ← config.FUNNEL_DIMS 가 아니라 DIMS
        if dim not in se.columns:
            continue
        g = funnel_by(fe, se, dim, s_from, s_to)
        쓸 = g[g["사유"].isna()]
        # 못 믿을 칸은 funnel_by 가 이미 전환율을 NaN 으로 둔다. 두 칸이 안 남으면
        # **비교 자체가 안 된다** — 기각이 아니라 후보를 안 만든다.
        if len(쓸) < 2:
            continue
        최저 = 쓸.loc[쓸["전환율"].idxmin()]
        최고 = 쓸.loc[쓸["전환율"].idxmax()]
        격차 = float(최고["전환율"] - 최저["전환율"]) * 100
        도달 = int(최저["도달"])
        후보.append(_topic(
            키=f"축:{dim}",
            제목=f"{dim} {최저[dim]} 칸의 이탈을 줄인다",
            한줄=(f'{최저[dim]} {float(최저["전환율"]) * 100:.2f}% '
                  f'({int(최저["전환"]):,}/{도달:,}) vs '
                  f'{최고[dim]} {float(최고["전환율"]) * 100:.2f}% '
                  f'({int(최고["전환"]):,}/{int(최고["도달"]):,}) '
                  f'— 격차 {격차:.2f}%p · 비중 {float(최저["비중"]) * 100:.2f}% '
                  f'(분모 구간 도달 {int(g["도달"].sum()):,}건)'
                  + (f' · 감춘 칸 {int(g["사유"].notna().sum())}개'
                     if g["사유"].notna().any() else "")),
            규모=격차 / 100 * _annual(도달),
            근거축=dim,
            구간=구간이름,
            기각사유=_reject(격차, 도달, int(최고["도달"]))))

    # ── ③ 임계값 ─────────────────────────────────────────────────
    # 임계값은 status_of() 를 통해서만 읽는다. 여기서 THRESHOLDS 를 직접 보지 않는다.
    # 임계값이 아예 없는 지표(가드레일 둘)는 **비교 자체가 안 된다** — 후보를 안 만든다.
    # (config 에 "가드레일 임계값은 미정"이라고 적혀 있다. 여기서 정하지 않는다.)
    c = _kpi_base(t)
    분모 = _counts(c)
    for 이름, v in kpis(t).items():
        if 이름 not in C.THRESHOLDS:
            continue
        n = 분모.get(이름, 0)
        if trust_check({}, n):
            continue
        값 = float(v["value"])
        상태 = status_of(이름, 값)
        후보.append(_topic(
            키=f"임계:{이름}",
            제목=f"{이름}이 임계값을 벗어났다",
            한줄=f"{이름} {값:.2f}% (분모 {n:,}건) · 판정 {상태}",
            # 규모는 분모 전체다 — 지표가 임계를 벗어나면 그 분모 전부가 대상이다.
            규모=_annual(n) if 상태 != "ok" else 0.0,
            근거축="임계값",
            구간=f"{C.PERIOD[0]} ~ {C.PERIOD[1]}",
            기각사유=None if 상태 != "ok" else "임계값 안에 있다"))

    # ── ④ 추세 ───────────────────────────────────────────────────
    # 단위는 분기다(위 docstring 참고). 나빠지는 방향은 지표마다 다르다 —
    # 주지표는 양방향이라 **움직인 것 자체**를 보고, 가드레일은 오르는 쪽만 본다.
    m = monthly(t)
    q = c.loc[c["_수신일"].notna(), "_수신일"].dt.to_period("Q").astype(str)
    분기분모 = {g: _counts(sub) for g, sub in c[c["_수신일"].notna()].groupby(q)}
    if len(m) >= recent * 2:
        최근, 직전 = m.iloc[-recent:], m.iloc[-recent * 2:-recent]
        기간 = f"{직전.index[0]} ~ {최근.index[-1]}"
        for 이름 in m.columns:
            쓸분기 = [g for g in list(직전.index) + list(최근.index)
                      if not trust_check({}, 분기분모.get(g, {}).get(이름, 0))]
            # 한 분기라도 그 지표의 분모가 모자라면 평균을 낼 수 없다 → 비교 불가.
            if len(쓸분기) < recent * 2:
                continue
            a, b = float(직전[이름].mean()), float(최근[이름].mean())
            if pd.isna(a) or pd.isna(b):
                continue
            변화 = b - a
            선 = C.GUARDRAILS.get(이름, C.MOVE_MIN)
            나빠짐 = 변화 >= 선 if 이름 in C.GUARDRAILS else abs(변화) >= 선
            n = min(분기분모[g][이름] for g in 쓸분기)
            후보.append(_topic(
                키=f"추세:{이름}",
                제목=f"{이름}의 최근 {recent}분기 흐름을 확인한다",
                한줄=(f"{이름} 직전 {recent}분기 평균 {a:.2f}% → "
                      f"최근 {recent}분기 평균 {b:.2f}% ({변화:+.2f}%p) · "
                      f"선 {선:.1f}%p"
                      + ("" if 이름 in C.GUARDRAILS else " (양방향)")),
                규모=abs(변화) / 100 * _annual(n) if 나빠짐 else 0.0,
                근거축="추세",
                구간=기간,
                기각사유=None if 나빠짐 else
                        f"변화 {변화:+.2f}%p — 선 {선:.1f}%p 에 못 미친다"))

    # 규모가 큰 순서. **기각된 것은 맨 뒤로 — 지우지는 않는다.**
    후보.sort(key=lambda x: (x["기각사유"] is not None, -x["규모_연간건수"]))
    return 후보


# ── 주제 하나의 근거 ──────────────────────────────────────────────
# proposal_topics() 가 "무엇을 쓸 수 있나"를 늘어놓는다면, 여기는 고른 하나에 대해
# **제안서가 쓸 근거를 한 번에 모아 온다.**
#
# ★ 이 함수는 **조회만 한다.** 문장을 만들지 않는다.
#   "4군이 낮다" 같은 문장은 여기서 나오면 안 된다 — 표와 수만 돌려주고,
#   읽는 문장은 문서를 쓰는 쪽이 만든다. 여기서 문장을 만들기 시작하면
#   같은 값이 두 곳에서 다른 말로 설명된다.
#
# ★ 없는 것은 **지어내지 않고 None** 으로 둔다. 대신 왜 없는지를 같은 칸에 적는다.
#   None 만 돌려주면 부르는 쪽이 "아직 안 만든 것"과 "있을 수 없는 것"을 못 가린다.
#
# ★ **실측과 환산을 같은 칸에 섞지 않는다.** 키를 나눈다 — 섞으면 읽는 사람은
#   둘 다 실측으로 읽는다 (DESIGN.md §4-3 · 판단기준 2026-09-02).


def _blank(사유: str) -> dict:
    """낼 것이 없는 칸. **비워 두지 않고 왜 없는지를 적는다.**"""
    return {"표": None, "사유": 사유}


def _funnel_now(f: pd.DataFrame, 강조: tuple | None) -> dict:
    """현황 — 퍼널 전체. 병목과, 이 주제가 가리키는 구간을 표시한다."""
    L = C.FUNNEL_LABELS
    행 = []
    for i in range(len(f)):
        step = f.step.iloc[i]
        앞 = f.step.iloc[i - 1] if i else None
        행.append({
            "단계": L.get(step, step),
            "도달": int(f.n.iloc[i]),
            "단계 전환율": (None if i == 0
                            else round(float(f.step_rate.iloc[i]) * 100, 2)),
            "누적 전환율": round(float(f.cum_rate.iloc[i]) * 100, 2),
            # f.drop 은 DataFrame.drop() 메서드와 부딪힌다. 열은 대괄호로 집는다.
            "이탈": int(f["drop"].iloc[i]),
            "병목": bool(f.is_bottleneck.iloc[i]),
            "이 주제": bool(강조 and 앞 == 강조[0] and step == 강조[1]),
        })
    return {"표": pd.DataFrame(행), "사유": None}


def _dim_table(fe, se, dim: str, s_from: str, s_to: str) -> dict:
    """원인 — 분해 축 표. **감춘 칸도 지우지 않고 사유와 함께 남긴다.**

    화면에서 감춘 것을 근거에서 빼 버리면, 무엇을 못 봤는지가 사라진다.
    """
    g = funnel_by(fe, se, dim, s_from, s_to).copy()
    쓸 = g[g["사유"].isna()]
    표시 = pd.Series("", index=g.index, dtype=object)
    if len(쓸) >= 1:
        표시.loc[쓸["전환율"].idxmin()] = "최저"
        표시.loc[쓸["전환율"].idxmax()] = "최고"
    표시[g["사유"].notna()] = "감춤"
    g["표시"] = 표시
    g["전환율"] = (g["전환율"] * 100).round(2)
    g["비중"] = (g["비중"] * 100).round(2)
    L = C.FUNNEL_LABELS
    return {
        "표": g[[dim, "도달", "전환", "전환율", "비중", "표시", "사유"]],
        "축": dim,
        "구간": f"{L.get(s_from, s_from)} → {L.get(s_to, s_to)}",
        "비중_분모": int(g["도달"].sum()),
        "감춘_칸": int(g["사유"].notna().sum()),
        "비교_가능_칸": int(len(쓸)),
        "사유": (None if len(쓸) >= 2 else
                 f"비교할 칸이 {len(쓸)}개다. 최소 두 칸이 있어야 격차를 낸다"),
    }


def _size(격차: float | None, 도달: int | None, 비중: float | None,
           분모: int | None, 가정: list[str]) -> dict:
    """규모 — **실측과 환산을 나눠 담는다.**

    실측: 데이터에서 그대로 읽은 것.
    환산: 실측에 기간 배수를 곱한 것. 가정이 붙어 있다.
    """
    if 격차 is None or 도달 is None:
        return {"실측": None, "환산": None, "가정": [],
                "사유": "격차나 도달을 낼 수 없어 규모를 계산하지 않았다"}
    a, b = (pd.Timestamp(x) for x in C.PERIOD)
    일수 = (b - a).days + 1
    배수 = 365.25 / 일수 if 일수 > 0 else 1.0
    기간건수 = 격차 / 100 * 도달
    return {
        # 실측 — 기간(config.PERIOD) 안에서 실제로 센 것
        "실측": {"격차_%p": round(격차, 2), "도달": int(도달),
                 "비중_%": (None if 비중 is None else round(비중, 2)),
                 "비중_분모": 분모,
                 "기간_건수": round(기간건수, 1),
                 "기간": f"{C.PERIOD[0]} ~ {C.PERIOD[1]} ({일수}일)"},
        # 환산 — 위 값에 배수를 곱한 것. **실측이 아니다.**
        "환산": {"연간_건수": round(기간건수 * 배수, 1), "배수": round(배수, 4)},
        "가정": 가정,
        "사유": None,
    }


def _trend(t: dict, 지표: str | None, 개월: int = 12) -> dict:
    """추세 — 관련 지표의 최근 구간. **단위는 분기다.**

    지시는 "최근 12개월"이었다. monthly() 는 **분기**로 자르고, 그렇게 정한
    이유가 config 에 적혀 있다 — 월 수신이 66~100건뿐이라 월별 변동이 전부
    표본 노이즈다(동질성 p=0.271). 12개월을 **4분기**로 읽는다.

    분기마다 **그 지표의 분모**로 표본을 따로 본다. 수신 건수 하나로 재면
    재작업률·경계선 비율이 미달인데도 통과한다.
    """
    if 지표 is None:
        return {"표": None, "단위": None,
                "사유": ("이 주제는 지표가 아니라 퍼널 구간이다. "
                         "구간 전환율의 기간별 추이는 이 앱이 계산하지 않는다 "
                         "— monthly() 는 지표 셋만 낸다")}
    m = monthly(t)
    if 지표 not in m.columns:
        return {"표": None, "단위": None,
                "사유": f"monthly() 에 '{지표}' 열이 없다"}
    n_q = max(1, round(개월 / 3))
    c = _kpi_base(t)
    c = c[c["_수신일"].notna()]
    q = c["_수신일"].dt.to_period("Q").astype(str)
    분모 = {g: _counts(sub)[지표] for g, sub in c.groupby(q)}
    행 = []
    for g in list(m.index)[-n_q:]:
        n = int(분모.get(g, 0))
        사유 = trust_check({}, n)
        v = m[지표].iloc[m.index.get_loc(g)]
        행.append({"분기": g,
                   "값": (None if pd.isna(v) else round(float(v), 2)),
                   "분모": n, "믿을만": 사유 is None, "사유": 사유})
    return {"표": pd.DataFrame(행), "단위": "분기",
            "요청_개월": 개월, "쓴_분기수": n_q,
            "사유": None}


def topic_evidence(t: dict, topic) -> dict:
    """고른 주제 하나에 대해 **제안서가 쓸 근거를 한 번에 모아 돌려준다.**

    topic 은 proposal_topics() 가 돌려준 dict 이거나 그 "키" 문자열이다.

    돌려주는 것:

        {"주제": <받은 것 그대로>,
         "현황": {"표": 퍼널 전체, "사유": None},
         "원인": {"표": 분해 축, "축", "구간", "비중_분모", "감춘_칸", "사유"},
         "규모": {"실측": {...}, "환산": {...}, "가정": [...], "사유"},
         "추세": {"표": 분기별, "단위": "분기", "사유"}}

    **낼 수 없는 칸은 None 이고, 같은 칸에 사유가 들어 있다.** 지어내지 않는다.
    **실측과 환산은 키가 다르다.** 한 칸에 섞으면 둘 다 실측으로 읽힌다.
    **문장은 만들지 않는다.** 표와 수만 돌려준다.
    """
    키 = topic.get("키") if isinstance(topic, dict) else str(topic)
    종류, _, 값 = str(키 or "").partition(":")

    fe, se = t[C.FUNNEL_TABLE], t[C.TABLES[0]]
    f = funnel(fe)
    S, L = C.FUNNEL_STEPS, C.FUNNEL_LABELS
    bi = max(int(f.index[f.is_bottleneck][0]), 1)

    강조 = None
    원인 = _blank("이 주제는 퍼널 구간이 아니라 지표 값이다. 분해 축이 붙는 자리가 아니다")
    규모 = {"실측": None, "환산": None, "가정": [],
            "사유": "이 주제는 격차를 건수로 환산하는 종류가 아니다"}
    지표 = None

    if 종류 == "구간":
        s_from, s_to = (값.split(">", 1) + [""])[:2]
        if s_from not in S or s_to not in S:
            강조 = None
        else:
            강조 = (s_from, s_to)
            i = S.index(s_to)
            도달 = int(f.n.iloc[i - 1])
            율 = float(f.step_rate.iloc[i]) * 100
            나머지 = sorted(float(f.step_rate.iloc[j]) * 100
                            for j in range(1, len(S)) if j != i)
            다음 = next((x for x in 나머지 if x > 율), None)
            # 원인은 **기본 축**으로 쪼갠다. 어느 축으로 쪼갤지는 config.DIMS[0] 이
            # 이미 정해 두었다(첫 번째가 기본값). 여기서 새로 고르지 않는다.
            원인 = _dim_table(fe, se, C.DIMS[0], s_from, s_to)
            규모 = _size(
                None if 다음 is None else 다음 - 율, 도달,
                round(도달 / int(f.n.iloc[0]) * 100, 2), int(f.n.iloc[0]),
                ["격차는 **다음으로 낮은 구간까지** 좁힌다고 본 값이다. "
                 "전 구간 최고 수준이 아니다",
                 "격차가 전부 메워진다고 본 **상한**이다. 기대치가 아니다",
                 f"기간({C.PERIOD[0]} ~ {C.PERIOD[1]})을 365.25일로 늘려 연율화했다"])

    elif 종류 == "축":
        s_from, s_to = S[bi - 1], S[bi]
        강조 = (s_from, s_to)
        if 값 not in se.columns:
            원인 = _blank(f"'{값}' 열이 검진건 표에 없다")
        else:
            원인 = _dim_table(fe, se, 값, s_from, s_to)
            g = 원인["표"]
            쓸 = g[g["사유"].isna()]
            if len(쓸) >= 2:
                최저 = 쓸.loc[쓸["전환율"].idxmin()]
                최고 = 쓸.loc[쓸["전환율"].idxmax()]
                # 격차는 **표시용으로 반올림한 전환율이 아니라 건수에서** 낸다.
                # 반올림한 값을 빼면 proposal_topics() 와 소수 둘째 자리가 갈리고,
                # 같은 격차가 문서에서 두 값으로 나온다.
                격차 = (int(최고["전환"]) / int(최고["도달"])
                        - int(최저["전환"]) / int(최저["도달"])) * 100
                규모 = _size(
                    격차, int(최저["도달"]),
                    float(최저["비중"]), 원인["비중_분모"],
                    [f"격차는 **최저 칸이 최고 칸({최고[값]}) 수준이 된다**고 본 값이다",
                     "격차가 전부 메워진다고 본 **상한**이다. 기대치가 아니다",
                     f"비중의 분모는 이 구간에 도달한 {원인['비중_분모']:,}건이다 "
                     f"(전체 접수가 아니다)",
                     f"기간({C.PERIOD[0]} ~ {C.PERIOD[1]})을 365.25일로 늘려 연율화했다"]
                    + ([f"감춘 칸 {원인['감춘_칸']}개는 분모에만 들어 있고 "
                        f"격차 계산에는 안 들어갔다"] if 원인["감춘_칸"] else []))
            else:
                규모 = {"실측": None, "환산": None, "가정": [],
                        "사유": 원인["사유"] or "비교할 칸이 모자라다"}

    elif 종류 in ("임계", "추세"):
        지표 = 값

    return {
        "주제": topic,
        "현황": _funnel_now(f, 강조),
        "원인": 원인,
        "규모": 규모,
        "추세": _trend(t, 지표),
    }
