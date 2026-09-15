# -*- coding: utf-8 -*-
"""제안서 조립.

────────────────────────────────────────────────────────────────────
읽는 사람은 **팀장**이고, 읽고 나서 `config.PROPOSAL_DECISIONS` 중 하나를 정한다.
절 순서는 그 결정에 필요한 차례다 — `config.PROPOSAL_SECTIONS` 에 있다.
**판정어도 절 제목도 여기 적지 않는다.** 문서에 나가는 말은 전부 config 에 있다.

    데이터가 쓴다  auto    현황 · 원인 · 규모 · 신뢰
    사람이 쓴다    human   위험·철회 기준 · 요청

**해석과 요청을 자동으로 쓰지 않는다.** 자동화하는 순간 책임이 사라진다.
────────────────────────────────────────────────────────────────────

여기서 지키는 것 넷.

  1. **evidence 에 없는 값으로 문장을 만들지 않는다.**
     없으면 그 절을 **아예 만들지 않는다.** 빈 절을 남겨 두면 "해당 없음"으로
     읽히고, todo 로 남겨 두면 채울 수 있는 것처럼 읽힌다. 둘 다 사실이 아니다.

  2. **값을 다시 계산하지 않는다.** metrics 가 센 것을 문장으로 옮길 뿐이다.
     여기서 한 번 더 세면 같은 수가 두 값으로 갈린다.

  3. **실측과 환산을 한 문장에 합치지 않는다.** 표에서 줄을 나누고
     `config.PROPOSAL_LABELS` 의 말로 각각 이름을 붙인다.

  4. **제목·질문·판정어를 이 파일에 박지 않는다.** 전부 config 에서 읽는다.
     여기 박으면 문서 구조가 코드 안에 숨고, 고칠 때 두 곳을 고치게 된다.

절 하나의 모양:

    {"제목": str,        config.PROPOSAL_SECTIONS 에서
     "질문": str,        이 절이 답하는 질문 한 줄. 화면과 문서에 같이 나간다
     "kind": "auto" | "human",
     "문장": [str, ...], 자동 절은 데이터에서 나온 문장. 사람 절은 사람이 쓴 것
     "차트": str | None, 인라인 SVG 문자열 하나
     "표":   DataFrame | None}
"""
from __future__ import annotations

import re

import pandas as pd

from core import config as C
from viz import proposal_charts as PCH

# 인과 단정 검사는 리포트 것을 **그대로 쓴다.** 두 벌이 되면 한쪽만 통과한다.
from report.sections import BANNED, check_phrasing  # noqa: F401  (재수출)

SECTIONS = {s["키"]: s for s in C.PROPOSAL_SECTIONS}


def 말(그룹: str, 키: str) -> str:
    """인쇄되는 말 하나. **없으면 에러를 내지 않고 키를 그대로 쓴다.**

    라벨이 비었다고 문서가 안 나오면, 말을 고르는 동안 아무것도 못 만든다.
    키가 그대로 찍히면 "아직 말을 안 정했다"가 문서에서 눈에 띈다.
    """
    return C.PROPOSAL_WORDS.get(그룹, {}).get(키, 키)


# 값 구분(실측·환산·상한·가정)은 자주 쓰므로 꺼내 둔다. 출처는 같다.
LAB = C.PROPOSAL_LABELS


def _num(v):
    """쓸 수 있는 수인가. None·NaN 은 값이 없는 것이다."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _sec(키: str, 문장: list[str], 차트=None, 표=None,
         자동: list[str] | None = None) -> dict:
    """절 하나. 제목·질문·kind 는 config 에서 온다.

    **"문장" 과 "자동" 을 가른다.** 사람이 쓰는 절에도 자동으로 붙이는 줄이 있는데,
    한 칸에 담으면 사람이 쓴 것과 붙인 것을 못 가리고, 사람 글에 자동 검사가 걸린다.
    """
    s = SECTIONS[키]
    return {"제목": 말("절제목", 키), "질문": s["질문"], "kind": s["kind"],
            "문장": [x for x in 문장 if x], "차트": 차트, "표": 표,
            "자동": [x for x in (자동 or []) if x]}


def _blk(evidence: dict, 키: str) -> dict:
    return (evidence or {}).get(키) or {}


def 미확인(v) -> bool:
    """카드의 이 칸이 아직 안 채워졌는가.

    **"미확인"이라는 글자가 있다고 전부 빈 칸은 아니다.** 실측값을 적고 그 옆에
    "추정치는 미확인"이라고 덧붙인 칸은 채워진 것이다 — 오히려 정직한 칸이다.
    실측이 하나도 없이 미확인만 있는 칸을 빈 칸으로 본다.

    ⚠ `report/proposal_v1.py` 에도 같은 판정이 있다. 그쪽은 **보존해 둔 옛 판**이라
       따라 고치지 않는다. 살아 있는 판정은 여기 하나다.
    """
    t = str(v or "").strip()
    if not t:
        return True
    if "실측" in t:
        return False
    return "미확인" in t


# ── auto — 데이터가 쓰는 절 ───────────────────────────────────────
# 절 하나는 **세 문장을 넘지 않는다.** 자리는 셋이고 뜻이 정해져 있다.
#
#   1  무슨 일이 일어나는가   값과 **분모**를 함께. 분모 없는 비율은 판단 재료가 아니다
#   2  그게 왜 문제인가       **비교 대상 대비** 얼마나 벌어졌는지
#   3  그래서 얼마인가        **연간으로 환산한** 규모 + 쓴 가정을 괄호로
#
# ★ **실측 문장과 환산 문장을 합치지 않는다.** 한 문장에 넣으면 읽는 사람은
#   둘 다 실측으로 읽는다. 1·2 는 기간 안에서 센 값이고, 3 만 환산이다.
# ★ **자리가 비면 그 문장을 안 쓴다.** evidence 에 환산 값이 없는 절은 두 문장이다.
#   자리를 채우려고 다른 절의 숫자를 끌어오면 같은 수가 문서에 두 번 나온다.
# ★ **함수·컬럼 이름을 문장에 넣지 않는다.** 팀장이 읽는 문서다.
#   evidence 가 준 사유 문자열에는 함수 이름이 들어 있어 **그대로 싣지 않는다** —
#   사유에 담긴 수만 꺼내 새로 쓴다.
# ★ 값끼리의 뺄셈·나눗셈(격차·몫)은 만든 것이 아니라 **비교**다. 다만 그 재료는
#   둘 다 evidence 에 있어야 한다.


def _문장(*칸) -> list[str]:
    """빈 자리를 걸러 문장 목록을 만든다. **셋을 넘지 않는다.**"""
    쓸 = [x for x in 칸 if x]
    assert len(쓸) <= 3, f"한 절은 세 문장을 넘지 않는다 — {len(쓸)}개"
    return 쓸


def _가정(b: dict) -> str:
    """환산 문장 뒤에 붙일 괄호 한 줄. 가정이 없으면 빈 문자열."""
    쓴 = [str(a).replace("**", "") for a in (b.get("가정") or [])]
    return f" (가정: {' · '.join(쓴)})" if 쓴 else ""


def _총이탈(evidence: dict):
    표 = _blk(evidence, "현황").get("표")
    return None if 표 is None or "이탈" not in 표 else int(표["이탈"].sum())


def _현황(evidence: dict) -> dict | None:
    """무슨 일이 일어나는가 → 어디가 가장 벌어졌는가."""
    표 = _blk(evidence, "현황").get("표")
    if 표 is None or len(표) == 0:
        return None
    첫, 끝 = 표.iloc[0], 표.iloc[-1]
    하나 = (f"{첫['단계']} {int(첫['도달']):,}건 가운데 {끝['단계']}까지 간 것은 "
            f"{int(끝['도달']):,}건이다({_num(끝['누적 전환율']):.2f}%).")

    둘 = None
    병목 = 표[표["병목"]]
    if len(병목):
        i = int(병목.index[0])
        if i > 0:
            앞, 이 = 표.iloc[i - 1], 표.iloc[i]
            앞n, 이n = int(앞["도달"]), int(이["도달"])
            율 = 이n / 앞n * 100 if 앞n else 0.0
            # 앞 구간 전환율도 **건수에서** 낸다. 표에 실린 값은 소수 둘째 자리까지
            # 반올림돼 있어, 그걸로 빼면 규모 절의 격차와 끝자리가 갈린다.
            앞율 = (int(앞["도달"]) / int(표.iloc[i - 2]["도달"]) * 100
                    if i >= 2 and int(표.iloc[i - 2]["도달"]) else None)
            벌어짐 = (f", 바로 앞 구간({앞율:.2f}%)보다 {앞율 - 율:.2f}%p 낮은 값이다"
                      if 앞율 is not None else "")
            # 한 항목에 한 문장만 담는다. 마침표로 둘을 이어 붙이면 세 문장 규칙이
            # 항목 수로는 지켜지고 읽는 사람에게는 안 지켜진다.
            둘 = (f"가장 많이 빠지는 곳은 {앞['단계']} → {이['단계']} 구간으로, "
                  f"{앞n:,}건 중 {이n:,}건만 넘어가 {int(이['이탈']):,}건이 빠지며"
                  f"({율:.2f}%){벌어짐}.")
    # 환산 값은 이 절에 없다 — 규모 절이 답한다. 자리를 억지로 채우지 않는다.
    return _sec("현황", _문장(하나, 둘), PCH.funnel_svg(_blk(evidence, "현황")), 표)


def _원인(evidence: dict) -> dict | None:
    """어느 칸이 낮은가 → 가장 높은 칸 대비 얼마나 벌어졌는가."""
    b = _blk(evidence, "원인")
    표, 축 = b.get("표"), b.get("축")
    if 표 is None or not 축 or 축 not in 표.columns:
        return None
    쓸 = 표[표["사유"].isna()]
    if len(쓸) < 2:
        return None

    최저 = 쓸.loc[쓸["전환율"].idxmin()]
    최고 = 쓸.loc[쓸["전환율"].idxmax()]
    # 격차는 **반올림한 전환율이 아니라 건수에서** 낸다. 반올림한 값을 빼면
    # 앞서 센 격차와 소수 둘째 자리가 갈리고, 같은 격차가 두 값으로 나온다.
    격차 = (int(최고["전환"]) / int(최고["도달"])
            - int(최저["전환"]) / int(최저["도달"])) * 100
    # 값 뒤에 조사를 붙이지 않는다 — 칸 이름이 숫자면 "4 이며"처럼 깨지고,
    # 받침 유무에 따라 "로/으로"가 갈려 축 이름마다 문장이 틀어진다.
    하나 = (f"{b.get('구간', '')} 구간을 {축} 기준으로 나눠 보면 가장 낮은 칸은 "
            f"{최저[축]} — {int(최저['도달']):,}건 중 "
            f"{int(최저['전환']):,}건이 넘어갔다({_num(최저['전환율']):.2f}%).")
    둘 = (f"가장 높은 칸 {최고[축]}({_num(최고['전환율']):.2f}%)보다 "
          f"{격차:.2f}%p 낮으며, 이 칸이 같은 구간의 "
          f"{_num(최저['비중']):.2f}%를 차지한다"
          + (f"(분모 {int(b['비중_분모']):,}건)." if b.get("비중_분모") else "."))
    return _sec("원인", _문장(하나, 둘), PCH.gap_svg(b), 표)


def _규모(evidence: dict) -> dict | None:
    """실측 → 전체 대비 몫 → 연간 환산. **셋째 문장만 환산이다.**"""
    b = _blk(evidence, "규모")
    실측, 환산 = b.get("실측"), b.get("환산")
    if not 실측 or not 환산:
        return None

    하나 = (f"기간 안에서 실제로 센 값은 {실측['기간_건수']:,.1f}건이다 — "
            f"격차 {실측['격차_%p']:.2f}%p 에 해당 건수 "
            f"{int(실측['도달']):,}건을 곱한 값이며, 기간은 {실측['기간']} 이다.")

    둘 = None
    총 = _총이탈(evidence)
    if 총:
        둘 = (f"같은 기간 전체 이탈 {총:,}건과 견주면 "
              f"{실측['기간_건수'] / 총 * 100:.1f}% 에 해당하고, 격차가 전부 "
              f"메워진다고 본 {LAB['상한']}이라 기대치가 아니다.")

    셋 = (f"{LAB['환산']}으로는 {환산['연간_건수']:,.1f}건이다"
          f"{_가정(b)}.")

    행 = [{"구분": LAB["실측"], "값": f"{실측['기간_건수']:,.1f}건",
           "무엇": f"격차 {실측['격차_%p']:.2f}%p × {int(실측['도달']):,}건 · "
                   f"기간 {실측['기간']}"},
          {"구분": LAB["환산"], "값": f"{환산['연간_건수']:,.1f}건",
           "무엇": f"{LAB['실측']}에 기간 배수 {환산['배수']} 를 곱한 값. "
                   f"{LAB['실측']}이 아니다"}]
    if 실측.get("비중_%") is not None:
        행.append({"구분": "비중", "값": f"{실측['비중_%']:.2f}%",
                   "무엇": f"분모 {int(실측['비중_분모']):,}건"})
    return _sec("규모", _문장(하나, 둘, 셋), None, pd.DataFrame(행))


def _신뢰(evidence: dict) -> dict | None:
    """무엇으로 봤는가 → 무엇을 못 봤는가.

    **evidence 가 준 사유 문자열을 그대로 싣지 않는다.** 그 안에는 함수 이름이
    들어 있어 팀장이 읽는 문서에 나갈 말이 아니다. 수만 꺼내 새로 쓴다.
    """
    원인, 추세, 규모 = (_blk(evidence, k) for k in ("원인", "추세", "규모"))
    하나 = 둘 = 셋 = None
    표 = None

    if 원인.get("표") is not None:
        쓸 = int(원인.get("비교_가능_칸") or 0)
        감춤 = int(원인.get("감춘_칸") or 0)
        # "축" 을 붙여 조사를 고정한다. 값 뒤에 바로 조사를 붙이면
        # 받침 유무에 따라 "는/은" 이 갈린다.
        하나 = f"{원인.get('축')} 축은 {쓸 + 감춤}칸 가운데 {쓸}칸으로 비교했다."
        if 감춤:
            못본 = float(원인["표"].loc[원인["표"]["사유"].notna(), "비중"].sum())
            둘 = (f"나머지 {감춤}칸은 표본이 모자라 계산하지 않았고, 그 몫이 "
                  f"이 구간의 {못본:.2f}%다 — 값이 0 이라는 뜻이 아니라 "
                  f"보지 못했다는 뜻이다.")

    if 추세.get("표") is not None:
        표 = 추세["표"]
        믿 = int(표["믿을만"].sum())
        칸 = (f"최근 {len(표)}개 {추세.get('단위') or '구간'} 가운데 "
              f"{믿}개가 표본을 넘었다"
              + ("." if 믿 == len(표) else
                 f"; 나머지는 문서에 싣지 않았다 — 못 믿는 값이다."))
        if 하나 is None:
            하나 = 칸
        elif 둘 is None:
            둘 = 칸
        else:
            셋 = 칸

    if 셋 is None and 규모.get("가정"):
        셋 = (f"위 숫자에는 {len(규모['가정'])}개의 {LAB['가정']}이 붙어 있어 "
              f"{LAB['상한']}과 {LAB['실측']}을 같은 값으로 읽지 않아야 한다.")

    문장 = _문장(하나, 둘, 셋)
    if not 문장:
        return None

    지표 = None
    주제 = (evidence or {}).get("주제")
    키 = str((주제.get("키") if isinstance(주제, dict) else 주제) or "")
    if ":" in 키:
        종류, _, 값 = 키.partition(":")
        지표 = 값 if 종류 in ("임계", "추세") else None
    return _sec("신뢰", 문장, PCH.trend_svg(추세, 지표) if 추세 else None, 표)


# ── human — 사람이 쓰는 절 ───────────────────────────────────────
def _사람(키: str, human: dict, cards: dict, topic) -> dict:
    """위험·철회 기준과 요청. **자동으로 쓰지 않는다.**

    카드에 적힌 것은 **재료로만** 표에 싣는다. 문장은 사람이 쓴다 —
    여기서 대신 쓰면 팀장이 읽는 판단이 사람 것이 아니게 된다.
    """
    제목 = 말("절제목", 키)
    문장 = [x for x in str((human or {}).get(제목, "") or "").split("\n") if x.strip()]
    표 = None
    카드 = _카드(cards, topic)
    if 카드:
        if 키 == "위험":
            반증 = 카드.get("반증") or {}
            행 = [("틀렸다면", 반증.get("가설")),
                  ("확인 방법", 반증.get("확인 방법")),
                  ("확신도", 반증.get("확신도")),
                  ("되돌림", 카드.get("되돌림"))]
        else:
            행 = [("제안", 카드.get("제목")),
                  ("분류", 말("분류어", str(카드.get("분류") or ""))),
                  ("비용", 카드.get("비용")), ("효과", 카드.get("효과"))]
        표 = pd.DataFrame(
            [{"항목": k, "카드에 적힌 것": v or 말("확인필요", "빈칸")}
             for k, v in 행])
    return _sec(키, 문장, None, 표)


def _카드(cards, topic) -> dict | None:
    """이 주제에 붙은 카드. 제목이 같은 것을 찾는다. 없으면 None."""
    목록 = (cards or {}).get("카드") if isinstance(cards, dict) else (cards or [])
    제목 = (topic or {}).get("제목") if isinstance(topic, dict) else None
    if not 목록 or not 제목:
        return None
    return next((c for c in 목록 if str(c.get("제목", "")).strip() == 제목.strip()),
                None)


def _모름(칸: str) -> str:
    """모르는 것 한 줄. **낱말 하나로 두지 않고 셋으로 적는다.**

        무엇을 모르는가 — 누가·어떻게 확인하는가 — 모르는 채로 할 수 있는 결정

    "미확인" 한 낱말만 적으면 읽는 사람이 할 수 있는 일이 없다.
    확인 주체와 그래도 가능한 결정이 붙어야 그 자리에서 결정이 선다.
    뒤 둘은 조직이 정하는 것이라 config 에서 읽고, **비었으면 비었다고 적는다.**
    """
    u = C.PROPOSAL_UNKNOWNS.get(칸) or {}
    무엇 = u.get("무엇") or 칸
    확인 = u.get("확인") or 말("확인필요", "빈칸")
    결정 = u.get("그래도 가능한 결정")
    결정 = 말("판정어", 결정) if 결정 else 말("확인필요", "빈칸")
    return f"{칸} — {무엇} · 확인: {확인} · 모르는 채로 가능한 결정: {결정}"


def _요청(human: dict, cards: dict, topic, evidence: dict) -> dict:
    """요청 — **문장은 사람이 쓴다.** 아래 셋만 자동으로 붙인다.

        · 이 주제의 규모 (연 N건)
        · 결정 선택지 셋과 각각에 따라오는 것
        · 결정을 미뤘을 때 다음 분기까지 쌓이는 양

    붙이는 줄은 "자동" 칸에 담는다. 사람이 쓴 "문장" 과 섞지 않는다 —
    섞으면 팀장이 읽을 때 누가 한 말인지 갈리지 않는다.
    """
    제목 = 말("절제목", "요청")
    문장 = [x for x in str((human or {}).get(제목, "") or "").split("\n")
            if x.strip()]

    자동 = []
    환산 = (_blk(evidence, "규모").get("환산") or {})
    연 = 환산.get("연간_건수")
    if 연 is not None:
        자동.append(f"이 주제의 규모는 {LAB['환산']}으로 {연:,.1f}건이다.")
        # 다음 분기까지 쌓이는 양. **분기마다 고르게 일어난다고 본 값**이고,
        # 그 가정을 문장 안에 적는다 — 빼면 실측처럼 읽힌다.
        자동.append(
            f"결정을 다음 분기로 미루면 그 사이에 {연 / 4:,.1f}건이 더 쌓인다 "
            f"(한 해를 네 분기로 나눠 고르게 일어난다고 본 값이다).")

    # 모르는 것 — 카드에서 아직 미확인인 칸만.
    카드 = _카드(cards, topic)
    if 카드:
        자동 += [_모름(k) for k in ("비용", "효과", "되돌림") if 미확인(카드.get(k))]

    # 결정 선택지 셋. 따라오는 것은 조직 절차라 config 에서 읽는다.
    행 = []
    for 키 in C.PROPOSAL_WORDS["판정어"]:
        따라 = (C.PROPOSAL_DECISION_EFFECT.get(키) or "").strip()
        행.append({"선택지": 말("판정어", 키),
                   "무엇이 따라오는가": 따라 or 말("확인필요", "빈칸")})
    return _sec("요청", 문장, None, pd.DataFrame(행), 자동)


def 요청_점검(secs: list[dict]) -> str | None:
    """요청 문장이 **결정을 요구하고 있는가.** 경고만 한다. 막지 않는다.

    쓰다 만 글을 저장 못 하게 하면 사람이 화면을 떠나고, 떠나면 영영 안 쓴다.
    """
    절 = next((s for s in secs if s["제목"] == 말("절제목", "요청")), None)
    if 절 is None or not 절["문장"]:
        return None
    글 = " ".join(절["문장"])
    if any(v in 글 for v in C.PROPOSAL_ASK_VERBS):
        return None
    return (f"요청 문장에 결정을 요구하는 말이 없습니다 "
            f"({' · '.join(C.PROPOSAL_ASK_VERBS)} 중 하나). "
            f"무엇을 해 달라는 것인지 읽는 사람이 고르지 못합니다.")


def 자동_검사(secs: list[dict]) -> list[tuple[str, list[str]]]:
    """인과 단정 검사. **자동으로 쓴 부분에만 건다.**

    사람이 쓴 문장에 걸면 두 가지가 나빠진다 — 사람 글을 기계가 고치라고 하고,
    그 글 때문에 문서 조립이 멈춘다. 사람 글은 사람이 책임진다.
    """
    나쁨 = []
    for s in secs:
        볼것 = list(s.get("자동") or [])
        if s["kind"] == "auto":
            볼것 += s["문장"]
        걸림 = check_phrasing(" ".join(볼것))
        if 걸림:
            나쁨.append((s["제목"], 걸림))
    return 나쁨

# ── 조립 ──────────────────────────────────────────────────────────
_AUTO = {"현황": _현황, "원인": _원인, "규모": _규모, "신뢰": _신뢰}


def build(topic, evidence: dict, cards=None, human=None) -> list[dict]:
    """제안서 절 목록을 만든다.

    topic     metrics.proposal_topics() 가 고른 주제 하나
    evidence  metrics.topic_evidence(t, topic) 의 결과
    cards     제안카드.md 를 읽은 dict — **사람이 쓰는 절의 재료로만** 쓴다
    human     사람이 쓴 본문. 키는 절 제목이다

    **순서는 config.PROPOSAL_SECTIONS 그대로다. 여기서 바꾸지 않는다.**
    재료가 없는 auto 절은 목록에서 빠진다 — 빈 절로 남기지 않는다.
    human 절 둘은 재료가 없어도 남는다. 그 둘이 팀장이 답해야 할 자리다.
    """
    절 = []
    for s in C.PROPOSAL_SECTIONS:
        키 = s["키"]
        if s["kind"] == "human":
            # 요청 절만 자동으로 붙이는 줄이 있다. 나머지 사람 절은 그대로.
            절.append(_요청(human or {}, cards, topic, evidence or {})
                      if 키 == "요청" else _사람(키, human or {}, cards, topic))
            continue
        만든 = _AUTO[키](evidence or {})
        if 만든 is not None:          # 없으면 아예 안 넣는다
            절.append(만든)
    return 절


def missing(evidence: dict) -> list[dict]:
    """만들지 못한 auto 절과 그 사유. **조용히 빠뜨리지 않으려고 따로 낸다.**

    사유는 evidence 가 준 것을 그대로 옮긴다 — 여기서 만들지 않는다.
    """
    안됨 = []
    for s in C.PROPOSAL_SECTIONS:
        if s["kind"] != "auto" or _AUTO[s["키"]](evidence or {}) is not None:
            continue
        안됨.append({"제목": 말("절제목", s["키"]), "질문": s["질문"],
                     "사유": _blk(evidence, s["키"]).get("사유")
                             or "이 주제에는 낼 자료가 없다"})
    return 안됨


# ── 단일 파일 HTML ────────────────────────────────────────────────
# **템플릿 파일을 읽지 않는다.** 이 함수가 스타일까지 직접 만든다 —
# 바깥 파일에 기대면 그 파일이 없는 곳(배포·메일·USB)에서 다른 문서가 된다.
#
# 색은 넷뿐이다. 다섯째 색을 만들지 않고, 선과 머리행 배경은 먹색을 옅게 쓴다.
#
#   먹색  본문        회색  보조·질문·단위
#   강조  제목·구분선  위험  아직 안 채운 자리
#
# 차트 SVG 도 같은 넷을 쓰므로 문서 전체가 한 벌로 읽힌다.
_INK, _MUTED = C.BRAND["ink"], C.BRAND["muted"]
_ACCENT, _DANGER = C.BRAND["primary"], C.COLORS["block"]

# 문서에 내보내지 않을 표 열.
#   무엇 — 계산 과정이다. 팀장이 읽을 문서에 곱셈식을 싣지 않는다.
# 내부에서 쓰던 이름은 읽는 말로 바꾼다.
_DROP_COLS = {"무엇"}
_RENAME_COLS = {"표시": "구분", "믿을만": "표본 충족", "사유": "비고"}

# 쪼개면 안 되는 덩어리부터 집는다 — 날짜·분기는 숫자가 아니라 이름이다.
_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s\d{2}:\d{2}:\d{2})?|\d{4}Q[1-4]")
_NUMU = re.compile(r"(?<![\w.-])(\d[\d,]*(?:\.\d+)?)(%p|%|건|일|칸|개|분기|명)?")

_CSS = f"""
@page{{size:A4;margin:18mm 16mm}}
:root{{--ink:{_INK};--muted:{_MUTED};--accent:{_ACCENT};--danger:{_DANGER};
      --rule:rgba(15,23,42,.14);--head:rgba(15,23,42,.035)}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{font-family:-apple-system,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;
     color:var(--ink);font-size:10.5pt;line-height:1.72;background:#fff}}
.page{{max-width:180mm;margin:0 auto;padding:16mm 0 24mm}}

/* 제목 위계는 셋까지다. 넷째 단계를 만들지 않는다. */
h1{{font-size:19pt;font-weight:800;margin:0 0 2mm;line-height:1.28;
   page-break-after:avoid}}
h2{{font-size:13pt;font-weight:700;margin:11mm 0 0;padding-top:2mm;
   border-top:1.6pt solid var(--accent);page-break-after:avoid}}
h3{{font-size:10.5pt;font-weight:700;margin:0 0 2mm;color:var(--accent);
   letter-spacing:.04em;page-break-after:avoid}}
.meta{{font-size:9pt;color:var(--muted);margin:0 0 9mm}}

/* 절 제목 아래 붙는 질문. 본문과 섞이지 않게 작고 회색이다. */
.q{{font-size:9pt;color:var(--muted);margin:1mm 0 4mm;page-break-after:avoid}}
p{{margin:0 0 2.5mm;orphans:3;widows:3}}

/* 한 장 요약 — 문서 맨 앞 박스 하나 */
.sum{{border:1pt solid var(--rule);border-left:3pt solid var(--accent);
     border-radius:2mm;padding:6mm 7mm;margin:0 0 9mm;
     page-break-inside:avoid}}
.sum .row{{margin:0 0 3mm}}
.sum .row:last-child{{margin-bottom:0}}
.sum .qq{{font-size:8.5pt;color:var(--muted);margin-bottom:.6mm}}

/* 숫자는 자릿수가 세로로 맞아야 읽힌다. 단위는 한 단계 작게. */
.n{{font-variant-numeric:tabular-nums;font-feature-settings:"tnum";
   font-weight:700}}
.u{{font-size:8.6pt;color:var(--muted);margin-left:.3mm}}
.blank{{color:var(--danger);font-weight:700}}
/* 자동으로 붙인 줄. 사람이 쓴 문장과 눈으로 갈리게 한 톤 물러난다. */
.auto{{color:var(--muted);font-size:9.6pt;margin:0 0 1.6mm;
      padding-left:3mm;border-left:1.5pt solid var(--rule)}}

/* 표는 가로선만. 세로선을 긋지 않는다. */
table{{border-collapse:collapse;width:100%;font-size:9.2pt;margin:4mm 0 0;
      page-break-inside:avoid}}
th,td{{border:0;border-bottom:.75pt solid var(--rule);padding:1.8mm 2.5mm;
      text-align:left;vertical-align:top}}
thead th{{background:var(--head);border-bottom:1pt solid var(--rule);
         font-weight:700;font-size:8.6pt;color:var(--muted)}}
td.r,th.r{{text-align:right}}
figure,svg{{page-break-inside:avoid}}
figure{{margin:4mm 0 0}}
.note{{font-size:9pt;color:var(--muted);margin-top:10mm;padding-top:3mm;
      border-top:.75pt solid var(--rule)}}
@media print{{.page{{max-width:none;padding:0}}}}
"""


def _esc(s) -> str:
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _mark(s) -> str:
    """이스케이프 → 숫자에 굵은 tabular-nums, 단위는 한 단계 작게.

    **SVG 에는 걸지 않는다.** 차트는 이미 제 눈금을 갖고 있고, 태그 속
    숫자를 건드리면 좌표가 깨진다.
    """
    t = _esc(s)
    조각, 끝 = [], 0

    def 숫자(x: str) -> str:
        return _NUMU.sub(
            lambda m: f'<b class="n">{m.group(1)}</b>'
                      + (f'<span class="u">{m.group(2)}</span>'
                         if m.group(2) else ""), x)

    for m in _TOKEN.finditer(t):
        조각.append(숫자(t[끝:m.start()]))
        조각.append(f'<b class="n">{m.group(0)}</b>')
        끝 = m.end()
    조각.append(숫자(t[끝:]))
    return "".join(조각)


def _tbl(df) -> str:
    """가로선만 있는 표. 계산 과정 열은 문서에 싣지 않는다."""
    if df is None or len(df) == 0:
        return ""
    열 = [c for c in df.columns if c not in _DROP_COLS]
    if not 열:
        return ""
    보임 = df[열].astype(object).where(df[열].notna(), "—")
    # 수 열은 오른쪽으로 민다 — 자릿수가 세로로 맞아야 읽힌다.
    수 = {c: pd.api.types.is_numeric_dtype(df[c]) for c in 열}
    머리 = "".join(
        f'<th class="r">{_esc(_RENAME_COLS.get(c, c))}</th>'
        if 수[c] else f"<th>{_esc(_RENAME_COLS.get(c, c))}</th>" for c in 열)
    몸 = ""
    for _, r in 보임.iterrows():
        칸 = "".join(
            f'<td class="r">{_mark(r[c])}</td>' if 수[c]
            else f"<td>{_mark(r[c])}</td>" for c in 열)
        몸 += f"<tr>{칸}</tr>"
    return f"<table><thead><tr>{머리}</tr></thead><tbody>{몸}</tbody></table>"


def _그릴까(s: dict) -> bool:
    """**빈 절은 그리지 않는다.** 문장도 차트도 표도 없으면 절이 아니다."""
    return bool(s.get("문장") or s.get("자동") or s.get("차트")
                or (s.get("표") is not None and len(s["표"])))


def to_html(secs: list[dict]) -> str:
    """절 목록을 **A4 인쇄 기준 단일 파일 HTML** 로 만든다.

    템플릿 파일을 읽지 않는다 — 스타일까지 이 함수가 만든다.
    웹폰트·CDN·외부 이미지를 부르지 않아 파일 하나로 열린다.
    차트는 이미 인라인 SVG 문자열이므로 그대로 넣는다.

    **빈 절은 그리지 않는다.** 사람이 아직 안 쓴 절은 문서에서 빠지고,
    그 질문이 답 없이 남았다는 사실만 맨 끝에 한 줄로 남는다 —
    빠진 것을 모르면 다 갖춰진 문서로 읽힌다.
    """
    그릴 = [s for s in secs if _그릴까(s)]
    안쓴 = [s for s in secs if not _그릴까(s)]

    # 한 장 요약 — 맨 앞 박스 하나. 절마다 질문과 첫 문장을 한 줄씩 옮긴다.
    줄 = "".join(
        f'<div class="row"><div class="qq">{_esc(s["질문"])}</div>'
        f'<div>{_mark(s["문장"][0]) if s["문장"] else ""}</div></div>'
        for s in 그릴 if s["문장"])
    요약 = f'<div class="sum"><h3>한 장 요약</h3>{줄}</div>' if 줄 else ""

    덩이 = []
    for s in 그릴:
        본문 = "".join(f"<p>{_mark(x)}</p>" for x in s["문장"])
        # 자동으로 붙인 줄은 사람이 쓴 문장 **아래**에 따로 둔다.
        붙임 = "".join(f'<p class="auto">{_mark(x)}</p>'
                       for x in (s.get("자동") or []))
        덩이.append(f"<h2>{_esc(s['제목'])}</h2>"
                    f'<div class="q">{_esc(s["질문"])}</div>'
                    f"{본문}{붙임}{s['차트'] or ''}{_tbl(s['표'])}")

    꼬리 = ""
    if 안쓴:
        꼬리 = ('<div class="note">아직 답하지 않은 질문 — '
                + " · ".join(_esc(s["질문"]) for s in 안쓴) + "</div>")

    return ('<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="UTF-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{_esc(C.DATASET)}</title>\n<style>{_CSS}</style>\n"
            f'</head>\n<body>\n<div class="page">'
            f"<h1>{_esc(C.DATASET)}</h1>"
            f'<div class="meta">{_mark(C.PERIOD[0])} ~ {_mark(C.PERIOD[1])}</div>'
            f"{요약}" + "".join(덩이) + 꼬리 + "</div>\n</body>\n</html>\n")
