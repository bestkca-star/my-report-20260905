# -*- coding: utf-8 -*-
"""검증.

검증은 **자동으로 통과시키지 않는다.** 결과를 사람 앞에 놓고 게이트에서 판단하게 한다.
경고를 앱이 마음대로 무시하면, 사람은 무엇을 승인했는지 모른 채 승인하게 된다.

판정 3종:

  ok    통과
  warn  경고 — **정상일 수도 있다. 사람이 판단한다.**
  block 차단 — 이 상태로는 분석할 수 없다.

────────────────────────────────────────────────────────────────────
차단과 경고를 가르는 것은 한 질문이다.

    이 규칙이 깨진 채로 계산하면 값이 틀리는가?
        틀린다              → block
        해석만 조심하면 된다 → warn

차단을 늘리면 안전해 보이지만, 실무 데이터는 늘 어딘가 깨져 있어서
앱이 아무것도 못 돌리게 된다. **차단은 "이대로 계산하면 확실히 틀리는 것"에만 건다.**
────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import pandas as pd

from core import config as C
from core.load import to_dt
from core.todo import todo


def _r(name, level, msg, detail=""):
    """검증 결과 한 줄. 그대로 쓴다."""
    return {"name": name, "level": level, "msg": msg, "detail": detail}


def profile(t: dict) -> pd.DataFrame:
    """적재 직후 개요. 게이트 1에서 사람이 보는 화면.

    **그대로 쓴다.** 어느 도메인이든 행수·컬럼·기간·결측은 먼저 본다.
    """
    rows = []
    for name, df in t.items():
        date_col = getattr(C, "DATE_COLS", {}).get(name) or next(
            (c for c in df.columns
             if c.endswith("_date") or c == "year_month"), None)
        span = ""
        if date_col is not None:
            s = df[date_col].astype(str)
            span = f"{s.min()} ~ {s.max()}"
        rows.append({
            "테이블": name, "행수": len(df), "컬럼": df.shape[1],
            "기간": span,
            "결측 컬럼": int(df.isna().any().sum()),
            "메모리(MB)": round(df.memory_usage(deep=True).sum() / 1e6, 1),
        })
    return pd.DataFrame(rows)


def run_checks(t: dict) -> list[dict]:
    """정합성 검증. 결과는 게이트 1에서 사람에게 보여준다.

    ★ Day1 실습 D에서 채웁니다. **규칙 3건**을 직접 씁니다.

        1. 행 수      — 비어 있거나 예상보다 크게 다르면?
        2. 필수 컬럼  — 계산에 꼭 필요한 컬럼이 있는가?
        3. 날짜 범위  — config.PERIOD 를 벗어난 데이터가 있는가?

    각 규칙마다 물어라: **이게 깨지면 계산이 틀리는가, 해석만 조심하면 되는가.**
    그 답이 block 과 warn 을 가른다.

    아래 reference_checks_telecom() 에 통신사에서 쓴 12건이 그대로 있다.
    읽어보고 **내 데이터에 맞는 것만** 가져다 고쳐 쓴다. 대부분은 안 맞는다.

    다 쓰고 나면 **정상 파일을 일부러 망가뜨려 넣어 본다.**
    컬럼 하나를 지우거나 날짜를 한 해 옮긴다. 차단이 뜨고 게이트 버튼이
    비활성되는 것까지 눈으로 봐야 한다.
    **경고만 띄우고 진행되면 그 검증은 없는 것과 같다.**

    반환: [_r(이름, 레벨, 메시지, 상세), ...]
    """
    out = []
    사례, 이벤트 = t.get("검진건"), t.get("검진이벤트")

    # 1. 행 수 — 차단
    #    근거: 명세 4행의 최소표본이 분기 200건이다. 그 밑에서는 심사유의율을
    #          내도 신뢰구간이 너무 넓어 판정에 쓸 수 없다.
    적음 = [f"{n} {len(df):,}행" for n, df in t.items() if len(df) < C.MIN_SAMPLE]
    out.append(_r("행 수", "block" if 적음 else "ok",
                  f"표본 부족: {', '.join(적음)} (최소 {C.MIN_SAMPLE:,})" if 적음 else
                  " · ".join(f"{n} {len(df):,}행" for n, df in t.items())
                  + f" — 모두 최소 {C.MIN_SAMPLE:,}행 이상",
                  "이 밑으로는 비율을 내도 못 믿는다." if 적음 else ""))

    # 2. 필수 컬럼 — 차단
    #    근거: 하나만 없어도 주지표(심사유의율)나 퍼널 중 하나가 아예 안 나온다.
    #          없어도 되는 컬럼(검사수치·연령대 등)과는 구분한다.
    필수 = {"검진건": ["검진건ID", "의뢰일", "심사유의여부"],
            "검진이벤트": ["검진건ID", "일자", "단계"]}
    빠짐 = [f"{tbl}.{c}" for tbl, cols in 필수.items() if tbl in t
            for c in cols if c not in t[tbl].columns]
    out.append(_r("필수 컬럼", "block" if 빠짐 else "ok",
                  f"없는 컬럼 {len(빠짐)}개: {', '.join(빠짐)}" if 빠짐 else
                  f"필수 {sum(len(v) for v in 필수.values())}개 컬럼 모두 있음",
                  "심사유의율 또는 퍼널을 계산할 수 없다." if 빠짐 else ""))

    # 3. 날짜 범위 — 방향으로 가른다
    #    뒤로 넘어감  -> 경고. 수행·수신은 의뢰보다 나중에 일어나므로 구조적 정상이다.
    #                        차단하면 앱이 늘 멈춘다.
    #    앞으로 벗어남 -> 차단. 검진은 의뢰보다 먼저 일어날 수 없고, 기간 시작 이전
    #                        데이터가 이 파일에 있을 이유가 없다. 지난 연도 파일이다.
    lo, hi = pd.Timestamp(C.PERIOD[0]), pd.Timestamp(C.PERIOD[1])
    앞, 뒤 = [], []
    for tbl, col in C.DATE_COLS.items():
        if tbl not in t or col not in t[tbl].columns:
            continue
        d = to_dt(t[tbl][col])
        n앞, n뒤 = int((d < lo).sum()), int((d > hi).sum())
        if n앞:
            앞.append(f"{tbl}.{col} {n앞:,}행 ({n앞/len(d)*100:.1f}%), 최소 {d.min().date()}")
        if n뒤:
            뒤.append(f"{tbl}.{col} {n뒤:,}행 ({n뒤/len(d)*100:.1f}%), 최대 {d.max().date()}")
    if 앞:
        lv, msg = "block", f"기간({C.PERIOD[0]}) 이전 데이터 — " + " · ".join(앞)
        det = "검진은 의뢰보다 먼저 일어날 수 없다. 지난 연도 파일을 올렸는지 확인하십시오."
    elif 뒤:
        lv, msg = "warn", f"기간({C.PERIOD[1]}) 이후 — " + " · ".join(뒤)
        det = ("후속 단계 일자가 의뢰 기간보다 뒤인 것은 정상이다. 다만 기간을 잘라 "
               "집계할 때 이 행들이 어디로 가는지 알고 있어야 한다.")
    else:
        lv, msg, det = "ok", f"모든 날짜가 {C.PERIOD[0]} ~ {C.PERIOD[1]} 안에 있습니다", ""
    out.append(_r("날짜 범위", lv, msg, det))

    # 4. 조인 안전성(중복) — 경고
    #    근거: 인원을 COUNT(DISTINCT 검진건ID)로 세면 값이 맞는다. 구현만 조심하면
    #          되므로 경고다. 다만 행으로 세면 분모가 부풀어 전환율이 전부 틀어진다.
    if 이벤트 is not None:
        dup = int(이벤트.duplicated().sum())
        행 = 이벤트.groupby("단계", observed=True)["검진건ID"].agg(["count", "nunique"])
        차 = ", ".join(f"{s} {r['count']:,}행/{r['nunique']:,}건"
                       for s, r in 행.iterrows() if r["count"] != r["nunique"])
        out.append(_r("조인 안전성(중복)", "warn" if dup else "ok",
                      f"검진이벤트 완전중복 {dup:,}행 ({dup/len(이벤트)*100:.1f}%) — {차}"
                      if dup else "중복 없음",
                      "인원은 반드시 COUNT(DISTINCT 검진건ID)로 센다. "
                      "행으로 세면 분모가 부풀어 전환율이 전부 틀어진다." if dup else ""))

    return out


def summarize(checks: list[dict]) -> dict:
    """통과·경고·차단을 센다. 차단이 하나라도 있으면 게이트를 못 넘는다.

    **그대로 쓴다.**
    """
    n = {"ok": 0, "warn": 0, "block": 0}
    for c in checks:
        n[c["level"]] += 1
    return {**n, "total": len(checks), "can_pass": n["block"] == 0}


# ══════════════════════════════════════════════════════════════════
# 참고 — 통신사 데이터에서 쓴 검증 12건
#
# **이 함수는 호출되지 않는다.** 읽고 필요한 것만 위 run_checks() 로 옮긴다.
# 대부분은 통신사 테이블·컬럼에 묶여 있어서 그대로는 안 돌아간다.
#
# 눈여겨볼 것은 규칙 자체가 아니라 **무엇을 block 으로 두고 무엇을 warn 으로
# 뒀는가**이다.
#
#   block  기간 정합성 · 퍼널 순서 · 신규 고객 일치 · 배정 중복 ·
#          중도절단 · 참조 무결성        ← 깨지면 계산이 틀린다
#   warn   월 커버리지 · 결측률 2건 · 응답률 · 표본 수 · 배정 균형
#                                        ← 정상일 수도 있다. 사람이 판단한다
# ══════════════════════════════════════════════════════════════════
def reference_checks_telecom(t: dict) -> list[dict]:
    out = []
    lo, hi = pd.Timestamp(C.PERIOD[0]), pd.Timestamp(C.PERIOD[1])
    cu, se, fe = t["customers"], t["sessions"], t["funnel_events"]
    um, asg, ad = t["usage_monthly"], t["experiment_assignments"], t["ad_spend"]

    # 1. 기간 — 기간이 어긋나면 조인에 구멍이 생긴다
    bad = []
    for label, s in [("sessions", se.session_date), ("funnel_events", fe.event_date),
                     ("ad_spend", ad.spend_date)]:
        d = to_dt(s)
        if d.min() < lo or d.max() > hi:
            bad.append(f"{label} {d.min().date()}~{d.max().date()}")
    out.append(_r("기간 정합성", "block" if bad else "ok",
                  "기간을 벗어난 테이블이 있습니다" if bad else
                  f"모든 테이블이 {C.PERIOD[0]} ~ {C.PERIOD[1]} 안에 있습니다",
                  "; ".join(bad)))

    # 2. 월 커버리지 — 빠진 달이 있어도 정상일 수 있다
    m = sorted(um.year_month.astype(str).unique())
    out.append(_r("월 커버리지", "ok" if len(m) == 12 else "warn",
                  f"{m[0]} ~ {m[-1]} ({len(m)}개월)"))

    # 3. 퍼널 역행 — 앞 단계를 안 거치고 뒤 단계에 온 대상
    piv = (fe.pivot_table(index="visitor_id", columns="step_order",
                          values="event_id", aggfunc="count").fillna(0) > 0)
    cols = sorted(piv.columns)
    viol = sum(int(((~piv[a]) & piv[b]).sum()) for a, b in zip(cols, cols[1:]))
    out.append(_r("퍼널 순서", "block" if viol else "ok",
                  f"단계 역행 {viol}건" if viol else "단계 역행 없음"))

    # 4. 신규 고객 = 최종 통과자
    paid = set(fe.loc[fe.funnel_step == C.FUNNEL_STEPS[-1], "visitor_id"])
    newc = set(cu.loc[cu.visitor_id.notna(), "visitor_id"])
    out.append(_r("신규 고객 일치", "ok" if newc == paid else "block",
                  f"신규 {len(newc):,}명 / 최종 통과 {len(paid):,}명"))

    # 5. 실험 배정 중복 — 한 대상이 두 번 배정되면 결과를 못 믿는다
    dup = int(asg.duplicated(["experiment_id", "visitor_id"]).sum())
    out.append(_r("배정 중복", "block" if dup else "ok",
                  f"중복 {dup}건" if dup else "중복 없음"))

    # 6. 중도절단 — 떠난 뒤의 기록이 있으면 데이터가 잘못됐다
    ch = cu[cu.is_churned][["customer_id", "churn_date"]].copy()
    ch["cm"] = to_dt(ch.churn_date).dt.strftime("%Y-%m")
    mg = um.merge(ch, on="customer_id", how="inner")
    after = int((mg.year_month.astype(str) > mg.cm).sum())
    out.append(_r("중도절단", "block" if after else "ok",
                  f"이탈 이후 사용 기록 {after}건" if after else
                  "이탈 이후 사용 기록 없음"))

    # 7. 참조 무결성 — 끊어진 참조가 있으면 조인에서 조용히 사라진다
    fk_bad = []
    if not set(um.customer_id) <= set(cu.customer_id):
        fk_bad.append("usage_monthly")
    if not set(fe.session_id) <= set(se.session_id):
        fk_bad.append("funnel_events")
    out.append(_r("참조 무결성", "block" if fk_bad else "ok",
                  f"끊어진 참조: {', '.join(fk_bad)}" if fk_bad else "모든 참조 정상"))

    # 8. 결측 — 경고로만 낸다. **구조적 결측은 오류가 아니다.**
    nn = int(cu.visitor_id.isna().sum())
    if nn:
        out.append(_r("visitor_id 결측", "warn",
                      f"고객 {len(cu):,}명 중 {nn:,}명({nn/len(cu)*100:.0f}%)이 "
                      f"퍼널 이력이 없습니다",
                      "기존 고객은 이번 기간 퍼널을 거치지 않았으므로 정상일 수 있습니다. "
                      "다만 퍼널 테이블과 INNER JOIN하면 이 인원이 전부 사라집니다."))

    # 9. 캠페인 결측 — 자연 유입은 캠페인이 없다
    cn = int(se.campaign_id.isna().sum())
    if cn:
        out.append(_r("campaign_id 결측", "warn",
                      f"세션 {len(se):,}건 중 {cn:,}건({cn/len(se)*100:.0f}%)에 "
                      f"캠페인이 없습니다",
                      "자연 유입(검색·직접 방문)은 캠페인이 없으므로 정상일 수 있습니다."))

    # 10. 응답률 — 응답자 평균은 전체 평균이 아니다
    st_ = t["support_tickets"]
    resp = st_.satisfaction_score.notna().mean()
    if resp < 0.5:
        out.append(_r("만족도 응답률", "warn",
                      f"응답률 {resp*100:.1f}% — 응답자 평균은 전체 만족도가 아닙니다",
                      "극단적 경험을 한 쪽이 더 많이 응답하는 경향이 있습니다. "
                      "이 경고는 리포트 7장 한계로 옮깁니다."))

    # 11. 표본 크기
    small = []
    for _, e in t["experiments"].iterrows():
        n = int((asg.experiment_id == e.experiment_id).sum())
        if n < C.MIN_SAMPLE:
            small.append(f"{e.experiment_id}({n:,})")
    out.append(_r("실험 표본", "warn" if small else "ok",
                  f"표본 부족: {', '.join(small)}" if small else
                  "모든 실험이 최소 표본을 넘습니다"))

    # 12. SRM — 실험 결과를 보기 전에 반드시 확인
    from core.metrics import srm_check
    broken = []
    for _, e in t["experiments"].iterrows():
        s = srm_check(asg, e.experiment_id)
        if not s["ok"]:
            broken.append(f"{e.experiment_id} ({s['ratio'][0]*100:.1f}:"
                          f"{s['ratio'][1]*100:.1f}, p={s['p']:.1e})")
    out.append(_r("실험 배정 균형(SRM)", "warn" if broken else "ok",
                  f"배정이 깨진 실험: {', '.join(broken)}" if broken else
                  "모든 실험의 배정이 균형입니다",
                  "배정이 깨진 실험은 어떤 효과가 나와도 해석할 수 없습니다. "
                  "결과를 쓰지 말고 재실험해야 합니다." if broken else ""))

    return out
