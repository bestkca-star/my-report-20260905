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


@st.fragment
def 획득_퍼널(t):
    st.caption(f"[확인용] 이 조각을 그린 시각 {datetime.now():%H:%M:%S}")   # 나중에 지운다
    ms = _months(t)
    lo, hi = st.select_slider("의뢰월 구간", options=ms, value=(ms[0], ms[-1]),
                              key="acq_period")
    fe = _cohort_events(t, lo, hi)
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
            # ★ Day3 — 분해 축. 내 데이터의 컬럼명으로 바꾼다.
            DIMS = ["device", "channel"]
            dim = st.radio("분해 축", DIMS, horizontal=True,
                           label_visibility="collapsed")
            i = st.selectbox(
                "구간", range(len(f) - 1),
                format_func=lambda i: f"{f.label.iloc[i]} → {f.label.iloc[i+1]}",
                index=min(bi - 1, len(f) - 2))
            g = ui.guard(M.funnel_by, t[C.FUNNEL_TABLE], t.get("sessions"), dim,
                         f.step.iloc[i], f.step.iloc[i + 1])
            if g is not None and len(g):
                st.plotly_chart(charts.device_compare(g), width="stretch",
                                config={"displayModeBar": False})
                hi = g.loc[g.전환율.idxmax()]
                lo = g.loc[g.전환율.idxmin()]
                if hi[g.columns[0]] != lo[g.columns[0]]:
                    ui.callout(
                        f"<b>{lo[g.columns[0]]}</b>이(가) 전체의 "
                        f"<b>{lo.비중*100:.1f}%</b>인데 전환율은 "
                        f"<b>{lo.전환율*100:.1f}%</b>로 "
                        f"{hi[g.columns[0]]}({hi.전환율*100:.1f}%)보다 "
                        f"<b>{(hi.전환율-lo.전환율)*100:.1f}%p 낮습니다.</b>")

        # 차트 아래에 표로도 보여준다. 차트는 모양을, 표는 숫자를 읽는 자리다.
        # step_rate·cum_rate 는 funnel() 이 이미 0~1 로 돌려주므로 나누지 않는다.
        st.dataframe(
            f[["label", "n", "step_rate", "cum_rate"]].rename(columns={
                "label": "단계", "n": "도달 수",
                "step_rate": "단계 전환율", "cum_rate": "누적 전환율"}),
            column_config={
                "단계": st.column_config.TextColumn("단계"),
                "도달 수": st.column_config.NumberColumn("도달 수", format="%,d"),
                "단계 전환율": st.column_config.ProgressColumn(
                    # "%.1f%%" 는 100을 곱하지 않아 0.8952 가 "0.9%" 로 뜬다.
                # "percent" 는 곱해서 "89.52%" 로 뜬다.
                "단계 전환율", min_value=0, max_value=1, format="percent"),
                "누적 전환율": st.column_config.ProgressColumn(
                    "누적 전환율", min_value=0, max_value=1, format="percent"),
            },
            hide_index=True, width="stretch")   # use_container_width 는 폐기됐다


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
    획득_퍼널(t)
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
