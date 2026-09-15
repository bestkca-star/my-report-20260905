# -*- coding: utf-8 -*-
"""제안서 7장 조립.

────────────────────────────────────────────────────────────────────
자동인 장과 사람인 장은 sections.py 와 같은 질문으로 가른다 —
**이 문장이 틀렸을 때 누가 책임지는가.**

    카드에 있는 것을 옮길 뿐  → 자동으로 쓴다
                               (1 한 장 요약 · 2 하지 말 것 ·
                                3 다시 할 것 · 4 할 것 · 7 부록)
    사람이 책임진다            → 사람이 쓴다 (5 이 제안이 틀린다면 · 6 적용)

**여기서 새로 제안하지 않는다.** 카드에 없는 제안은 만들지 않고, 카드에 없는 숫자는
쓰지 않는다. 이 파일이 하는 일은 `제안카드.md` 를 문서 순서로 다시 놓는 것뿐이다.

그리고 **순서를 대신 매기지 않는다.** 카드에 `순위` 가 없으면 파일에 적힌 차례
그대로 두고, "이것은 순서가 아니다"를 그 장 안에 적는다(각주로 빼면 아무도 안 읽는다).
────────────────────────────────────────────────────────────────────

cards 의 모양 — `제안카드.md` 를 파싱해 넣는다.

    {
      "대상": "my-report (방문검진_심사유의 · run 20260903-203951)",
      "작성 시작": "2026-09-15",
      "최종 갱신": "2026-09-15",
      "조회": {"일시": "2026-09-15 16:55:11",           # 발견.md 머리말 그대로
               "표본": "검진 건 2,004건 · 구간 도달 1,525건"},
      "카드": [
        {
          "번호":   1,
          "제목":   "표본 200 미달 분기(2025Q3)를 추이 화면에서 뺀다",
          "분류":   "하지 말 것" | "다시 할 것" | "할 것",
          "근거":   "...",      # 분자·분모 실제 건수 · 비교 대상 · 비중
          "비용":   "...",      # 또는 "미확인 — ..."
          "효과":   "...",      # 실측 / 추정(가정 명시) / 미확인
          "되돌림": "...",
          "크기":   {"격차": 24.75, "비중": 0.1580,      # 1장 「발견」이 이것만 읽는다
                     "분모": "구간 도달 1,525건",         # **분모를 반드시 함께 적는다**
                     "건수": 59.7},                       # 절대 건수 환산(있으면)
          "반증":      {"가설": "", "확인 방법": "", "무엇을 봤는가": "",
                        "뒤집혔는가": "", "확신도": ""},
          "받은 반박": {"무엇을 지적받았나": "", "어떻게 처리했나": "",
                        "안 받아들였다면 왜": "", "확신도가 바뀌었나": ""},
          "순위":   None,       # 사람이 매겼으면 1부터. 없으면 None
        }, ...
      ],
      "카드로 만들지 않은 것": [{"무엇": "...", "왜": "..."}, ...],
    }

`카드` 대신 리스트를 그대로 넘겨도 받는다 — 파서가 아직 껍데기를 안 씌운 경우다.

**`크기` 는 산문에서 긁지 않는다.** 근거 문장 안의 "격차 ...%p" 와 "비중 ...%" 를
정규식으로 뽑으면 조용히 틀린다 — 한 근거에 격차가 두 번 나오거나(자른 값과 안 자른 값),
비중의 분모가 그 카드에서만 다른 경우가 있어서, 뽑아 놓고 보면 그 카드에 존재하지도
않는 크기가 나온다. **틀린 숫자보다 없는 숫자가 낫다.** 파서가 `크기` 를 채워 주기
전까지 1장의 「발견」·「불확실」 줄은 `todo` 로 남는다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# ★ 인과 단정 검사는 sections.py 것을 **그대로 쓴다.**
#   여기서 BANNED 를 새로 만들면 두 목록이 반드시 어긋난다.
#   리포트에서 막은 표현이 제안서에서는 통과하는 일이 생긴다.
from report.sections import BANNED, check_phrasing  # noqa: F401  (재수출)

NL = "\n"

# 분류 순서는 고정이다. **"하지 말 것"이 맨 앞이다.**
# 사람은 "할 것"을 먼저 읽기 시작하면 거기서 멈추고, 멈추는 제안은 영영 안 읽힌다.
CLASSES = ["하지 말 것", "다시 할 것", "할 것"]

CLASS_NOTE = {
    "하지 말 것": "지금 하고 있는데 근거가 없거나 해로운 것이다. **멈추는 것이 가장 싸다.**",
    "다시 할 것": "판정이 무효였거나 표본이 모자라 아직 결론을 못 내는 것이다. "
                  "여기 있는 것을 「할 것」으로 옮기려면 먼저 재야 한다.",
    "할 것": "근거가 있고 효과를 추정할 수 있는 것이다. "
             "**추정의 가정이 안 적힌 것은 여기 있으면 안 된다.**",
}

GUIDE_NOTE = ("이 문서는 **카드를 옮긴 것일 뿐입니다.** 카드에 없는 제안·숫자는 "
              "여기에도 없습니다. 빈 칸은 비운 채로 둡니다 — 채우면 지어낸 것이 됩니다.")

# 6장이 고른 결정을 담는 자리. 사람이 쓴 글(`"6. 적용"`)과 **따로** 둔다 —
# 한 칸에 합쳐 두면 다시 열었을 때 고른 목록까지 편집 대상이 되어 버린다.
PICKED = "6. 적용 · 고른 결정"

# ── 판단기준.md 의 「오늘 내가 내린 결정」 ─────────────────────────
DECISIONS_FILE = Path(__file__).resolve().parent.parent / "판단기준.md"

_DEC_HEAD = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})[^·]*·\s*(.+)$")
_DEC_ROW = re.compile(r"^\|(.*)\|\s*$")


def read_decisions(path: str | Path | None = None, recent: int = 2) -> list[dict]:
    """`판단기준.md` 의 「오늘 내가 내린 결정」 표에서 문장을 뽑는다. **읽기만 한다.**

    돌려주는 것: [{"날짜", "제목", "문장"}, ...] — `recent` 개 항목(## 블록)까지만.

    **여기서 문장을 다듬지 않는다.** 표에 적힌 두 칸을 "A → B" 로 잇기만 한다.
    다듬기 시작하면 판단기준에 적은 말과 제안서에 실린 말이 달라지고,
    나중에 어느 쪽이 내가 정한 것인지 못 가린다.
    """
    p = Path(path or DECISIONS_FILE)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []

    블록, 날짜, 제목, 안에 = [], "", "", False
    for raw in text.splitlines():
        line = raw.strip()

        m = _DEC_HEAD.match(line)
        if m:
            날짜, 제목 = m.group(1), m.group(2).strip()
            블록.append({"날짜": 날짜, "제목": 제목, "문장": []})
            안에 = False
            continue
        if line.startswith("## "):
            안에 = False
            continue
        if line.startswith("### "):
            안에 = line[4:].strip() == "오늘 내가 내린 결정"
            continue
        if not (안에 and 블록):
            continue

        m = _DEC_ROW.match(line)
        if not m:
            continue
        cells = [c.replace("**", "").strip() for c in m.group(1).split("|")]
        if len(cells) < 2 or all(set(c) <= set("-: ") for c in cells):
            continue
        # 표 머리(규칙/판정/왜 · 결정/무엇으로/왜)는 결정이 아니다.
        if cells[0] in ("규칙", "결정") or not cells[0] or not cells[1]:
            continue
        블록[-1]["문장"].append(f"{cells[0]} → {cells[1]}")

    찬것 = [b for b in 블록 if b["문장"]]
    return [{"날짜": b["날짜"], "제목": b["제목"], "문장": s}
            for b in 찬것[-recent:] for s in b["문장"]]


# ── 카드 읽기 ─────────────────────────────────────────────────────
def _cards(cards) -> list[dict]:
    """껍데기가 있으면 벗기고, 리스트로 왔으면 그대로 쓴다."""
    if isinstance(cards, dict):
        return list(cards.get("카드") or [])
    return list(cards or [])


def _비었(v) -> bool:
    return not str(v or "").strip()


def _미확인(v) -> bool:
    """이 칸이 아직 안 채워졌는가.

    **"미확인"이라는 글자가 있다고 전부 빈 칸은 아니다.** 실측값을 적고 그 옆에
    "추정치는 미확인"이라고 덧붙인 칸은 채워진 것이다 — 오히려 정직한 칸이다.
    실측이 하나도 없이 미확인만 있는 칸을 빈 칸으로 본다.
    """
    s = str(v or "").strip()
    if not s:
        return True
    if "실측" in s:
        return False
    return s.startswith("미확인") or "미확인" in s


def _빈칸(c: dict) -> list[str]:
    return [k for k in ("근거", "비용", "효과", "되돌림") if _미확인(c.get(k))]


def _번호(c: dict) -> str:
    n = c.get("번호")
    return f"제안 {n}" if n is not None else "제안 <번호 없음>"


def _of(카드들: list[dict], 분류: str) -> list[dict]:
    """한 분류의 카드. **순위가 있으면 그 순서, 없으면 파일에 적힌 차례 그대로.**"""
    골라낸 = [c for c in 카드들 if str(c.get("분류", "")).strip() == 분류]
    if all(c.get("순위") is not None for c in 골라낸) and 골라낸:
        return sorted(골라낸, key=lambda c: c["순위"])
    return 골라낸


def _순위_매겨졌나(카드들: list[dict]) -> bool:
    return bool(카드들) and all(c.get("순위") is not None for c in 카드들)


# ── 크기 ──────────────────────────────────────────────────────────
def _크기(c: dict) -> dict | None:
    """격차 × 비중. **카드가 구조화해서 준 것만 읽는다.** 근거 산문은 안 긁는다.

    값이 없으면 `격차 × 비중` 으로 센다 — 여기서 새로 계산하는 것이 아니라
    카드에 적힌 두 수를 곱할 뿐이다. 둘 중 하나라도 없으면 크기도 없다.
    """
    z = c.get("크기") or {}
    격차, 비중 = z.get("격차"), z.get("비중")
    if 격차 is None or 비중 is None:
        return None
    return {"값": z.get("값", 격차 * 비중), "격차": 격차, "비중": 비중,
            "분모": z.get("분모"), "건수": z.get("건수")}


def _가장_큰(카드들: list[dict]) -> tuple[dict, dict] | None:
    """크기가 가장 큰 카드 하나. 크기를 가진 카드가 없으면 None."""
    있는 = [(c, z) for c in 카드들 if (z := _크기(c))]
    return max(있는, key=lambda x: x[1]["값"]) if 있는 else None


def _크기_문구(z: dict) -> str:
    """**분모를 반드시 함께 적는다.** 비중의 분모는 카드마다 다르다 —
    구간 도달인지 전체 이탈인지 전체 접수인지 모르면 크기끼리 비교할 수 없다.
    """
    분모 = f", 분모 {z['분모']}" if z.get("분모") else ", 분모 <안 적힘>"
    건수 = f" · 절대 건수 {z['건수']:,.1f}건" if z.get("건수") is not None else ""
    return (f"크기 {z['값']:.2f} (격차 {z['격차']:.2f}%p × "
            f"비중 {z['비중'] * 100:.2f}%{분모}){건수}")


def _확신도(c: dict) -> str:
    return str((c.get("반증") or {}).get("확신도", "") or "").strip()


def _흔들리나(c: dict) -> bool:
    """확신도가 낮거나 못 채운 칸이 있는가. 「확인됨」만 흔들리지 않는 것으로 본다."""
    return _확신도(c) != "확인됨" or bool(_빈칸(c))


# ── 차단 검사 ─────────────────────────────────────────────────────
def _blocks(카드들: list[dict]) -> list[str]:
    """제안.md §4 의 차단 조건. **걸리면 문서를 내보내지 않는다.**

    build() 는 여기서 나온 것을 1장 맨 위에 적는다. 조용히 빼지 않는다 —
    빠진 것을 모르면 다 갖춰진 문서로 읽힌다.

    §4-4(감춰진 항목을 근거로 썼는가)는 **여기서 못 가린다.** 글자만 봐서는
    "표본 190건이라 감췄다"와 "표본 190건이니 이걸 근거로 쓰자"가 같아 보인다.
    카드를 쓴 사람이 지켜야 하고, 7장 부록에 근거 원문을 그대로 실어 두는 것으로
    읽는 사람이 직접 볼 수 있게 한다.
    """
    막힘 = []
    for c in 카드들:
        if _비었(c.get("근거")):
            막힘.append(f"{_번호(c)} — 근거 칸이 비었다. "
                        f"데이터에서 조회해 채운다. 옮겨 적는 것은 조회가 아니다.")
    if not _of(카드들, "하지 말 것"):
        막힘.append('"하지 말 것"이 한 건도 없다 — 무엇을 멈출지 안 정한 것이고, '
                    '그것은 선택을 안 한 것이다.')
    for c in _of(카드들, "할 것"):
        if _미확인(c.get("효과")):
            막힘.append(f"{_번호(c)} — 효과가 미확인인데 「할 것」에 있다. "
                        f"「다시 할 것」으로 옮기거나 효과를 조회한다.")
    return 막힘


# ── 카드 한 장을 문단으로 ─────────────────────────────────────────
def _card_body(c: dict) -> str:
    줄 = [f"### {_번호(c)} — {c.get('제목', '<제목 없음>')}", ""]
    for 칸 in ("근거", "비용", "효과", "되돌림"):
        v = str(c.get(칸, "") or "").strip()
        줄.append(f"- **{칸}** — {v if v else '<비어 있음>'}")

    확신도 = str((c.get("반증") or {}).get("확신도", "") or "").strip()
    줄.append(f"- **확신도** — {확신도 if 확신도 else '<아직 안 적음>'}")

    빈 = _빈칸(c)
    if 빈:
        # 빈 칸을 지우지 않는다. 무엇이 남았는지 보여야 한다.
        줄.append(f"- ⚠ 아직 못 채운 칸: {' · '.join(빈)}")
    return NL.join(줄)


# ── 자동으로 쓰는 장 ──────────────────────────────────────────────
def _l1_발견(카드들: list[dict]) -> str:
    """가장 큰 근거 하나. **분모를 함께 적는다.**"""
    큰 = _가장_큰(카드들)
    if not 큰:
        return ("todo: 카드에 「크기」가 없다. "
                "격차·비중·분모를 카드에 적어야 이 줄이 채워진다. "
                "근거 산문에서 긁지 않는다.")
    c, z = 큰
    return f"{_번호(c)} 「{c.get('제목', '')}」 · {_크기_문구(z)}."


def _l2_제안(카드들: list[dict]) -> str:
    """제목만 나열한다. **본문(2·3·4장)과 같은 순서다.**

    여기서 고르지도, 순서를 바꾸지도 않는다 — 요약이 본문과 다른 순서를 보이면
    읽는 사람은 요약 쪽을 우선순위로 읽는다.
    """
    덩이 = []
    for k in CLASSES:
        골라낸 = _of(카드들, k)
        덩이.append(f"{k}: "
                    + (" · ".join(str(c.get("제목", "<제목 없음>")) for c in 골라낸)
                       if 골라낸 else "없음"))
    꼬리 = "" if _순위_매겨졌나(카드들) else " (이 차례는 순서가 아니다)"
    return " / ".join(덩이) + 꼬리 + "."


def _l3_불확실(카드들: list[dict]) -> str:
    """흔들리는 것 중 가장 큰 것 하나. 여러 개면 제일 큰 것만 — 넷을 넘길 수 없다."""
    흔들 = [c for c in 카드들 if _흔들리나(c)]
    if not 흔들:
        return "없음. 모든 카드가 확신도 「확인됨」이고 빈 칸이 없다."
    큰 = _가장_큰(흔들)
    if not 큰:
        return (f"todo: 흔들리는 카드 {len(흔들)}건 중 크기가 적힌 것이 없어 "
                f"어느 것이 가장 큰지 못 고른다. 카드에 「크기」를 적는다.")
    c, z = 큰
    확신도 = _확신도(c) or "안 적음"
    빈 = _빈칸(c)
    사유 = f"확신도 {확신도}" + (f" · 못 채운 칸 {'·'.join(빈)}" if 빈 else "")
    return (f"{_번호(c)} 「{c.get('제목', '')}」 ({사유}) · "
            f"{_크기_문구(z)}. 흔들리는 카드는 모두 {len(흔들)}건.")


def _l4_근거(cards) -> str:
    """어디서 조회한 값인가. **상세는 부록으로 보낸다** — 요약에 다 적으면 요약이 아니다."""
    조회 = (cards.get("조회") if isinstance(cards, dict) else None) or {}
    일시, 표본 = 조회.get("일시"), 조회.get("표본")
    if not 일시 and not 표본:
        return ("todo: 카드에 「조회」가 없다. "
                "`발견.md` 머리말의 조회 일시와 표본을 옮긴다. 상세는 부록.")
    # 표본 값 안에 가운뎃점이 들어 있는 경우가 많아(예 "2,004건 · 도달 1,525건")
    # 줄의 구분자와 섞인다. 값은 「」로 묶어 어디까지가 표본인지 보이게 한다.
    return (f"조회 {일시 or '<일시 todo>'} · "
            f"표본 「{표본 or '<표본 todo>'}」 · 상세는 부록.")


def _s1_summary(cards, 카드들: list[dict]) -> dict:
    """1. 한 장 요약 — **발견 · 제안 · 불확실 · 근거 넉 줄이다.**

    ★ 다섯째 줄을 만들지 않는다. 다섯째 줄이 생겼으면 잘못 조립한 것이다.
      대상·갱신일·건수 같은 것은 여기 있을 자리가 아니다 — 부록으로 간다.

    **카드에 없는 문장은 만들지 않는다.** 재료가 없으면 그 줄에 `todo` 를 적는다.
    빈 줄로 두면 읽는 사람은 "없다"가 아니라 "해당 없다"로 읽는다.

    차단이 걸리면 넉 줄을 아예 조립하지 않는다. 내보내면 안 되는 문서를
    말끔한 넉 줄로 요약해 주면, 그 넉 줄만 읽고 나가는 사람이 생긴다.
    """
    막힘 = _blocks(카드들)
    조회 = (cards.get("조회") if isinstance(cards, dict) else None) or {}
    메타 = {"대상": (cards.get("대상") if isinstance(cards, dict) else "") or "",
            "갱신": (cards.get("최종 갱신") if isinstance(cards, dict) else "") or "",
            "일시": 조회.get("일시", ""), "표본": 조회.get("표본", ""),
            "차단": len(막힘)}

    if 막힘:
        본문 = NL.join([f"**이 문서를 내보내지 마십시오. 차단 {len(막힘)}건을 "
                        f"먼저 보십시오.** 요약은 조립하지 않았습니다."]
                       + [f"- {m}" for m in 막힘])
        # 요약은 None 이다. **빈 dict 로 두지 않는다** — 네 줄이 다 비어 있는 것과
        # 애초에 조립하지 않은 것은 다르고, to_html 이 그 둘을 다르게 그려야 한다.
        return {"title": "1. 한 장 요약", "kind": "auto", "body": 본문,
                "blocks": 막힘, "요약": None, "메타": 메타}

    # 넷이다. 늘리지 않는다.
    요약 = {"발견": _l1_발견(카드들), "제안": _l2_제안(카드들),
            "불확실": _l3_불확실(카드들), "근거": _l4_근거(cards)}
    줄 = [f"**{k}** — {v}" for k, v in 요약.items()]
    return {"title": "1. 한 장 요약", "kind": "auto", "body": NL.join(줄),
            "blocks": 막힘, "요약": 요약, "메타": 메타}


def _s_class(분류: str, 번호: int, 카드들: list[dict]) -> dict:
    """2·3·4장 — 분류 하나를 그대로 옮긴다.

    **값을 다시 계산하지 않는다.** 카드에 적힌 근거를 그대로 싣는다.
    카드가 틀렸으면 카드를 고치는 것이지 여기서 보정하지 않는다.
    """
    골라낸 = _of(카드들, 분류)
    줄 = [CLASS_NOTE[분류], ""]
    if not 골라낸:
        # "없음"도 결과다. 장을 통째로 빼면 없다는 사실까지 사라진다.
        줄.append(f"**{분류}: 0건.** 없는 것이 아니라 아직 안 뽑은 것일 수 있다.")
        if 분류 == "하지 말 것":
            줄.append("근거를 대고 하고 있는 것이 몇 개이고, "
                      "관성으로 하고 있는 것이 몇 개인지부터 센다.")
    else:
        줄 += [_card_body(c) for c in 골라낸]
        if not _순위_매겨졌나(골라낸):
            줄 += ["", "위 차례는 **순서가 아니다.** 카드 파일에 적힌 순서 그대로다."]
    return {"title": f"{번호}. {분류}", "kind": "auto", "body": (NL * 2).join(줄),
            "분류": 분류, "카드": 골라낸}


def _s5_falsify(human: dict, 카드들: list[dict]) -> dict:
    """5. 이 제안이 틀린다면 — **자동으로 쓰지 않는다.**

    **문서 전체에 하나다. 카드마다가 아니다.** 카드마다 반증을 늘어놓으면
    여덟 번 변명하는 문서가 되고, 읽는 사람은 어느 것이 진짜 약한 곳인지 못 고른다.
    제안을 낸 사람이 **문서 전체를 걸고** 한 번 쓴다.

    내가 틀렸을 수 있는 지점은 사실 진술이 아니라 판단이다 — 틀렸을 때
    책임지는 것도 쓴 사람이다. 그래서 여기는 사람이 쓴다.

    카드의 반증 칸은 **재료로만 넘긴다**(hint). 문서 본문에 자동으로 싣지 않는다.
    """
    적은 = [c for c in 카드들 if str((c.get("반증") or {}).get("가설", "") or "").strip()]
    hint = None
    if 적은:
        # 화면에서 참고하라고 주는 것이지 문서에 들어가는 글이 아니다.
        hint = ("카드에 적힌 반증 — " + " / ".join(
            f"{_번호(c)} {(c.get('반증') or {}).get('가설', '')}" for c in 적은)
            + f" (반증을 안 적은 카드 {len(카드들) - len(적은)}건)")
    return {
        "title": "5. 이 제안이 틀린다면", "kind": "human",
        "body": (human or {}).get("5. 이 제안이 틀린다면", ""),
        "placeholder": ("이 제안이 틀렸다면 무엇 때문인지, "
                        "확인하려면 무엇을 보면 되는지 적으십시오."),
        "hint": hint,
    }


def _s7_appendix(cards, 카드들: list[dict]) -> dict:
    """7. 부록 — 근거 상세.

    **근거 원문을 자르지 않고 그대로 싣는다.** 읽는 사람이 분자·분모를 다시 세어
    볼 수 있어야 하고, 감춰진 항목이 근거로 쓰였는지도 여기서만 눈에 띈다.
    """
    줄 = []
    for c in 카드들:
        줄.append(f"**{_번호(c)} · {c.get('분류', '')}** — {c.get('제목', '')}"
                  + NL + f"근거: {c.get('근거', '') or '<없음>'}")

    안만든 = (cards.get("카드로 만들지 않은 것") if isinstance(cards, dict) else None) or []
    if 안만든:
        줄.append("**카드로 만들지 않은 것** — 뺀 것이 아니라 왜 안 만들었는지를 남긴다.")
        줄 += [f"- {x.get('무엇', '')} — {x.get('왜', '')}" for x in 안만든]

    # 자동으로 쓴 장에 인과 단정이 섞였는지 스스로 검사한다.
    섞임 = check_phrasing(NL.join(str(c.get("근거", "")) for c in 카드들))
    if 섞임:
        줄.append(f"⚠ **근거 문장에 인과를 단정하는 표현이 있다** — {' · '.join(섞임)}. "
                  f"관측 데이터로는 인과를 주장할 수 없다. 카드를 고친다.")

    줄.append(f"자동 생성 · {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
              f"근거는 `제안카드.md` 에서 옮긴 것이며 여기서 다시 계산하지 않았다.")
    return {"title": "7. 부록 — 근거 상세", "kind": "auto",
            "body": (NL * 2).join(줄), "카드": 카드들, "안만든": 안만든}


# ── 사람이 쓰는 장 ────────────────────────────────────────────────
def _s6_apply(human: dict, 카드들: list[dict], 후보: list[dict]) -> dict:
    """6. 적용 — **자동으로 쓰지 않는다.** 후보만 자동으로 내놓는다.

    `판단기준.md` 에 이번에 내린 결정이 이미 적혀 있다. 그것을 후보로 **먼저 보여주고**,
    그 아래에 사람이 "다음에 무엇을 볼 것인가"를 쓴다.

    **후보 목록은 편집 대상이 아니다.** 그래서 `body` 에 넣지 않는다 —
    body 는 입력창에 그대로 들어가고, 들어간 것은 고쳐진다. 고쳐진 순간
    판단기준에 적은 말과 제안서에 실린 말이 갈라지고, 어느 쪽이 내가 정한 것인지
    알 수 없게 된다. 그래서 후보는 `"후보"` 키로 따로 내보내 읽기 전용으로 그린다.

        "후보"  자동 · 읽기 전용 · 판단기준.md 에서 그대로
        "고른"  사람 · 후보 중에서 **고르기만** 한다 (글자를 못 바꾼다)
        "body"  사람 · 다음에 무엇을 볼 것인가

    고르는 것과 쓰는 것이 사람 몫이고, 목록을 만드는 것만 자동이다.
    """
    남은 = [_번호(c) for c in 카드들 if _빈칸(c)]
    안내 = ("다음에 무엇을 볼 것인지 적으십시오. 위 목록은 이번에 내린 결정이며 "
            "**고르기만 할 수 있고 고칠 수 없습니다.** "
            "**자동으로 쓰지 않습니다 — 선택은 사람의 책임입니다.**")
    if 남은:
        안내 += (f" 아직 칸이 빈 카드({' · '.join(남은)})를 위에 올리려면 "
                 f"그 칸부터 채워야 합니다.")

    문장들 = [c["문장"] for c in 후보]
    고른 = [s for s in (human or {}).get(PICKED, []) if s in 문장들]
    return {"title": "6. 적용", "kind": "human",
            "body": (human or {}).get("6. 적용", ""),
            "placeholder": 안내,
            "후보": 후보,
            "고른": 고른}


# ── 조립 ──────────────────────────────────────────────────────────
def build(cards: dict, human: dict | None = None) -> list[dict]:
    """제안서 7장을 조립한다. human 은 사람이 쓴 장의 본문 딕셔너리.

    **순서와 자동/사람 구분은 바꾸지 않는다.**

        1 한 장 요약 → 2 하지 말 것 → 3 다시 할 것 → 4 할 것
        → 5 이 제안이 틀린다면 → 6 적용 → 7 부록(근거 상세)

    「하지 말 것」이 「할 것」보다 앞에 오는 것이 이 순서의 전부다.
    뒤로 밀면 안 읽히고, 안 읽히는 제안은 안 한 제안과 같다.

    반환값은 sections.build() 와 같은 모양이다 —
    {"title", "kind": "auto"|"human", "body", ...} 의 리스트.
    1장에는 차단 목록이 "blocks" 키로 함께 실린다. **비어 있지 않으면 내보내지 않는다.**
    """
    human = human or {}
    카드들 = _cards(cards)
    return [
        _s1_summary(cards, 카드들),
        _s_class("하지 말 것", 2, 카드들),
        _s_class("다시 할 것", 3, 카드들),
        _s_class("할 것", 4, 카드들),
        _s5_falsify(human, 카드들),
        _s6_apply(human, 카드들, read_decisions()),
        _s7_appendix(cards, 카드들),
    ]


# ══════════════════════════════════════════════════════════════════
# HTML 내보내기 — 제안서_템플릿.html 의 구조와 클래스를 그대로 쓴다
# ══════════════════════════════════════════════════════════════════
TEMPLATE_FILE = Path(__file__).resolve().parent / "제안서_템플릿.html"

# 템플릿에 있는 클래스만 쓴다. 새 클래스를 만들지 않는다 —
# 만드는 순간 이 문서만 다르게 보이고, 템플릿을 고쳐도 안 따라온다.
_BADGE = {"하지 말 것": ("b-block", "✕ 하지 말 것"),
          "다시 할 것": ("b-warn", "▲ 다시 할 것"),
          "할 것": ("b-ok", "● 할 것")}
_PROP = {"하지 말 것": "stop", "다시 할 것": "redo", "할 것": "go"}
_NO = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]

_STYLE = re.compile(r"<style>.*?</style>", re.S)
# **쪼개면 안 되는 덩어리부터 집는다.** 날짜·분기·실행 ID 는 숫자가 아니라 이름이다.
# 먼저 안 집으면 "2025Q3" 가 "2025" + "Q3" 로, "20260903-203951" 이 반토막이 난다.
_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2}:\d{2})?"   # 날짜(시각)
                    r"|\d{6,}-\d{4,}"                              # 실행 ID
                    r"|\d{4}Q[1-4]")                               # 분기
_NUM = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?:%p|%)?")
_PLACE = re.compile(r"&lt;[^&]*?&gt;")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _mark_num(s: str) -> str:
    """숫자에 class="num" 을 붙인다. **날짜·분기·실행 ID 는 통째로 한 덩어리다.**

    먼저 집지 않으면 "2026-09-15" 가 세 토막, "2025Q3" 가 두 토막으로 잘린다.
    """
    def 숫자(t: str) -> str:
        return _NUM.sub(lambda x: f'<span class="num">{x.group(0)}</span>', t)

    조각, 끝 = [], 0
    for m in _TOKEN.finditer(s):
        조각.append(숫자(s[끝:m.start()]))
        조각.append(f'<span class="num">{m.group(0)}</span>')
        끝 = m.end()
    조각.append(숫자(s[끝:]))
    return "".join(조각)


def _txt(s) -> str:
    """본문 한 토막. 이스케이프 → todo 자리 → 굵게 → 숫자 순서로 입힌다.

    **순서를 바꾸지 않는다.** 숫자를 먼저 감싸면 그 안에 들어간 태그를
    뒤의 정규식이 다시 집어 태그가 겹친다.
    """
    t = _esc(s)
    t = _PLACE.sub(lambda m: f'<span class="todo">{m.group(0)}</span>', t)
    t = _BOLD.sub(r"<b>\1</b>", t)
    if t.startswith("todo:"):
        return f'<span class="todo">{_mark_num(t)}</span>'
    return _mark_num(t)


def _val(v, 없으면: str) -> str:
    """빈 칸은 **채우지 않는다.** 템플릿처럼 대괄호 자리로 남긴다."""
    if str(v or "").strip():
        return _txt(v)
    return f'<span class="todo">[ {_esc(없으면)} ]</span>'


def _find(secs: list[dict], 조각: str) -> dict | None:
    return next((s for s in secs if 조각 in s.get("title", "")), None)


def _style() -> str:
    """템플릿의 <style> 을 **그대로** 가져온다.

    외부 CSS·이미지·CDN 을 쓰지 않는다 — 단일 파일이어야 메일에 붙이든
    USB 로 옮기든 같은 문서가 된다. 템플릿을 못 읽으면 **꾸미지 않은 채로**
    내보낸다. 조용히 다른 스타일을 지어내면 템플릿과 갈라진다.
    """
    try:
        m = _STYLE.search(TEMPLATE_FILE.read_text(encoding="utf-8"))
    except OSError:
        m = None
    return m.group(0) if m else "<style>/* 템플릿을 못 읽었습니다 */</style>"


def _cover(s1: dict | None, 카드들: list[dict]) -> str:
    메타 = (s1 or {}).get("메타") or {}
    차단 = int(메타.get("차단", 0))
    뱃지 = ('<span class="badge b-ok">● 차단 0</span>' if not 차단
            else f'<span class="badge b-block">✕ 차단 {차단}</span>')
    return (
        '<div class="cover">'
        '<div class="kicker">성과 개선 제안</div>'
        # 한 줄 주장은 **사람이 쓴다.** 카드에 없으므로 자리만 남긴다.
        '<h1><span class="todo">[ 무엇을 하자고 하는지 한 줄 ]</span></h1>'
        f'<div class="sub">{_val(메타.get("대상"), "어느 분석의 결과인지")} · '
        f'제안 <span class="num">{len(카드들)}</span>건</div>'
        '<div class="meta">'
        f'<span>카드 <b>{_val(메타.get("갱신"), "갱신일")}</b></span>'
        f'<span>조회 <b>{_val(메타.get("일시"), "조회 일시")}</b></span>'
        f'<span>표본 <b>{_val(메타.get("표본"), "표본")}</b></span>'
        f'<span>검증 <b>{뱃지}</b></span>'
        '</div></div>')


def _summary(s1: dict | None, secs: list[dict]) -> str:
    요약 = (s1 or {}).get("요약")
    if 요약 is None:
        # 차단이면 요약을 조립하지 않았다. 없는 것을 있는 척 그리지 않는다.
        막힘 = (s1 or {}).get("blocks") or []
        항목 = "".join(f"<li>{_txt(m)}</li>" for m in 막힘)
        return ('<div class="callout stop"><b>이 문서를 내보내지 마십시오.</b> '
                f'차단 <span class="num">{len(막힘)}</span>건입니다. '
                f'한 장 요약은 조립하지 않았습니다.<ul>{항목}</ul></div>')

    항목 = []
    for 분류 in CLASSES:
        절 = _find(secs, f". {분류}")
        for c in (절 or {}).get("카드", []):
            cls, 라벨 = _BADGE[분류]
            항목.append(
                f'<li><span class="n">{_NO[min(len(항목), 9)]}</span><span>'
                f'<span class="badge {cls}">{라벨}</span> '
                f'{_val(c.get("제목"), "제안 한 줄")}</span></li>')
    plist = ("".join(항목) if 항목
             else '<li><span class="todo">[ 제안이 없다 ]</span></li>')
    return (
        '<div class="summary"><h2>한 장 요약</h2>'
        '<div class="srow"><div class="k">발견</div>'
        f'<div class="v"><div class="lead">{_txt(요약["발견"])}</div></div></div>'
        '<div class="srow"><div class="k">제안</div>'
        f'<div class="v"><ul class="plist">{plist}</ul></div></div>'
        '<div class="srow"><div class="k">불확실</div>'
        f'<div class="v">{_txt(요약["불확실"])}</div></div>'
        '<div class="srow"><div class="k">근거</div>'
        f'<div class="v small">{_txt(요약["근거"])}</div></div>'
        '</div>')


def _prop(c: dict, 분류: str, no: str) -> str:
    확신도 = _확신도(c)
    if 확신도:
        cls = {"확인됨": "b-ok", "추정": "b-warn"}.get(확신도, "b-block")
        확신 = f'<span class="badge {cls}">{_esc(확신도)}</span>'
    else:
        확신 = '<span class="todo">[ 확인됨 / 추정 / 미확인 ]</span>'
    칸 = "".join(
        f"<dt>{k}</dt><dd>{_val(c.get(k), 없으면)}</dd>"
        for k, 없으면 in (("근거", "값 · 분모 · 비교 대상 · 비중"),
                          ("비용", "무엇이 드는가"),
                          ("효과", "관측된 값 / 추정이면 가정을 함께"),
                          ("되돌림", "가능 / 부분 가능 / 불가 — 왜")))
    return (f'<div class="prop {_PROP[분류]}">'
            f'<div class="cls">{no} {_esc(분류)}</div>'
            f'<h4>{_val(c.get("제목"), "제안 한 줄 — 동사로 끝낸다")}</h4>'
            f"<dl>{칸}<dt>확신도</dt><dd>{확신}</dd></dl></div>")


def _sec_props(secs: list[dict], 번호: int) -> str:
    """2·3·4장 — 분류별 제안 카드. 템플릿의 .prop 구조를 그대로 쓴다."""
    덩이, n = [], 0
    for 분류 in CLASSES:
        절 = _find(secs, f". {분류}")
        if 절 is None:
            continue
        카드 = 절.get("카드") or []
        덩이.append(f'<h2 class="sec"><span class="no">{번호}</span>'
                    f'{_esc(절["title"].split(". ", 1)[-1])}</h2>'
                    f'<p class="sec-lead">{_txt(CLASS_NOTE[분류])}</p>')
        if not 카드:
            덩이.append('<p><span class="todo">[ 이 분류의 제안이 없다 ]</span></p>')
        for c in 카드:
            n += 1
            덩이.append(_prop(c, 분류, _NO[min(n - 1, 9)]))
        번호 += 1
    return "".join(덩이)


def _sec_human(s: dict | None, 번호: int) -> str:
    """5·6장 — 사람이 쓰는 장. 안 썼으면 **빈 채로 남긴다.**"""
    if s is None:
        return ""
    제목 = _esc(s["title"].split(". ", 1)[-1])
    본문 = (f"<p>{_txt(s['body'])}</p>" if str(s.get("body") or "").strip()
            else f'<p><span class="todo">[ {_esc(s.get("placeholder", ""))} ]'
                 f"</span></p>")
    더 = ""
    고른 = s.get("고른")
    if 고른 is not None:
        줄 = "".join(
            f"<tr><td>{_txt(x)}</td>"
            f'<td><span class="todo">[ 우리 어느 일에 적용하면 무엇이 달라지나 ]'
            f"</span></td></tr>" for x in 고른)
        더 = ("<table><thead><tr><th>판단 기준</th>"
              "<th>어디에 적용하면 무엇이 달라지나</th></tr></thead><tbody>"
              + (줄 or '<tr><td><span class="todo">[ 판단기준.md 에서 고른 문장 ]'
                       '</span></td><td><span class="todo">[ ]</span></td></tr>')
              + "</tbody></table>")
    return (f'<h2 class="sec"><span class="no">{번호}</span>{제목}</h2>'
            f"{본문}{더}")


def _appendix(s7: dict | None) -> str:
    if s7 is None:
        return ""
    카드들 = s7.get("카드") or []
    줄 = "".join(
        f"<tr><td>{_esc(_번호(c))}</td><td>{_esc(c.get('분류', ''))}</td>"
        f'<td>{_val(c.get("제목"), "제목")}</td>'
        f'<td>{_val(c.get("근거"), "근거 — 데이터에서 조회한다")}</td></tr>'
        for c in 카드들)
    표 = ("<table><thead><tr><th>번호</th><th>분류</th><th>제안</th>"
          f"<th>근거</th></tr></thead><tbody>{줄}</tbody></table>"
          if 줄 else '<p><span class="todo">[ 카드가 없다 ]</span></p>')

    안만든 = s7.get("안만든") or []
    뺀것 = ""
    if 안만든:
        r = "".join(f'<tr><td>{_txt(x.get("무엇", ""))}</td>'
                    f'<td>{_txt(x.get("왜", ""))}</td></tr>' for x in 안만든)
        뺀것 = ('<h2 class="sec">부록 B · 카드로 만들지 않은 것</h2>'
                '<p class="small">뺀 것이 아니라 왜 안 만들었는지를 남긴다.</p>'
                "<table><thead><tr><th>무엇</th><th>왜</th></tr></thead>"
                f"<tbody>{r}</tbody></table>")
    return ('<div class="appendix">'
            '<h2 class="sec">부록 A · 근거 상세</h2>'
            f"{표}{뺀것}</div>")


def to_html(secs: list[dict]) -> str:
    """제안서 7장을 **단일 파일 HTML** 로 만든다.

    구조와 클래스는 `제안서_템플릿.html` 을 그대로 쓴다 — .cover · .summary/.srow ·
    .prop.stop/.redo/.go · .badge · .callout · .appendix · .num · .todo.
    스타일도 그 파일의 <style> 을 읽어 그대로 인라인한다.

    **외부를 아무것도 안 부른다.** CSS 링크·이미지·CDN·웹폰트가 없다.
    파일 하나로 끝나야 메일에 붙이든 USB 로 옮기든 같은 문서가 된다.

    **안 채운 자리는 채우지 않는다.** class="todo" 로 남긴다 —
    템플릿이 "미확인은 구멍이 아니라 요청이다"라고 적어 둔 그대로다.
    숫자에는 class="num" 을 붙여 자릿수가 세로로 맞게 한다.
    """
    s1 = _find(secs, "한 장 요약")
    카드들 = (_find(secs, "부록") or {}).get("카드") or []
    제목 = ((s1 or {}).get("메타") or {}).get("대상") or "제안서"
    안쪽 = "".join([
        _cover(s1, 카드들),
        _summary(s1, secs),
        _sec_props(secs, 1),
        _sec_human(_find(secs, "이 제안이 틀린다면"), 4),
        _sec_human(_find(secs, "적용"), 5),
        _appendix(_find(secs, "부록")),
    ])
    return ('<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
            '<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>제안서 · {_esc(제목)}</title>\n"
            f"{_style()}\n</head>\n<body>\n"
            f'<div class="page">{안쪽}</div>\n</body>\n</html>\n')


# ══════════════════════════════════════════════════════════════════
# PDF 내보내기 — report/to_pdf.py 와 **같은 방식**
# ══════════════════════════════════════════════════════════════════
# 폰트·머리말·꼬리말은 to_pdf.Report 를 그대로 쓴다. 여기서 FPDF 를 새로
# 깔면 한글 폰트 등록이 두 곳이 되고, 한쪽만 고치면 한쪽에서만 글자가 깨진다.
_MD = re.compile(r"^#{1,6}\s*|^[-*]\s+", re.M)


# Noto Sans KR 에 없는 글자. **빈칸으로 새는 것보다 바꿔 넣는 편이 낫다** —
# 없는 글자는 조용히 사라져서, 인쇄하고 나서야 문장이 이상한 것을 알게 된다.
# 화면(HTML)에는 원래 글자가 그대로 간다. 여기 표는 PDF 에서만 쓴다.
_NOGLYPH = str.maketrans({"「": "'", "」": "'", "⚠": "(!)", "←": "<-"})


def _plain(s: str) -> str:
    """PDF 는 마크다운을 모른다. 표시용 기호만 걷어낸다.

    **글자는 안 바꾼다.** `**` 와 `###` 와 목록 기호만 없앤다 —
    화면과 PDF에 같은 문장이 실려야 어느 쪽을 봐도 같은 제안이 된다.
    예외는 폰트에 없는 글자뿐이고, 그건 _NOGLYPH 에 적어 둔다.
    """
    t = _BOLD.sub(r"\1", _MD.sub("", str(s or ""))).strip()
    return t.translate(_NOGLYPH)


def _is_todo(line: str) -> bool:
    """아직 안 채운 줄인가. 색을 달리 해 **눈에 띄게 남긴다.**"""
    t = line.strip()
    return t.startswith("todo:") or bool(re.search(r"<[^<>]*>", t)) \
        or t.startswith("[작성되지 않음]")


def build_pdf(secs: list[dict], title: str = "성과 개선 제안") -> bytes:
    """제안서 7장을 PDF 로 만든다. `to_pdf.build_pdf()` 와 같은 뼈대다 —
    표지 → 목차 → 장마다 새 페이지.

    차트는 받지 않는다. 제안서에 들어갈 그림은 아직 없다 —
    없는 인자를 받아 두면 있는 줄 알고 넘기게 된다.

    **안 채운 자리는 채우지 않는다.** todo 줄은 경고색으로 남긴다.
    """
    from report.to_pdf import INK, LINE, MUTED, Report, _hex

    WARN = _hex("#b45309")
    BLOCK = _hex("#9f1239")

    s1 = _find(secs, "한 장 요약") or {}
    메타 = s1.get("메타") or {}
    막힘 = s1.get("blocks") or []
    카드들 = (_find(secs, "부록") or {}).get("카드") or []

    pdf = Report()

    # ── 표지 ──────────────────────────────────────────────────────
    pdf.add_page()
    pdf.ln(64)
    pdf.set_font(pdf.base, "B", 26)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 12, title, align="L",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font(pdf.base, "", 12)
    pdf.set_text_color(*MUTED)
    for 줄 in (메타.get("대상") or "[ 어느 분석의 결과인지 ]",
               f"제안 {len(카드들)}건 · "
               + " · ".join(f"{k} {len(_of(카드들, k))}" for k in CLASSES)):
        pdf.multi_cell(0, 8, _plain(줄), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_draw_color(*_hex("#4f46e5"))
    pdf.set_line_width(1.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 40, pdf.get_y())
    pdf.ln(14)
    pdf.set_font(pdf.base, "", 10)
    pdf.set_text_color(*(BLOCK if 막힘 else MUTED))
    pdf.multi_cell(0, 6, _plain(f"검증 차단 {len(막힘)}건"
                                + ("  ← 내보내지 마십시오" if 막힘 else "")),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, f"생성 {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ── 목차 ──────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf.base, "B", 15)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, "목차", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for s in secs:
        pdf.set_font(pdf.base, "", 11)
        pdf.set_text_color(*INK)
        mark = "" if s["kind"] == "auto" else "  (사람 작성)"
        pdf.cell(0, 8, _plain(s["title"]) + mark, new_x="LMARGIN", new_y="NEXT")

    if 막힘:
        # 차단은 목차 바로 뒤다. 뒤로 미루면 본문부터 읽고 덮는다.
        pdf.ln(6)
        pdf.set_font(pdf.base, "B", 11)
        pdf.set_text_color(*BLOCK)
        pdf.multi_cell(0, 7, f"차단 {len(막힘)}건 — 먼저 보십시오",
                       new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.base, "", 10)
        for m in 막힘:
            pdf.multi_cell(0, 6, f"· {_plain(m)}", new_x="LMARGIN", new_y="NEXT")

    # ── 본문 ──────────────────────────────────────────────────────
    for s in secs:
        pdf.add_page()
        pdf.set_font(pdf.base, "B", 15)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 9, _plain(s["title"]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.3)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(6)

        body = (s.get("body") or "").strip()
        if not body:
            pdf.set_font(pdf.base, "", 10)
            pdf.set_text_color(*WARN)
            pdf.multi_cell(0, 6, f"[작성되지 않음] "
                                 f"{_plain(s.get('placeholder', ''))}",
                           new_x="LMARGIN", new_y="NEXT")
            # 6장은 고른 결정이 따로 있다. 본문이 비었다고 그것까지 빼지 않는다.
            _picked(pdf, s, INK, MUTED)
            continue

        for para in body.split("\n\n"):
            for 줄 in para.split("\n"):
                줄 = _plain(줄)
                if not 줄:
                    continue
                todo = _is_todo(줄)
                pdf.set_font(pdf.base, "B" if 줄.startswith("제안 ") else "", 10.5)
                pdf.set_text_color(*(WARN if todo else INK))
                pdf.multi_cell(0, 6.2, 줄, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
        _picked(pdf, s, INK, MUTED)

    return bytes(pdf.output())


def _picked(pdf, s: dict, INK, MUTED) -> None:
    """6장의 「고른 결정」. 화면에서 고른 것을 문서에도 싣는다."""
    고른 = s.get("고른")
    if 고른 is None:
        return
    pdf.ln(2)
    pdf.set_font(pdf.base, "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 6.2, "고른 판단 기준", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(pdf.base, "", 10.5)
    if not 고른:
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(0, 6.2, "[ 아직 고르지 않았습니다 ]", new_x="LMARGIN", new_y="NEXT")
        return
    pdf.set_text_color(*INK)
    for x in 고른:
        pdf.multi_cell(0, 6.2, f"· {_plain(x)}", new_x="LMARGIN", new_y="NEXT")
