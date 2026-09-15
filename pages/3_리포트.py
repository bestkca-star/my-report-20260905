# -*- coding: utf-8 -*-
"""리포트 — 남에게 보내는 문서.

8장 중 5장은 자동으로 쓰고, **3장(배경·해석·제안)은 사람이 쓴다.**
자동 생성 문장은 인과를 단정하지 않는지 스스로 검사한다.

탭이 둘이다. 「제안서(임시)」는 `제안카드.md` 를 **읽기만 해서** 7장을 그린다 —
카드는 여기서 고치지 않는다. 카드를 고치는 곳은 `/제안` 이다.
"""
import re
from pathlib import Path

import streamlit as st

from core import config as C, gates, load, metrics as M
from core.todo import NotYet
from report import proposal as P, sections as S, to_pdf
from viz import pdf_charts, ui

st.set_page_config(page_title="리포트", page_icon="📄", layout="wide",
                   initial_sidebar_state="expanded")
ui.css()
ui.sidebar_nav("report")

if "run" not in st.session_state:
    st.session_state.run = None
if "human" not in st.session_state:
    st.session_state.human = {}
# 리포트가 쓰는 사람 작성분과 **섞지 않는다.** 장 이름이 겹치지 않더라도
# 두 문서의 사람 작성분은 별개다. 한 곳에 담으면 나중에 어느 문서 것인지 못 가린다.
if "human_prop" not in st.session_state:
    st.session_state.human_prop = {}
ui.context_bar(st.session_state.run)

# ★ 리포트 차트에 쓸 분해 축. 내 데이터의 컬럼명으로 바꾼다.
DIM = C.DIMS[0]      # 분해 축은 config 에서 온다 (지표 정의는 config 에서만 바꾼다)

CARD_FILE = Path(__file__).resolve().parent.parent / "제안카드.md"


# ── 제안카드.md 읽기 — **읽기 전용** ──────────────────────────────
# 여기서 카드를 고치지 않는다. 화면에서 카드를 고칠 수 있게 만들면
# 문서와 카드가 서로 다른 말을 하기 시작하고, 어느 쪽이 원본인지 사라진다.
_CLS = ("하지 말 것", "다시 할 것", "할 것")
_ROW = re.compile(r"^\|(.*)\|\s*$")

# 카드 템플릿에 인쇄돼 있는 **보기 목록.** 고른 값이 아니라 고르라는 안내다.
# 여기 적힌 것과 **글자 그대로 같을 때만** 빈 칸으로 본다.
_TEMPLATE = {
    "하지 말 것 / 다시 할 것 / 할 것",
    "확인됨 / 추정 / 미확인",
    "확인함 / 배제 못 함으로 추가 / 안 받아들임",
}
_PLACEHOLDER = re.compile(r"<[^>]*>")      # "<어떻게>" · "<  >" 같은 빈자리


def _cell(v: str) -> str:
    """표 한 칸. **아직 안 고른 템플릿 자리는 빈 값으로 본다.**

    "확인됨 / 추정 / 미확인" 은 확신도가 셋 중 하나라는 **안내**지 확신도가 아니고,
    "<어떻게>" 도 채운 것이 아니다. 이걸 값으로 읽으면 한 칸도 안 채운 카드가
    화면에서는 다 채워진 것으로 보인다.

    ⚠ **슬래시가 있다고 보기 목록이 아니다.** 처음에 " / " 가 들어 있으면
    템플릿으로 봤더니 근거 세 칸이 통째로 빈 값이 됐다 —
    "비중 25.25%(도달 385 / 구간 도달 합 1,525)" 의 슬래시는 분수다.
    그래서 목록과 **글자 그대로 같은 것**만 걸러낸다.
    """
    s = str(v or "").replace("**", "").strip()
    if not s or s in _TEMPLATE or _PLACEHOLDER.search(s):
        return ""
    return s


def _분류(s: str) -> str:
    """분류 칸에 괄호 설명이 붙어 있어도 분류 이름만 남긴다.

    예) "하지 말 것 (선언한 규칙과 다르게 계산하는 것을 멈춘다)" → "하지 말 것"
    proposal 이 분류를 글자 그대로 맞춰 보므로 여기서 맞춰 두지 않으면
    그 카드만 조용히 어느 장에도 안 실린다.
    """
    for k in _CLS:
        if s.startswith(k):
            return k
    return s


@st.cache_data(show_spinner=False)
def _read_cards(path: str, mtime: float) -> dict:
    """`제안카드.md` → proposal.build() 가 받는 dict. **값을 만들지 않는다.**

    mtime 을 인자로 받는 이유는 캐시 때문이다 — 파일이 바뀌면 다시 읽어야 한다.

    못 읽는 것이 하나 있다. **「크기」(격차 × 비중)는 카드에 숫자 칸이 없다.**
    근거 산문에서 긁으면 조용히 틀리므로(→ proposal.py 맨 위 설명) 안 긁는다.
    그래서 1장의 「발견」·「불확실」 줄은 todo 로 뜬다. 그게 지금 사실이다.
    """
    head = {"대상": "", "작성 시작": "", "최종 갱신": "",
            "카드": [], "카드로 만들지 않은 것": []}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return head

    cur, zone, where = None, "본문", "머리"
    for raw in text.splitlines():
        line = raw.strip()

        m = re.match(r"^##\s+제안\s+(\d+)\s*—\s*(.+)$", line)
        if m:
            cur = {"번호": int(m.group(1)), "제목": m.group(2).strip(),
                   "분류": "", "근거": "", "비용": "", "효과": "", "되돌림": "",
                   "크기": {}, "반증": {}, "받은 반박": {}, "순위": None}
            head["카드"].append(cur)
            zone, where = "본문", "카드"
            continue
        if line.startswith("## "):
            cur = None
            where = "안만든" if "카드로 만들지 않은 것" in line else "기타"
            continue
        if line.startswith("### "):
            zone = line[4:].strip()
            continue

        if where == "머리":
            if line.startswith("대상:"):
                head["대상"] = line.split(":", 1)[1].strip().replace("`", "")
            for k in ("작성 시작", "최종 갱신"):
                mm = re.search(rf"{k}:\s*([0-9][0-9-]+)", line)
                if mm:
                    head[k] = mm.group(1)

        # 반증의 앞 두 줄은 표가 아니라 문장이다.
        if cur is not None and zone == "반증":
            mm = re.match(r"^이 제안이 틀렸다면\s*(.*?)\s*때문일 것이다", line)
            if mm:
                cur["반증"]["가설"] = _cell(mm.group(1))
            mm = re.match(r"^확인하려면\s*(.*?)\s*을 보면 된다", line)
            if mm:
                cur["반증"]["확인 방법"] = _cell(mm.group(1))

        m = _ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if all(set(c) <= set("-: ") for c in cells):     # 구분선
            continue

        if where == "안만든":
            if len(cells) >= 2 and cells[0] != "무엇":
                head["카드로 만들지 않은 것"].append(
                    {"무엇": _cell(cells[0]), "왜": _cell(cells[1])})
            continue
        if cur is None or len(cells) < 2:
            continue

        key, val = cells[0].replace("**", "").strip(), _cell(cells[1])
        if zone == "본문":
            if key == "분류":
                cur["분류"] = _분류(val)
            elif key in ("근거", "비용", "효과", "되돌림"):
                cur[key] = val
        elif zone == "반증":
            if key in ("무엇을 봤는가", "뒤집혔는가", "확신도"):
                cur["반증"][key] = val
        elif zone == "받은 반박":
            if key:
                cur["받은 반박"][key] = val
    return head


def _head(title: str, kind: str, body: str) -> None:
    """장 제목 + auto/human 배지. 두 탭이 같은 방식으로 그린다."""
    라벨 = {"auto": "자동 생성", "human": "사람 작성", "todo": "아직 안 만듦"}[kind]
    lvl = {"auto": "ok", "todo": "none"}.get(
        kind, "ok" if body.strip() else "warn")
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">'
        f'<div style="font-size:19px;font-weight:700">{title}</div>'
        f'{ui.badge(lvl, 라벨)}</div>', unsafe_allow_html=True)


def _auto_body(body: str) -> None:
    """자동 생성 본문 + 인과 단정 검사. 검사는 sections.check_phrasing 하나뿐이다."""
    st.markdown(
        f'<div class="card"><div style="white-space:pre-line;'
        f'font-size:14px;line-height:1.75">{body}</div></div>',
        unsafe_allow_html=True)
    bad = S.check_phrasing(body)
    if bad:
        ui.callout(f"자동 생성 문장에 인과를 단정하는 표현이 있습니다: "
                   f"<b>{', '.join(bad)}</b>. 관측 데이터로는 인과를 "
                   f"주장할 수 없습니다.")
    else:
        st.caption("✓ 인과 단정 표현 검사 통과")


st.markdown('<div style="font-size:24px;font-weight:800;margin-bottom:16px">'
            '리포트</div>', unsafe_allow_html=True)

tab_report, tab_prop = st.tabs(["리포트", "제안서(임시)"])

# ── 탭 1 · 리포트 ─────────────────────────────────────────────────
with tab_report:
    t = ui.guard(load.load_all)
    if t is None:
        # 탭 안에서 st.stop() 을 부르면 **둘째 탭까지 같이 멈춘다.**
        # 제안서는 데이터가 아니라 카드 파일만 읽으므로 여기서 멈추면 안 된다.
        st.caption("데이터를 불러오지 못해 리포트를 조립하지 않았습니다.")
    else:
        secs = S.build(t, st.session_state.human)

        nav, body = st.columns([1, 3.4])

        with nav:
            titles = [s["title"] for s in secs]
            pick = st.radio("목차", titles, label_visibility="collapsed",
                            key="nav_report")
            st.divider()
            done = sum(1 for s in secs if s["kind"] == "human" and s["body"].strip())
            need = sum(1 for s in secs if s["kind"] == "human")
            left = sum(1 for s in secs if s["kind"] == "todo")
            st.caption(f"사람 작성 {done}/{need}장")
            st.progress(done / need if need else 0)
            if left:
                st.caption(f"아직 안 만든 장 {left}개")

        sec = next(s for s in secs if s["title"] == pick)

        with body:
            _head(sec["title"], sec["kind"], sec["body"])

            if sec["kind"] == "todo":
                ui.todo_card(sec["todo"])
            elif sec["kind"] == "auto":
                _auto_body(sec["body"])

                if "funnel" in sec.get("charts", []):
                    f = M.funnel(t[C.FUNNEL_TABLE])
                    st.image(pdf_charts.funnel_png(f), width="stretch")
                if "device" in sec.get("charts", []):
                    f = M.funnel(t[C.FUNNEL_TABLE])
                    bi = max(int(f.index[f.is_bottleneck][0]), 1)
                    g = ui.guard(M.funnel_by, t[C.FUNNEL_TABLE], t["검진건"], DIM,
                                 f.step.iloc[bi - 1], f.step.iloc[bi])
                    if g is not None:
                        st.image(pdf_charts.device_png(g), width="stretch")
                if "experiments" in sec.get("charts", []):
                    res = ui.guard(M.experiment_results, t)
                    if res is not None:
                        st.image(pdf_charts.experiments_png(res), width="stretch")
            else:
                st.caption(sec["placeholder"])
                if sec.get("hint"):
                    ui.callout(sec["hint"], "info")

                # 데이터 기반 가이드 — 화면에만 보인다. 문서에는 안 들어간다.
                gd = S.guide_for(sec["title"], t)
                if gd:
                    with st.expander("작성 가이드 (지금 데이터 기준)", expanded=False):
                        ui.callout(S.GUIDE_NOTE, "warn")
                        for 머리, 항목 in gd.items():
                            쓸 = [x for x in 항목 if x]
                            if not 쓸:
                                continue
                            st.markdown(f"**{머리}**")
                            for x in 쓸:
                                st.markdown(f"- {x}")
                txt = st.text_area("본문", value=sec["body"], height=280,
                                   key=f"h_{sec['title']}",
                                   label_visibility="collapsed")
                if st.button("저장", type="primary", key=f"save_{sec['title']}"):
                    st.session_state.human[sec["title"]] = txt
                    st.rerun()

        # ── 내보내기 ──────────────────────────────────────────────
        st.divider()
        ui.section("내보내기")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**PDF** — 표지 · 목차 · 차트 포함")
            if st.button("PDF 만들기", type="primary"):
                with st.spinner("차트를 그리고 PDF를 조립하는 중..."):
                    # 아직 안 채운 계산은 그 차트만 빼고 조립한다.
                    # build_pdf 가 charts.get() 으로 읽으므로 없는 키는 건너뛴다.
                    f = M.funnel(t[C.FUNNEL_TABLE])
                    bi = max(int(f.index[f.is_bottleneck][0]), 1)
                    charts = {"funnel": pdf_charts.funnel_png(f)}
                    빠짐 = []
                    try:
                        g = M.funnel_by(t[C.FUNNEL_TABLE], t["검진건"], DIM,
                                        f.step.iloc[bi - 1], f.step.iloc[bi])
                        charts["device"] = pdf_charts.device_png(g)
                    except NotYet as e:
                        빠짐.append(f"분해 축 차트 ({e.day})")
                    try:
                        charts["experiments"] = pdf_charts.experiments_png(
                            M.experiment_results(t))
                    except NotYet as e:
                        빠짐.append(f"실험 차트 ({e.day})")
                    pdf = to_pdf.build_pdf(secs, charts)
                st.session_state.pdf = pdf
                st.success(f"생성 완료 · {len(pdf)/1024:.0f}KB")
                if 빠짐:
                    st.caption("아직 안 채운 자리는 빼고 만들었습니다 — "
                               + " · ".join(빠짐))
            if st.session_state.get("pdf"):
                st.download_button("PDF 내려받기", st.session_state.pdf,
                                   file_name=f"성장리포트_{C.PERIOD[0][:7]}.pdf",
                                   mime="application/pdf")

        with c2:
            st.markdown("**이메일 초안** — 실제로 보내지 않습니다")
            draft = S.email_draft(t, secs)
            st.text_input("받는 사람", draft["to"], disabled=True)
            st.text_input("제목", draft["subject"], disabled=True)
            with st.expander("본문 미리보기"):
                st.markdown(draft["html"], unsafe_allow_html=True)

            run = st.session_state.run
            if run and gates.is_passed(run, 2):
                st.markdown('<div class="gate final" style="margin-top:12px">'
                            '<div class="q">게이트 3 · 발송</div>'
                            '<div style="font-size:12.5px;color:#9f1239;'
                            'margin-top:6px"><b>되돌릴 수 없습니다.</b> '
                            '통과시키면 발송 기록이 남습니다.</div>'
                            '</div>', unsafe_allow_html=True)
                if gates.is_passed(run, 3):
                    st.success("게이트 3 통과 기록됨 · 실제 발송은 하지 않았습니다.")
                else:
                    ok = st.text_input('확인 문구로 "발송"을 입력하십시오', key="g3")
                    if st.button("확정", disabled=(ok != "발송")):
                        gates.pass_gate(run, 3, "초안 확정 (실제 발송 없음)")
                        gates.save(run)
                        st.rerun()
            else:
                st.caption("게이트 2를 통과해야 발송 확정 단계가 열립니다.")

# ── 탭 2 · 제안서(임시) ───────────────────────────────────────────
with tab_prop:
    if not CARD_FILE.exists():
        ui.callout(f"제안 카드가 없습니다 — <b>{CARD_FILE.name}</b>. "
                   f"<b>/제안</b> 으로 카드를 먼저 만드십시오. "
                   f"카드 없이 제안서를 조립하지 않습니다.")
        st.stop()

    cards = _read_cards(str(CARD_FILE), CARD_FILE.stat().st_mtime)
    카드들 = cards.get("카드", [])
    psecs = P.build(cards, st.session_state.human_prop)

    st.caption(f"`{CARD_FILE.name}` 을 **읽기만 합니다** — 카드 {len(카드들)}장. "
               f"카드를 고치려면 `/제안` 으로 갑니다. 여기서 고친 것은 "
               f"6장(적용)뿐이고, 카드 파일에는 쓰지 않습니다.")

    막힘 = psecs[0].get("blocks") or []
    if 막힘:
        ui.callout("<b>이 문서를 내보내지 마십시오.</b> 차단 "
                   f"{len(막힘)}건 — " + " / ".join(막힘))

    pnav, pbody = st.columns([1, 3.4])

    with pnav:
        ptitles = [s["title"] for s in psecs]
        ppick = st.radio("목차", ptitles, label_visibility="collapsed",
                         key="nav_prop")
        st.divider()
        pdone = sum(1 for s in psecs
                    if s["kind"] == "human" and s["body"].strip())
        pneed = sum(1 for s in psecs if s["kind"] == "human")
        st.caption(f"사람 작성 {pdone}/{pneed}장")
        st.progress(pdone / pneed if pneed else 0)
        for k in P.CLASSES:
            st.caption(f"{k} {sum(1 for c in 카드들 if c.get('분류') == k)}건")

    psec = next(s for s in psecs if s["title"] == ppick)

    with pbody:
        _head(psec["title"], psec["kind"], psec["body"])

        if psec["kind"] == "auto":
            _auto_body(psec["body"])
            # 「todo」는 카드에 재료가 없다는 뜻이다. 조용히 넘기지 않는다.
            if "todo" in psec["body"]:
                ui.callout("이 장에 <b>todo</b> 가 있습니다 — 카드에 그 재료가 "
                           "아직 없습니다. 화면에서 지어내지 않고 그대로 둡니다.",
                           "info")
        else:
            # 후보 목록 — **읽기 전용.** 위젯이 아니라 마크다운으로 그린다.
            # 입력창에 넣으면 고쳐지고, 고쳐지면 판단기준.md 와 갈라진다.
            고른 = None
            후보 = psec.get("후보")
            if 후보 is not None:
                if 후보:
                    ui.section("이번에 내린 결정",
                               "판단기준.md 에서 그대로 · 고칠 수 없습니다")
                    묶음: dict[str, list[str]] = {}
                    for c in 후보:
                        묶음.setdefault(f"{c['날짜']} · {c['제목']}", []).append(
                            c["문장"])
                    항목 = "".join(
                        f'<div style="font-size:12px;font-weight:700;color:#64748b;'
                        f'margin:10px 0 4px">{머리}</div>'
                        + "".join(f'<div style="font-size:13.5px;line-height:1.7">'
                                  f'· {문장}</div>' for 문장 in 문장들)
                        for 머리, 문장들 in 묶음.items())
                    st.markdown(f'<div class="card">{항목}</div>',
                                unsafe_allow_html=True)
                    고른 = st.multiselect(
                        "이어서 볼 결정을 고르십시오 (고르기만 합니다)",
                        [c["문장"] for c in 후보], default=psec.get("고른") or [],
                        key=f"pick_{psec['title']}")
                else:
                    ui.callout("`판단기준.md` 에서 「오늘 내가 내린 결정」을 "
                               "찾지 못했습니다. 후보 없이 직접 적으십시오.", "info")

            st.caption(psec["placeholder"])
            # 리포트 탭과 같은 방식이다 — hint 는 화면에만 보이고 문서에는 안 들어간다.
            if psec.get("hint"):
                ui.callout(psec["hint"], "info")
            ptxt = st.text_area("본문", value=psec["body"], height=280,
                                key=f"p_{psec['title']}",
                                label_visibility="collapsed")
            if st.button("저장", type="primary", key=f"psave_{psec['title']}"):
                st.session_state.human_prop[psec["title"]] = ptxt
                if 고른 is not None:
                    st.session_state.human_prop[P.PICKED] = 고른
                st.rerun()

    # ── 내보내기 ──────────────────────────────────────────────────
    st.divider()
    ui.section("내보내기", "단일 파일 HTML · 외부 CSS·이미지·CDN 없음")

    if 막힘:
        # 차단이면 문서가 「내보내지 마십시오」로 시작한다. 막지는 않는다 —
        # 무엇이 비었는지 보려고 받아 보는 것까지 막을 이유는 없다.
        ui.callout("차단이 걸린 채로 내보냅니다. 문서 맨 위에 차단 목록이 "
                   "실리고 한 장 요약은 비어 있습니다.")
    p1, p2 = st.columns(2)
    with p1:
        st.markdown("**HTML** — 표지 · 한 장 요약 · 제안 카드 · 부록")
        html = P.to_html(psecs)
        남은 = html.count('class="todo"')
        st.caption(f"안 채운 자리 **{남은}곳**은 `class=\"todo\"` 로 남겨 둡니다 — "
                   f"채우지 않습니다. 브라우저에서 열어 인쇄하면 PDF가 됩니다.")
        st.download_button("제안서.html 내려받기", html.encode("utf-8"),
                           file_name="제안서.html", mime="text/html",
                           type="primary", key="dl_prop_html")

    with p2:
        # 리포트 탭과 같은 패턴이다 — 만들기 버튼이 session_state 에 담고,
        # 내려받기 버튼은 담긴 것이 있을 때만 나온다.
        st.markdown("**PDF** — 표지 · 목차 · 장마다 새 쪽")
        if st.button("PDF 만들기", type="primary", key="mk_prop_pdf"):
            with st.spinner("PDF를 조립하는 중..."):
                st.session_state.prop_pdf = P.build_pdf(psecs)
            st.success(f"생성 완료 · {len(st.session_state.prop_pdf)/1024:.0f}KB")
            안쓴 = [s["title"] for s in psecs
                    if s["kind"] == "human" and not (s["body"] or "").strip()]
            if 안쓴:
                st.caption("사람이 쓰는 장을 아직 안 채웠습니다 — "
                           + " · ".join(안쓴) + ". 빈 채로 넣었습니다.")
        if st.session_state.get("prop_pdf"):
            st.download_button("제안서 PDF 내려받기", st.session_state.prop_pdf,
                               file_name="제안서.pdf", mime="application/pdf",
                               key="dl_prop_pdf")
