# -*- coding: utf-8 -*-
"""대시보드 — 여기서 발견이 일어난다.

반복해서 보는 화면이므로 실행 절차를 지나치지 않고 바로 지표에 닿게 한다.

이 화면은 Day2~3에 걸쳐 살아난다.
  Day2  지표 카드 · 획득 퍼널 · 유지 퍼널
  Day3  분해 · 실험 카드
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from core import config as C, load, metrics as M
from viz import charts, ui

st.set_page_config(page_title="대시보드", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")
ui.css()
ui.sidebar_nav("dash")

if "run" not in st.session_state:
    st.session_state.run = None
ui.context_bar(st.session_state.run)

t = ui.guard(load.load_all)
if t is None:
    st.stop()

st.markdown('<div style="font-size:24px;font-weight:800;margin-bottom:16px">'
            '대시보드</div>', unsafe_allow_html=True)
st.caption(f"[확인용] 페이지 전체를 그린 시각 {datetime.now():%H:%M:%S}")   # 나중에 지운다

# ── 지표 카드 ─────────────────────────────────────────────────────
# delta 방향. "낮을수록 좋은" 지표는 inverse (오르면 빨강).
#   심사유의율은 **양방향**이다 — 낮아지는 것도 높아지는 것도 판정 운영이
#   흔들렸다는 신호다. 방향으로 좋고 나쁨을 말할 수 없으므로 off(회색)로 둔다.
DELTA_COLOR = {
    "심사유의율": "off",
    "경계선 비율": "inverse",
    "재작업률": "inverse",
}
LEVEL_KO = {"ok": "정상", "warn": "경고", "block": "위험"}


def _delta(m, name):
    """직전 기간 대비 변화. 어느 한쪽이라도 없으면 내지 않는다.

    비어 있는 기간을 건너뛰고 비교하면 카드마다 비교 기간이 달라진다.
    그러면 나란히 놓인 세 숫자가 서로 다른 것을 말하게 된다.
    """
    if m is None or name not in getattr(m, "columns", []) or len(m) < 2:
        return None, ""
    a, b = m[name].iloc[-2], m[name].iloc[-1]
    span = f"{m.index[-2]} → {m.index[-1]}"
    if pd.isna(a) or pd.isna(b):
        빈칸 = m.index[-1] if pd.isna(b) else m.index[-2]
        return None, f"{빈칸} 값이 없어 변화를 내지 않습니다"
    return b - a, span


def _guide(name, lv):
    """경고선과 현재 판정. st.metric 이 임계값 색을 못 쓰므로 글로 남긴다."""
    th = C.THRESHOLDS.get(name)
    if not th:
        return f"경고선 미정 / 현재 {LEVEL_KO[lv]} — 임계값이 없어 항상 정상으로 뜹니다"
    선 = []
    if "경고" in th:
        선.append(f"{th['경고']:.0f}% 미만")
    if "경고_상한" in th:
        선.append(f"{th['경고_상한']:.0f}% 초과")
    return f"경고선 {' 또는 '.join(선)} / 현재 {LEVEL_KO[lv]}"


k = ui.guard(M.kpis, t)
if k:
    m = ui.guard(M.monthly, t)
    cols = st.columns(len(k))
    for col, (name, v) in zip(cols, k.items()):
        with col:
            lv = M.status_of(name, v["value"])
            delta, span = _delta(m, name)
            st.metric(
                label=name,
                value=v["fmt"].format(v["value"]),
                delta=None if delta is None else f"{delta:+.2f}%p",
                delta_color=DELTA_COLOR.get(name, "normal"),
                border=True,
            )
            with st.popover("정의"):
                st.markdown(f"**{name}**")
                st.caption(C.METRIC_DEFS.get(name, "정의 미기재"))
            st.caption(_guide(name, lv))
            if span:
                st.caption(span)
            # 추이가 있으면 스파크라인. 지표 이름과 열 이름이 같아야 그려진다.
            if m is not None and name in getattr(m, "columns", []):
                st.plotly_chart(
                    charts.spark(m[name], C.COLORS[lv] if lv != "ok" else None),
                    width="stretch", config={"displayModeBar": False},
                    key=f"sp_{name}")
    st.caption("⚠ 심사유의율의 **위쪽 경고선(43%·47%)은 아직 판정에 반영되지 않습니다** — "
               "status_of() 가 한쪽만 봅니다. 44%도 48%도 정상으로 뜹니다.")

@st.dialog("이 값을 왜 보여주지 않나")
def 감춘이유(칸, 사유, 도달, 비중, dim):
    """조건 값만 보여준다. 지표 값·증감·p값은 넣지 않는다."""
    st.markdown(f"**{dim} · {칸}**")
    st.table(pd.DataFrame([
        {"항목": "걸린 조건", "값": "표본이 모자란다" if "표본" in 사유
                                else ("기간이 안 찼다" if "관측" in 사유 else "비교가 공정하지 않다")},
        {"항목": "사유", "값": 사유},
        {"항목": "표본 수", "값": f"{도달:,}건 (최소 {C.MIN_SAMPLE:,}건)"},
        {"항목": "이 구간에서의 비중", "값": f"{비중*100:.1f}%"},
    ]).set_index("항목"))
    부족 = C.MIN_SAMPLE - 도달
    # 이 데이터는 12개월치다. 지금 속도로 부족분을 채우는 데 걸리는 날.
    일 = 부족 / max(도달, 1) * 365
    st.info(f"**무엇을 하면 믿을 수 있나** — 이 칸에 **{부족:,}건**이 더 쌓이면 "
            f"판정할 수 있습니다. 지금 속도(12개월에 {도달:,}건)면 약 **{일:.0f}일** "
            f"뒤입니다. 기다릴 수 없으면 축을 더 굵게 묶으십시오 "
            f"(예: 기관을 권역으로).")
    st.caption("전환율·증감은 계산하지 않았으므로 여기에도 없습니다.")


# ── 판정 카드 ─────────────────────────────────────────────────────
ui.section("전후 비교", "실험이 없으므로 전후로 대신한다 — 인과는 주장하지 않는다")
카드들 = ui.guard(M.judge_pairs, t)
for k in (카드들 or []):
    col = C.COLORS.get(k["색"], "#94a3b8")
    h = (f'<div class="card" style="border-left:4px solid {col};margin-bottom:10px">'
         f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
         f'<div><div style="font-size:11px;color:#64748b;letter-spacing:.3px">'
         f'{k["앞"]} → {k["뒤"]}</div>'
         f'<div style="font-size:16px;font-weight:800;margin-top:2px">'
         f'{k["앞"]} 수신분 대비 {k["뒤"]} 수신분</div>'
         f'<div style="font-size:12px;color:#64748b;margin-top:6px">'
         f'모수 {k["모수"][0]:,}건 → {k["모수"][1]:,}건</div></div>'
         f'<div>{ui.badge(k["색"], k["판정"])}</div></div>')

    if "주지표" in k:
        j = k["주지표"]
        h += (f'<div style="font-size:30px;font-weight:800;margin-top:10px">'
              f'{j["변화"]:+.2f}%p</div>'
              f'<div style="font-size:12px;color:#64748b;margin-top:2px">'
              f'{j["이름"]} {j["앞"]:.2f}% → {j["뒤"]:.2f}% (움직임 기준 {j["기준"]:.0f}%p)</div>'
              f'<hr style="border:0;border-top:1px dashed #e2e8f0;margin:12px 0">')
        for g in k["가드레일"]:
            if g.get("확인불가"):
                h += (f'<div style="font-size:12.5px;color:#64748b">가드레일 {g["이름"]} '
                      f'— 관측 창이 안 닫혀 <b>확인할 수 없음</b></div>')
            else:
                c2 = C.COLORS["warn"] if g["악화"] else "#64748b"
                h += (f'<div style="font-size:12.5px;color:{c2}">가드레일 {g["이름"]} '
                      f'{g["앞"]:.2f}% → {g["뒤"]:.2f}% ({g["변화"]:+.2f}%p, '
                      f'악화 기준 {g["기준"]:.0f}%p)</div>')
    else:
        # 못 믿을 조건에 걸린 카드 — 사유만. 지표 값은 계산하지 않았으므로 없다.
        h += (f'<div class="blocked" style="margin-top:10px">'
              f'<b>{k["사유"]}</b><br>{k["설명"]}</div>')

    # 교안 p14 — 이 문장은 카드 **안**에 넣는다. 각주로 빼면 아무도 안 읽는다.
    h += (f'<div style="font-size:12px;color:{C.COLORS["block"]};margin-top:10px">'
          f'{k["인과"]}</div></div>')
    st.markdown(h, unsafe_allow_html=True)

    with st.status("판정 과정", expanded=False) as box:
        if "주지표" in k:
            st.write(f"✓ **못 믿을 조건 확인** — 양쪽 분기 모두 표본 "
                     f"{min(k['모수']):,}건 이상 · 통과")
            j = k["주지표"]; 움직 = abs(j["변화"]) >= j["기준"]
            st.write(f"{'✓' if 움직 else '✕'} **주지표 · {j['이름']}** — "
                     f"{j['앞']:.2f}% → {j['뒤']:.2f}% ({j['변화']:+.2f}%p)")
            if not 움직:
                st.write("— **가드레일** — 주지표가 안 움직여 판정에 쓰지 않음")
            else:
                for g in k["가드레일"]:
                    st.write(("— " if g.get("확인불가") else ("✕ " if g["악화"] else "✓ "))
                             + f"**가드레일 · {g['이름']}** — "
                             + ("관측 창이 안 닫혀 확인할 수 없음" if g.get("확인불가")
                                else f"{g['변화']:+.2f}%p"))
        else:
            st.write(f"✕ **못 믿을 조건 확인** — {k['사유']}")
            st.write("— **주지표** — 계산하지 않음")
            st.write("— **가드레일** — 계산하지 않음")
        box.update(label=f"판정 과정 · {k['판정']}",
                   state="error" if k["색"] == "block" else "complete")

# ── 퍼널 (탭) ─────────────────────────────────────────────────────
def _cohort_events(t, lo, hi):
    """의뢰월이 [lo, hi] 안인 검진 건의 이벤트만 남긴다.

    **이벤트 일자가 아니라 의뢰월로 자른다.** 일자로 자르면 접수는 구간 안이고
    수신은 밖인 건이 통째로 빠져 전환율이 실제보다 낮게 나온다.
    계산 경로이므로 현재 시각을 쓰지 않는다 — 같은 입력이면 같은 결과여야 한다.
    """
    c = t["검진건"]
    월 = pd.to_datetime(c[C.DATE_COLS["검진건"]]).dt.to_period("M").astype(str)
    ids = set(c.loc[(월 >= lo) & (월 <= hi), C.EVENT_ID_COL])
    fe = t[C.FUNNEL_TABLE]
    return fe[fe[C.EVENT_ID_COL].isin(ids)]


def _months(t):
    월 = pd.to_datetime(t["검진건"][C.DATE_COLS["검진건"]]).dt.to_period("M")
    return sorted(월.astype(str).unique())


def _qp(키, 후보, 기본):
    """URL 에서 읽되, 없거나 이상한 값이면 기본값으로 떨어진다. 에러를 내지 않는다."""
    v = st.query_params.get(키)
    return v if v in 후보 else 기본


# 필터는 fragment **밖**에 둔다. 조각 안에서 query_params 를 갱신하면
# 조각만 다시 그려져 URL 과 화면이 어긋난다.
ms = _months(t)
_축 = _qp("axis", C.DIMS, C.DIMS[0])
_lo = _qp("from", ms, ms[0])
_hi = _qp("to", ms, ms[-1])
if _lo > _hi:
    _lo, _hi = ms[0], ms[-1]

축 = st.segmented_control("분해 축", C.DIMS, default=_축, key="axis_sel") or _축
lo, hi = st.select_slider("의뢰월 구간", options=ms, value=(_lo, _hi), key="period_sel")
st.query_params.update({"axis": 축, "from": lo, "to": hi})
st.code(f"?axis={축}&from={lo}&to={hi}", language=None)
st.caption("현재 화면 링크 — 주소창 뒤에 붙이면 같은 화면이 열립니다.")


@st.fragment
def 획득_퍼널(t, 축, 시작월, 끝월):
    st.caption(f"[확인용] 이 조각을 그린 시각 {datetime.now():%H:%M:%S}")   # 나중에 지운다
    fe = _cohort_events(t, 시작월, 끝월)
    if not len(fe):
        st.info("그 구간에 해당하는 건이 없습니다.")
        return
    f = ui.guard(M.funnel, fe)
    if f is not None:
        left, right = st.columns([1.15, 1])
        with left:
            st.plotly_chart(charts.funnel_bars(f), width="stretch",
                            config={"displayModeBar": False})
            bn = f[f.is_bottleneck].iloc[0]
            bi = max(int(f.index[f.label == bn.label][0]), 1)
            prev = f.iloc[bi - 1]
            ui.callout(
                f"<b>병목은 {prev.label} → {bn.label}</b> 구간입니다. "
                f"{prev.n:,} 중 {bn.n:,}만 넘어가 "
                f"<b>{(1-bn.step_rate)*100:.1f}%가 이탈</b>합니다.")

        with right:
            # 분해 축. 방문진단군을 기본으로 둔다 — 4칸 모두 최소표본을 넘고
            # 격차가 24.8%p로 유일하게 유의하다(p=1.27e-11). 지역 자체는 못 바꾸지만
            # 배차·인력 배분은 바꿀 수 있다. 나머지 둘은 눌러 볼 수는 있게 남긴다.
            dim = 축
            i = st.selectbox(
                "구간", range(len(f) - 1),
                format_func=lambda i: f"{f.label.iloc[i]} → {f.label.iloc[i+1]}",
                index=min(bi - 1, len(f) - 2))
            g = ui.guard(M.funnel_by, t[C.FUNNEL_TABLE], t["검진건"], dim,
                         f.step.iloc[i], f.step.iloc[i + 1])
            if g is not None and len(g):
                믿음 = g[g.사유.isna()]
                감춤 = g[g.사유.notna()]

                # 믿을 수 있는 칸만 그린다. 걸린 칸은 값이 아예 없다(계산하지 않았다).
                if len(믿음):
                    st.plotly_chart(charts.device_compare(믿음), width="stretch",
                                    config={"displayModeBar": False})
                    최고 = 믿음.loc[믿음.전환율.idxmax()]
                    최저 = 믿음.loc[믿음.전환율.idxmin()]
                    if 최고[dim] != 최저[dim]:
                        ui.callout(
                            f"<b>{최저[dim]}</b>이(가) 전체의 "
                            f"<b>{최저.비중*100:.1f}%</b>인데 전환율은 "
                            f"<b>{최저.전환율*100:.1f}%</b>로 "
                            f"{최고[dim]}({최고.전환율*100:.1f}%)보다 "
                            f"<b>{(최고.전환율-최저.전환율)*100:.1f}%p 낮습니다.</b>")
                else:
                    ui.callout("믿을 수 있는 칸이 없습니다. 이 축으로는 판정하지 않습니다.")

                # 감춘 칸 — 사유만 적는다. 지표 값은 적지 않는다.
                for _, r in 감춤.iterrows():
                    st.markdown(
                        f'<div class="card tight" style="margin-bottom:2px">'
                        f'<b>{r[dim]}</b> {ui.badge("block", "판정 보류")}'
                        f'<div style="font-size:12.5px;color:#64748b;margin-top:4px">'
                        f'{r.사유} · 이 구간 도달의 {r.비중*100:.1f}%</div></div>',
                        unsafe_allow_html=True)
                    if st.button("왜 감췄나", key=f"why_{dim}_{r[dim]}"):
                        감춘이유(r[dim], r.사유, int(r.도달), float(r.비중), dim)
                if len(감춤):
                    st.caption(f"{len(감춤)}칸을 감췄습니다 — 표본이 모자라 전환율을 "
                               f"**계산하지 않았습니다.**")


@st.fragment
def 유지_퍼널(t):
    st.caption(f"[확인용] 이 조각을 그린 시각 {datetime.now():%H:%M:%S}")   # 나중에 지운다
    if not C.RETENTION_STEPS:
        st.caption("config.RETENTION_STEPS 가 비어 있습니다. "
                   "7주차에 정한 유지·이탈의 정의를 옮기면 여기에 그려집니다.")
    rf = ui.guard(M.retention_funnel, t)
    if rf is not None and len(rf):
        if "is_bottleneck" not in rf.columns:
            rf = rf.assign(is_bottleneck=False)
        c1, c2 = st.columns([1.15, 1])
        with c1:
            st.plotly_chart(charts.funnel_bars(rf), width="stretch",
                            config={"displayModeBar": False})
        with c2:
            ui.callout(
                "유지는 <b>관측 기간이 대상마다 다릅니다.</b> "
                "먼저 들어온 대상은 오래 관측됐고 나중에 들어온 대상은 짧게 관측됐습니다. "
                "<b>누적값으로 비교하면 기간의 그림자를 효과로 착각합니다.</b> "
                "비율(단위 기간당)로 바꾸거나 같은 시점에 시작한 것끼리 묶으십시오.",
                "info")


tab1, tab2 = st.tabs(["획득 퍼널", "유지 퍼널"])
with tab1:
    ui.section("획득 퍼널", "그레인을 먼저 확인한다")
    획득_퍼널(t, 축, lo, hi)
with tab2:
    ui.section("유지 퍼널", "데려온 대상이 남는가")
    유지_퍼널(t)

# ── 실험 ──────────────────────────────────────────────────────────
ui.section("실험 결과", "믿을 수 있는지 먼저 보고, 그 다음에 지표를 본다")
res = ui.guard(M.experiment_results, t)
if res is not None and not res:
    st.caption("실험이 없습니다. 전후 비교로 대신하되 "
               "**인과를 주장할 수 없다**를 카드에 남기십시오.")
for r in (res or []):
    cls = r["color"]
    head = (f'<div class="exp {cls}">'
            f'<div style="display:flex;align-items:flex-start;gap:12px">'
            f'<div style="flex:1"><div class="id">{r["id"]}</div>'
            f'<div class="nm">{r["name"]}</div>'
            f'<div class="hy">{r["hypothesis"]}</div></div>'
            f'<div>{ui.badge(cls, r["verdict"])}</div></div>')

    if r["verdict"] == "무효":
        # 못 믿을 실험의 숫자는 보여주지 않는다.
        # 계산해 놓고 숨기는 것이 아니라 계산 자체를 하지 않았다.
        head += (f'<div class="blocked"><b>✕ 지표를 표시하지 않습니다</b><br>'
                 f'{r["reason"]}</div>')
        st.markdown(head + "</div>", unsafe_allow_html=True)
        continue

    if "rc" not in r:
        head += (f'<div style="margin-top:12px;font-size:13px;color:#64748b">'
                 f'{r.get("reason", "")}</div>')
        st.markdown(head + "</div>", unsafe_allow_html=True)
        continue

    head += (f'<div style="margin-top:14px;display:flex;gap:28px;'
             f'align-items:baseline;flex-wrap:wrap">'
             f'<div><div style="font-size:11px;color:#64748b">{r["primary"]}</div>'
             f'<div class="mv">{r["rc"]*100:.2f}% → {r["rt"]*100:.2f}%</div></div>'
             f'<div><div style="font-size:11px;color:#64748b">상대 효과</div>'
             f'<div class="mv">{r["lift"]*100:+.1f}%</div></div>'
             f'<div><div style="font-size:11px;color:#64748b">p값</div>'
             f'<div class="mv">{r["p"]:.4f}</div></div>'
             f'<div><div style="font-size:11px;color:#64748b">표본</div>'
             f'<div style="font-size:13px;color:#475569" class="num">'
             f'{r["nc"]:,} / {r["nt"]:,}</div></div></div>')
    st.markdown(head + "</div>", unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1.1])
    with c1:
        st.caption("효과 크기와 95% 신뢰구간 (0을 지나면 유의하지 않음)")
        st.plotly_chart(charts.forest(r), width="stretch",
                        config={"displayModeBar": False}, key=f"fr_{r['id']}")
    with c2:
        if r.get("guard"):
            gd = r["guard"]
            bad = gd["delta"] < -0.03
            st.markdown(
                f'<div class="card tight" style="border-color:'
                f'{C.COLORS["warn"] if bad else C.BRAND["line"]}">'
                f'<div style="font-size:11px;color:#64748b">가드레일 · {gd["name"]}</div>'
                f'<div style="font-size:20px;font-weight:700;margin-top:4px" class="num">'
                f'{gd["control"]*100:.1f}% → {gd["treatment"]*100:.1f}% '
                f'<span style="color:{C.COLORS["warn"] if bad else C.COLORS["ok"]}">'
                f'({gd["delta"]*100:+.1f}%p)</span></div>'
                + ('<div class="note">주지표는 개선됐지만 가드레일이 무너졌습니다.</div>'
                   if bad else
                   '<div style="font-size:12px;color:#64748b;margin-top:6px">'
                   '이상 없음</div>')
                + '</div>', unsafe_allow_html=True)
        elif r.get("reason"):
            st.markdown(f'<div class="card tight">'
                        f'<div style="font-size:13px;color:#64748b">{r["reason"]}</div>'
                        f'</div>', unsafe_allow_html=True)

    # 기간을 쪼개야 드러나는 것 — 초기 효과가 남아 있는가
    w = M.weekly_effect(r, r["start"])
    if not w.empty and len(w) >= 3:
        with st.expander("기간을 쪼개서 보기 — 효과가 유지되는가"):
            st.plotly_chart(charts.effect_decay(w), width="stretch",
                            config={"displayModeBar": False})
            ui.callout(
                f"전체 평균은 <b>{r['lift']*100:+.1f}%</b>인데 "
                f"초반 <b>{w.lift.iloc[0]*100:+.0f}%</b>에서 "
                f"후반 <b>{w.lift.iloc[-1]*100:+.0f}%</b>로 갑니다. "
                f"기간 평균만 보면 안 보이는 것입니다.")

    # 그때 멈췄다면 무엇을 봤을까
    pc = M.peeking_curve(r, r["start"])
    if not pc.empty and len(pc) >= 3:
        with st.expander("만약 여기서 멈췄다면? — 조기 중단 시뮬레이터"):
            cuts = list(pc.cut.astype(int))
            sel = st.select_slider("실험 종료일", options=cuts, value=cuts[0],
                                   key=f"peek_{r['id']}")
            row = pc[pc.cut == sel].iloc[0]
            a, b = st.columns([1, 1.4])
            with a:
                lv = "warn" if row.sig else "none"
                st.markdown(
                    ui.kpi_card(f"{sel}일차에 종료했다면", f"{row.lift*100:+.1f}%",
                                "유의 — 성공으로 보고" if row.sig
                                else "유의하지 않음", lv),
                    unsafe_allow_html=True)
                st.caption(f"p = {row.p:.3f}")
            with b:
                st.plotly_chart(charts.peeking(pc, r["lift"]), width="stretch",
                                config={"displayModeBar": False})
            ui.callout("종료 시점은 실험을 **시작하기 전에** 정해야 합니다.")

# ── 채널 효율 (선택 과제) ─────────────────────────────────────────
ui.section("획득 경로 효율", "비용만 보면 순위가 뒤집힌다")
ce = ui.guard(M.channel_efficiency, t)
if ce is not None and len(ce):
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.plotly_chart(charts.cac_compare(ce), width="stretch",
                        config={"displayModeBar": False})
    with c2:
        naive = list(ce.sort_values("CAC").channel)
        real = list(ce.sort_values("유효CAC").channel)
        st.markdown(
            f'<div class="card tight">'
            f'<div style="font-size:12px;color:#64748b">단순 비용 순위</div>'
            f'<div style="font-size:14px;margin:4px 0 12px">{" < ".join(naive)}</div>'
            f'<div style="font-size:12px;color:#64748b">유지율 반영 순위</div>'
            f'<div style="font-size:14px;font-weight:700;color:{C.COLORS["block"]}">'
            f'{" < ".join(real)}</div></div>', unsafe_allow_html=True)
        st.caption("비용은 가정값입니다. 리포트에 쓸 때 '가정값 기반'을 남기십시오.")
