# app.py
import math
import json
import base64
from typing import Dict, Tuple, List, Optional

import streamlit as st

Ticket = Tuple[int, int, int]

# ========= ロジック（あなたの確定仕様） =========
def norm_ticket(a: int, b: int, c: int) -> Optional[Ticket]:
    t = tuple(sorted((a, b, c)))
    return t if len(set(t)) == 3 else None

def tkey(t: Ticket) -> str:
    return f"{t[0]}{t[1]}{t[2]}"

def parse_marks_order(s: str) -> Dict[str, int]:
    s = (s or "").strip()
    if len(s) != 5 or not s.isdigit():
        raise ValueError("印は5桁の数字で入力してください（例: 32547）")
    nums = list(map(int, s))
    if any(not (1 <= n <= 9) for n in nums):
        raise ValueError("車番は1〜9です。")
    if len(set(nums)) != 5:
        raise ValueError("同じ車番を複数印に使えません。")
    return {"◎": nums[0], "○": nums[1], "▲": nums[2], "△": nums[3], "☓": nums[4]}

def build_candidate_sets(m: Dict[str, int]) -> List[Tuple[str, List[str]]]:
    g, o, a, d, x = m["◎"], m["○"], m["▲"], m["△"], m["☓"]
    t1 = norm_ticket(g, o, a)  # 固定
    t2a = norm_ticket(g, o, d) # ◎-○-△
    t2b = norm_ticket(g, o, x) # ◎-○-☓
    t3a = norm_ticket(g, a, d) # ◎-▲-△
    t3b = norm_ticket(g, a, x) # ◎-▲-☓
    if None in (t1, t2a, t2b, t3a, t3b):
        raise ValueError("候補が成立しません（同一車番が混ざっています）。")
    # 印優先 A→B→C→D
    return [
        ("A", [tkey(t1), tkey(t2a), tkey(t3a)]),
        ("B", [tkey(t1), tkey(t2a), tkey(t3b)]),
        ("C", [tkey(t1), tkey(t2b), tkey(t3a)]),
        ("D", [tkey(t1), tkey(t2b), tkey(t3b)]),
    ]

def required_keys_for_mark(m: Dict[str, int]) -> List[str]:
    k_fixed = tkey(norm_ticket(m["◎"], m["○"], m["▲"]))
    k_go_d  = tkey(norm_ticket(m["◎"], m["○"], m["△"]))
    k_go_x  = tkey(norm_ticket(m["◎"], m["○"], m["☓"]))
    k_ga_d  = tkey(norm_ticket(m["◎"], m["▲"], m["△"]))
    k_ga_x  = tkey(norm_ticket(m["◎"], m["▲"], m["☓"]))
    return [k_fixed, k_go_d, k_go_x, k_ga_d, k_ga_x]

def need_stake(odds: float, target_return: int = 2500, unit: int = 100) -> int:
    raw = target_return / odds
    return max(unit, math.ceil(raw / unit) * unit)

def allocate_budget(odds_list: List[float], total: int = 1000, unit: int = 100, target: int = 2500):
    stakes = [need_stake(o, target, unit) for o in odds_list]
    s = sum(stakes)
    if s > total:
        return None
    rest = total - s
    returns = [stakes[i] * odds_list[i] for i in range(3)]
    while rest >= unit:
        idx = min(range(3), key=lambda i: returns[i])
        stakes[idx] += unit
        returns[idx] += unit * odds_list[idx]
        rest -= unit
    return stakes, returns

def decide_one_race(mark_order: str, odds_map: Dict[str, float], total: int, unit: int, target_return: int):
    m = parse_marks_order(mark_order)
    candidates = build_candidate_sets(m)

    debug_rows = []
    for label, keys in candidates:
        if any(k not in odds_map for k in keys):
            missing = [k for k in keys if k not in odds_map]
            debug_rows.append((label, keys, "NO_ODDS", {"missing": missing}))
            continue

        odds_list = [odds_map[k] for k in keys]
        alloc = allocate_budget(odds_list, total=total, unit=unit, target=target_return)
        if alloc is None:
            needs = [need_stake(o, target_return, unit) for o in odds_list]
            debug_rows.append((label, keys, "NG", {"needs": needs, "needs_sum": sum(needs)}))
            continue

        stakes, returns = alloc
        return {
            "status": "OK",
            "label": label,
            "keys": keys,
            "odds": odds_list,
            "stakes": stakes,
            "returns": returns,
            "min_return": min(returns),
            "debug": debug_rows,
            "marks": m,
        }

    return {"status": "SKIP", "debug": debug_rows, "marks": parse_marks_order(mark_order)}

# ========= URLパラメータ（ブックマークレット受け取り） =========
def b64url_decode_to_dict(s: str) -> Dict[str, float]:
    if not s:
        return {}
    pad = "=" * (-len(s) % 4)
    raw = base64.urlsafe_b64decode((s + pad).encode("utf-8"))
    obj = json.loads(raw.decode("utf-8"))
    out: Dict[str, float] = {}
    for k, v in obj.items():
        # k: "235"  v: "5.4" or 5.4
        out[str(k)] = float(v)
    return out

def b64url_encode_dict(d: Dict[str, float]) -> str:
    raw = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

def load_from_query_params():
    qp = st.query_params
    # m: 印（例 32547） / o: odds_map（例 {"235":5.4,...} をbase64url）
    mark = qp.get("m", "")
    odds_b64 = qp.get("o", "")
    src = qp.get("src", "")

    odds_map: Dict[str, float] = {}
    if odds_b64:
        try:
            odds_map = b64url_decode_to_dict(odds_b64)
        except Exception:
            odds_map = {}

    if "odds_store" not in st.session_state:
        st.session_state["odds_store"] = {}

    changed = False
    if odds_map:
        st.session_state["odds_store"].update(odds_map)
        st.session_state["last_src"] = src or "bookmarklet"
        changed = True

    # ブックマークレットから来た場合は、常にURLの印を採用する
    if mark:
        st.session_state["mark_order"] = mark
        changed = True

    # このリランで一度だけ on_mark_change を自動実行させる
    if changed:
        st.session_state["__auto_apply__"] = True


def on_mark_change():
    """印が入った瞬間に：必要5キーを確定→オッズ自動反映→即判定"""
    mark = (st.session_state.get("mark_order") or "").strip()
    if not mark:
        st.session_state["result"] = None
        return

    try:
        m = parse_marks_order(mark)
        req = required_keys_for_mark(m)
    except Exception as e:
        st.session_state["result"] = {"status": "ERR", "message": str(e)}
        return

    store: Dict[str, float] = st.session_state.get("odds_store", {}) or {}

    # 入力欄に反映（あるものだけ）
    for k in req:
        if k in store:
            st.session_state[f"odds_{k}"] = float(store[k])

    # すぐ判定（足りないオッズがあればスルーになりやすいので、結果表示で分かる）
    total = int(st.session_state.get("total", 1000))
    unit = int(st.session_state.get("unit", 100))
    target_return = int(st.session_state.get("target_return", 2500))

    # 5つ揃ってるものだけ odds_map として渡す
    odds_map = {k: float(st.session_state.get(f"odds_{k}", 0.0)) for k in req if float(st.session_state.get(f"odds_{k}", 0.0)) > 0}
    st.session_state["result"] = decide_one_race(mark, odds_map, total=total, unit=unit, target_return=target_return)

# ========= UI =========
st.set_page_config(page_title="競輪 3連複3点 判定", layout="centered")
load_from_query_params()

# URL取り込み直後は on_change が発火しないので、1回だけ自動適用する
if st.session_state.pop("__auto_apply__", False):
    on_mark_change()

st.title("競輪：3連複3点（印優先）判定（KEIRIN.JP取り込み対応）")

with st.expander("使い方（最短）", expanded=True):
    st.write("""
1) KEIRIN.JPで対象レースの「3連複オッズ」画面を開く  
2) ブックマークレット「送る」を実行（印5桁を聞かれます）  
3) このアプリが開いて、印が入った瞬間にオッズが反映＆自動判定します
""")

c1, c2, c3 = st.columns(3)
with c1:
    st.number_input("予算（円）", min_value=100, max_value=100000, value=1000, step=100, key="total", on_change=on_mark_change)
with c2:
    st.number_input("購入単位（円）", min_value=10, max_value=1000, value=100, step=10, key="unit", on_change=on_mark_change)
with c3:
    st.number_input("払戻下限（円）", min_value=100, max_value=100000, value=2500, step=100, key="target_return", on_change=on_mark_change)

st.text_input("印（5桁：◎○▲△☓）", value=st.session_state.get("mark_order", ""), key="mark_order", on_change=on_mark_change, placeholder="例：32547")

mark_order = (st.session_state.get("mark_order") or "").strip()
if mark_order:
    try:
        m = parse_marks_order(mark_order)
        st.success(f"◎{m['◎']} ○{m['○']} ▲{m['▲']} △{m['△']} ☓{m['☓']}")
        cands = build_candidate_sets(m)

        st.subheader("候補3点（印優先 A→B→C→D）")
        for label, keys in cands:
            st.write(f"**{label}**： " + " + ".join(keys))

        req_keys = required_keys_for_mark(m)
        st.subheader("オッズ（自動反映＋手修正OK）")

        for k in req_keys:
            st.number_input(
                f"{k} のオッズ",
                min_value=0.01,
                value=float(st.session_state.get(f"odds_{k}", (st.session_state.get("odds_store", {}) or {}).get(k, 1.0))),
                step=0.1,
                format="%.2f",
                key=f"odds_{k}",
                on_change=on_mark_change,  # 手修正しても即判定が更新
            )

        show_debug = st.checkbox("デバッグ（A〜Dの落ち理由も表示）", value=True)

        res = st.session_state.get("result")
        if res:
            st.divider()
            if res.get("status") == "ERR":
                st.error(res.get("message", "入力エラー"))
            elif res["status"] == "SKIP":
                st.error("スルー（条件を満たす3点セットがありません）")
            else:
                st.success(f"購入（採用パターン：{res['label']}）")
                st.write("### 買い目（3連複3点）")
                for k, o, stak, ret in zip(res["keys"], res["odds"], res["stakes"], res["returns"]):
                    st.write(f"- **{k}**　オッズ: {o:.2f}　購入: {stak}円　払戻目安: {int(round(ret))}円")
                st.write(f"**合計：{sum(res['stakes'])}円 / 最小払戻：{int(round(res['min_return']))}円**")

            if show_debug:
                st.write("### DEBUG（候補A〜D）")
                for label, keys, status, meta in res.get("debug", []):
                    if status == "NO_ODDS":
                        st.write(f"- {label}: {' + '.join(keys)} → NO_ODDS（不足: {meta.get('missing')}）")
                    else:
                        st.write(f"- {label}: {' + '.join(keys)} → NG（needs_sum={meta.get('needs_sum')} / needs={meta.get('needs')}）")

        # オッズストア状況
        store = st.session_state.get("odds_store", {}) or {}
        if store:
            st.caption(f"取り込み済みオッズ件数: {len(store)}（src={st.session_state.get('last_src','')}）")

    except Exception as e:
        st.error(f"入力エラー：{e}")
else:
    st.info("印を入力するか、KEIRIN.JPから「送る」で開いてください。")
