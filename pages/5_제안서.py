# -*- coding: utf-8 -*-
"""제안서 — 팀장이 읽고 결정하는 문서.

주제를 하나 고르면 그 주제의 근거를 모아 절로 조립한다.
**거르는 자리는 조립기 한 곳뿐이다.** 이 화면은 조립기가 돌려준 것을 그대로 그린다 —
여기서 또 거르면 두 곳이 서로 다르게 거르고, 어느 쪽이 뺀 것인지 못 가린다.
"""
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from core import config as C, load, metrics as M
from report import proposal as P
from viz import ui

st.set_page_config(page_title="제안서", page_icon="📌", layout="wide",
                   initial_sidebar_state="expanded")
ui.css()
ui.sidebar_nav("proposal")

if "run" not in st.session_state:
    st.session_state.run = None
if "human_prop" not in st.session_state:
    st.session_state.human_prop = {}
ui.context_bar(st.session_state.run)

CARD_FILE = Path(__file__).resolve().parent.parent / "제안카드.md"

# ── 제안카드.md 읽기 — **읽기 전용** ──────────────────────────────
# 카드는 여기서 고치지 않는다. 화면에서 고칠 수 있게 만들면 문서와 카드가
# 서로 다른 말을 하기 시작하고, 어느 쪽이 원본인지 사라진다.
_CLS = ("하지 말 것", "다시 할 것", "할 것")
_ROW = re.compile(r"^\|(.*)\|\s*$")
_TEMPLATE = {
    "하지 말 것 / 다시 할 것 / 할 것",
    "확인됨 / 추정 / 미확인",
    "확인함 / 배제 못 함으로 추가 / 안 받아들임",
}
_PLACEHOLDER = re.compile(r"<[^>]*>")


def _cell(v: str) -> str:
    """표 한 칸. 아직 안 고른 템플릿 자리는 빈 값으로 본다.

    ⚠ 슬래시가 있다고 보기 목록이 아니다 — "(도달 385 / 합 1,525)" 의 슬래시는
    분수다. 목록과 **글자 그대로 같은 것**만 걸러낸다.
    """
    s = str(v or "").replace("**", "").strip()
    if not s or s in _TEMPLATE or _PLACEHOLDER.search(s):
        return ""
    return s


def _분류(s: str) -> str:
    for k in _CLS:
        if s.startswith(k):
            return k
    return s


@st.cache_data(show_spinner=False)
def _read_cards(path: str, mtime: float) -> dict:
    """`제안카드.md` → dict. **값을 만들지 않는다.** mtime 은 캐시 무효화용."""
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
        if all(set(c) <= set("-: ") for c in cells):
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


st.markdown('<div style="font-size:24px;font-weight:800;margin-bottom:16px">'
            '제안서</div>', unsafe_allow_html=True)

t = ui.guard(load.load_all)
if t is None:
    st.stop()

topics = ui.guard(M.proposal_topics, t)
if topics is None:
    st.stop()
cards = _read_cards(str(CARD_FILE), CARD_FILE.stat().st_mtime
                    if CARD_FILE.exists() else 0.0)

# ── ① 주제 고르기 ─────────────────────────────────────────────────
# **기각된 후보도 목록에 남긴다.** 지우면 "그건 안 봤다"와 "봤는데 차이가 작다"가
# 같아 보인다. 라벨에 규모를 같이 적어 무엇이 큰 건인지 고르기 전에 보이게 한다.
전체 = "전체"


def _라벨(x: dict) -> str:
    꼬리 = " (차이 없음)" if x["기각사유"] else ""
    return f"{x['제목']} · 연 {x['규모_연간건수']:,.0f}건{꼬리}"


보기 = {전체: None} | {_라벨(x): x for x in topics}
고름 = st.selectbox("주제", list(보기), index=0,
                    help="기각된 후보에는 (차이 없음) 이 붙습니다. 지우지 않습니다.")
topic = 보기[고름]

if topic is None:
    st.caption(f"주제 후보 {len(topics)}건. 하나를 고르면 그 주제로 제안서를 "
               f"조립합니다. 아래 표의 순서는 규모 순이며, "
               f"기각된 것은 맨 뒤입니다.")
    st.dataframe(
        pd.DataFrame([{"제목": x["제목"], "근거축": x["근거축"],
                       "규모(연 건수)": round(x["규모_연간건수"], 1),
                       "구간": x["구간"],
                       "기각사유": x["기각사유"] or ""} for x in topics]),
        width="stretch", hide_index=True)
    st.stop()

# ── ② 근거 요약 한 줄 ─────────────────────────────────────────────
ui.section("근거", topic["근거축"])
st.markdown(f'<div class="card"><div style="font-size:14px;line-height:1.75">'
            f'{topic["한줄"]}</div></div>', unsafe_allow_html=True)
if topic["기각사유"]:
    ui.callout(f"이 후보는 <b>기각</b>되었습니다 — {topic['기각사유']}. "
               f"문서는 그대로 만들어 드리지만, 제안으로 올리기 전에 "
               f"이 사유를 먼저 보십시오.")

evidence = ui.guard(M.topic_evidence, t, topic)
if evidence is None:
    st.stop()

secs = P.build(topic, evidence, cards, st.session_state.human_prop)
못만든 = P.missing(evidence)

# ── ③ 절별 미리보기 ───────────────────────────────────────────────
st.divider()
ui.section("절", f"{len(secs)}개 · 사람이 쓰는 절 "
                 f"{sum(1 for s in secs if s['kind'] == 'human')}개")

if not secs:
    # 빈 화면 대신 왜 없는지 적는다.
    ui.callout("이 주제로는 절이 하나도 만들어지지 않았습니다. "
               + (" / ".join(f"{x['제목']} — {x['사유']}" for x in 못만든)
                  or "근거를 낼 자료가 없습니다."))

for s in secs:
    사람 = s["kind"] == "human"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;'
        f'margin:18px 0 2px">'
        f'<div style="font-size:17px;font-weight:700">{s["제목"]}</div>'
        f'{ui.badge("warn" if 사람 and not s["문장"] else "ok", "사람 작성" if 사람 else "데이터")}'
        f"</div>", unsafe_allow_html=True)
    st.caption(f"이 절이 답하는 질문 — {s['질문']}")
    if s["문장"]:
        st.markdown('<div class="card">'
                    + "".join(f'<div style="font-size:14px;line-height:1.8;'
                              f'margin-bottom:6px">{x}</div>' for x in s["문장"])
                    + "</div>", unsafe_allow_html=True)
    if s.get("자동"):
        # 자동으로 붙인 줄. 사람이 쓴 것과 눈으로 갈리게 한 톤 물러나 그린다.
        st.markdown(
            "".join(f'<div style="font-size:13px;line-height:1.75;color:#64748b;'
                    f'border-left:2px solid #e2e8f0;padding-left:10px;'
                    f'margin:4px 0">{x}</div>' for x in s["자동"]),
            unsafe_allow_html=True)
    if 사람:
        # **문장은 사람이 쓴다.** 여기서 대신 쓰지 않는다.
        글 = st.text_area(f"{s['제목']} — 직접 쓰십시오",
                          value=chr(10).join(s["문장"]), height=150,
                          key=f"h_{s['제목']}", label_visibility="collapsed",
                          placeholder=s["질문"])
        if st.button("저장", key=f"save_{s['제목']}"):
            # 경고는 띄우되 **저장은 막지 않는다.** 쓰다 만 글을 못 저장하게 하면
            # 사람이 화면을 떠나고, 떠나면 영영 안 쓴다.
            st.session_state.human_prop[s["제목"]] = 글
            st.rerun()
    if s["차트"]:
        st.markdown(s["차트"], unsafe_allow_html=True)
    if s["표"] is not None:
        st.dataframe(s["표"], width="stretch", hide_index=True)

# 요청 문장이 결정을 요구하고 있는가. **경고만 한다.**
경고 = P.요청_점검(secs)
if 경고:
    ui.callout(경고)

# 자동으로 쓴 부분에만 인과 단정 검사를 건다. 사람 글에는 걸지 않는다.
for 제목, 낱말 in P.자동_검사(secs):
    ui.callout(f"<b>{제목}</b> 의 자동 문장에 인과를 단정하는 표현이 있습니다: "
               f"<b>{', '.join(낱말)}</b>.")

# 조립기가 못 만든 절은 **조용히 빠뜨리지 않는다.**
if 못만든:
    st.divider()
    ui.section("이 주제로는 만들지 못한 절")
    for x in 못만든:
        st.markdown(f"- **{x['제목']}** — {x['사유']}")

# ── ④ 내려받기 ────────────────────────────────────────────────────
st.divider()
ui.section("내보내기", "단일 파일 HTML · 외부 CSS·이미지·CDN 없음")
html = P.to_html(secs)
안쓴 = [s["제목"] for s in secs if s["kind"] == "human" and not s["문장"]]
if 안쓴:
    st.caption("사람이 쓰는 절이 비어 있습니다 — " + " · ".join(안쓴)
               + ". 비운 채로 넣고, 문서에도 안 썼다고 적습니다.")
st.download_button("제안서.html 내려받기", html.encode("utf-8"),
                   file_name="제안서.html", mime="text/html",
                   type="primary", key="dl_prop_html")
