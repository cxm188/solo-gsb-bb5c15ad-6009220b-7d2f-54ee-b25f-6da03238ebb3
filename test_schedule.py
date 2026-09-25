"""执行顺序规划(solve_schedule)的端到端逻辑测试(纯标准库)。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

import solver
from solver import solve, solve_failover, solve_schedule, ScheduleValidationError
from demo import DEMO_NETWORK

PASS, FAIL = 0, 0

def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {extra}")

# ---------- 1. 示例管网: 同暴露量时按编号字典序 ----------
print("== 1. 示例管网 tie-break ==")
res = solve(DEMO_NETWORK)
assert res["feasible"] and res["closed_valves"] == ["V2", "V4"], res["closed_valves"]
sch = solve_schedule(DEMO_NETWORK, res["closed_valves"],
                     {"V2": 4, "V4": 5}, {"L": 10})
check("顺序为字典序 [V2, V4]", sch["order"] == ["V2", "V4"], sch["order"])
check("总耗时 9", sch["total_duration"] == 9)
check("累计暴露量 90 (两顺序暴露相同->tie)", sch["total_exposure"] == 90,
      sch["total_exposure"])
s1, s2 = sch["steps"]
check("step1 起止 0->4", (s1["start"], s1["end"]) == (0, 4))
check("step1 操作期间 L 仍通水, 暴露 40", s1["step_exposure"] == 40)
check("step1 完成后 L 仍通水(旁路 s6)",
      [l["id"] for l in s1["flowing_leaks_after"]] == ["L"])
check("step1 无刚隔离漏点", s1["newly_isolated_leaks"] == [])
check("step2 起止 4->9", (s2["start"], s2["end"]) == (4, 9))
check("step2 刚隔离 L", [l["id"] for l in s2["newly_isolated_leaks"]] == ["L"])
check("step2 后无通水漏点", s2["flowing_leaks_after"] == [])
check("step2 累计 90", s2["cumulative_exposure"] == 90)
check("初始通水漏点 [L]", [l["id"] for l in sch["initial_flowing_leaks"]] == ["L"])

# ---------- 2. 顺序影响暴露量: 重权重漏点应先被隔离 ----------
print("== 2. 顺序优化 ==")
net2 = {
    "nodes": [
        {"id": "S", "role": "inlet"},
        {"id": "L1", "role": "leak"},
        {"id": "L2", "role": "leak"},
    ],
    "segments": [
        {"id": "a", "endpoint_a": "S", "endpoint_b": "L1"},
        {"id": "b", "endpoint_a": "S", "endpoint_b": "L2"},
    ],
    "valves": [
        {"id": "V1", "segment_id": "a", "cost": 1},
        {"id": "V2", "segment_id": "b", "cost": 1},
    ],
}
res2 = solve(net2)
assert res2["closed_valves"] == ["V1", "V2"]
sch2 = solve_schedule(net2, res2["closed_valves"],
                      {"V1": 10, "V2": 1}, {"L1": 1, "L2": 100})
check("先关 V2(重权重 L2 尽早隔离)", sch2["order"] == ["V2", "V1"], sch2["order"])
check("暴露量 1*101 + 10*1 = 111", sch2["total_exposure"] == 111,
      sch2["total_exposure"])
check("step1 刚隔离 L2", [l["id"] for l in sch2["steps"][0]["newly_isolated_leaks"]] == ["L2"])
check("step1 后仍通水 [L1]", [l["id"] for l in sch2["steps"][0]["flowing_leaks_after"]] == ["L1"])

# ---------- 3. 多进水点连通性 ----------
print("== 3. 多进水点 ==")
net3 = {
    "nodes": [
        {"id": "S1", "role": "inlet"},
        {"id": "S2", "role": "inlet"},
        {"id": "M", "role": "normal"},
        {"id": "L", "role": "leak"},
    ],
    "segments": [
        {"id": "a", "endpoint_a": "S1", "endpoint_b": "M"},
        {"id": "b", "endpoint_a": "S2", "endpoint_b": "M"},
        {"id": "c", "endpoint_a": "M", "endpoint_b": "L"},
    ],
    "valves": [
        {"id": "V1", "segment_id": "a", "cost": 5},
        {"id": "V2", "segment_id": "b", "cost": 5},
        {"id": "V3", "segment_id": "c", "cost": 1},
    ],
}
res3 = solve(net3)
check("最优方案只关 V3", res3["closed_valves"] == ["V3"], res3["closed_valves"])
sch3 = solve_schedule(net3, res3["closed_valves"], {"V3": 7}, {"L": 3})
check("单步暴露 21", sch3["total_exposure"] == 21)
check("单步后 L 隔离", sch3["steps"][0]["flowing_leaks_after"] == [])

# 多进水点: 漏点经两条独立通路连两个进水点, 需关两阀
net3b = {
    "nodes": [
        {"id": "S1", "role": "inlet"},
        {"id": "S2", "role": "inlet"},
        {"id": "L", "role": "leak"},
    ],
    "segments": [
        {"id": "a", "endpoint_a": "S1", "endpoint_b": "L"},
        {"id": "b", "endpoint_a": "S2", "endpoint_b": "L"},
    ],
    "valves": [
        {"id": "V1", "segment_id": "a", "cost": 1},
        {"id": "V2", "segment_id": "b", "cost": 1},
    ],
}
res3b = solve(net3b)
sch3b = solve_schedule(net3b, res3b["closed_valves"],
                       {"V1": 2, "V2": 3}, {"L": 5})
check("关第一阀后 L 仍经另一进水点通水",
      [l["id"] for l in sch3b["steps"][0]["flowing_leaks_after"]] == ["L"])
check("两步都完成才隔离, 暴露 (2+3)*5=25", sch3b["total_exposure"] == 25)

# ---------- 4. 校验错误 ----------
print("== 4. 录入校验 ==")
def expect_errors(name, dur, w, needles):
    try:
        solve_schedule(DEMO_NETWORK, ["V2", "V4"], dur, w)
        check(name, False, "未抛出 ScheduleValidationError")
    except ScheduleValidationError as exc:
        msg = "\n".join(exc.errors)
        ok = all(n in msg for n in needles)
        check(name, ok, f"缺少关键词 {needles}: {msg}")

expect_errors("遗漏阀门时长", {"V2": 4}, {"L": 10}, ["缺少计划阀门 V4"])
expect_errors("多余阀门编号", {"V2": 4, "V4": 5, "V9": 1}, {"L": 10},
              ["计划清单之外", "V9"])
expect_errors("遗漏漏点权重", {"V2": 4, "V4": 5}, {}, ["缺少漏点 L"])
expect_errors("多余漏点编号", {"V2": 4, "V4": 5}, {"L": 10, "X": 1},
              ["不存在的漏点", "X"])
expect_errors("时长为 0", {"V2": 0, "V4": 5}, {"L": 10}, ["正整数"])
expect_errors("时长为小数", {"V2": 2.5, "V4": 5}, {"L": 10}, ["正整数"])
expect_errors("时长为布尔", {"V2": True, "V4": 5}, {"L": 10}, ["布尔"])
expect_errors("时长为非法字符串", {"V2": "abc", "V4": 5}, {"L": 10}, ["正整数"])
expect_errors("权重为负数", {"V2": 4, "V4": 5}, {"L": -3}, ["正整数"])
expect_errors("durations 非对象", [1, 2], {"L": 10}, ["valve_durations 必须是对象"])
expect_errors("weights 非对象", {"V2": 4, "V4": 5}, "x", ["leak_weights 必须是对象"])

# 合法变体: 整数字符串 / 整数值浮点
sch_ok = solve_schedule(DEMO_NETWORK, ["V2", "V4"], {"V2": "4", "V4": 5.0}, {"L": "10"})
check("数字字符串与整数浮点可接受", sch_ok["total_exposure"] == 90)

# ---------- 5. 空计划(无漏点/无关阀) ----------
print("== 5. 边界 ==")
net5 = {
    "nodes": [{"id": "S", "role": "inlet"}, {"id": "H", "role": "must_keep"}],
    "segments": [{"id": "a", "endpoint_a": "S", "endpoint_b": "H"}],
    "valves": [],
}
res5 = solve(net5)
sch5 = solve_schedule(net5, res5["closed_valves"], {}, {})
check("无漏点无阀门: 0 步, 暴露 0",
      sch5["steps"] == [] and sch5["total_exposure"] == 0 and sch5["order"] == [])

# 漏点本来就隔离(无通路): 权重照录但不产生暴露
net5b = {
    "nodes": [{"id": "S", "role": "inlet"}, {"id": "L", "role": "leak"}],
    "segments": [],
    "valves": [],
}
res5b = solve(net5b)
sch5b = solve_schedule(net5b, res5b["closed_valves"], {}, {"L": 8})
check("本来已隔离漏点列入 already_isolated",
      [l["id"] for l in sch5b["already_isolated_leaks"]] == ["L"]
      and sch5b["initial_flowing_leaks"] == [])

# ---------- 6. 备援方案也可做执行顺序规划 ----------
print("== 6. 备援方案 ==")
net6 = {
    "nodes": [
        {"id": "S", "role": "inlet"}, {"id": "M", "role": "normal"},
        {"id": "L", "role": "leak"}, {"id": "H", "role": "must_keep"},
    ],
    "segments": [
        {"id": "a", "endpoint_a": "S", "endpoint_b": "M"},
        {"id": "b", "endpoint_a": "M", "endpoint_b": "L"},
        {"id": "h", "endpoint_a": "S", "endpoint_b": "H"},
    ],
    "valves": [
        {"id": "V1", "segment_id": "a", "cost": 1},
        {"id": "V2", "segment_id": "b", "cost": 2},
    ],
}
res6 = solve_failover(net6)
assert res6["feasible"] and res6["closed_valves"] == ["V1", "V2"]
sch6 = solve_schedule(net6, res6["closed_valves"], {"V1": 3, "V2": 6}, {"L": 4})
# V1 先关: 3*4 + 6*0 = 12 (V1 关后 L 被 V2 通路... 等等, V1 在 a 上, V2 在 b 上,
# 关 V1 后 S-a-M 断, L 即隔离 => 第二阀暴露 0)
check("备援方案顺序 [V1, V2]", sch6["order"] == ["V1", "V2"], sch6["order"])
check("暴露 12 (关 V1 后 L 已隔离)", sch6["total_exposure"] == 12,
      sch6["total_exposure"])
check("step1 刚隔离 L", [l["id"] for l in sch6["steps"][0]["newly_isolated_leaks"]] == ["L"])
check("step2 暴露 0", sch6["steps"][1]["step_exposure"] == 0)

# ---------- 7. 暴力验证 DP 最优性(全排列对照, 多组随机) ----------
print("== 7. DP vs 暴力全排列 ==")
import itertools, random

def brute(net, closed, dur, w):
    best = None
    best_order = None
    for perm in itertools.permutations(sorted(closed)):
        # 逐步模拟
        total = 0
        done = []
        for v in perm:
            # 当前已关集合 done, 操作 v 期间它仍开
            tmp = dict(net)
            tmp["valves"] = [dict(x) for x in net["valves"]]
            # 用 solver 内部图算仍通水漏点
            nodes, segs, vals = solver.validate_network(tmp)
            g = solver._Graph(nodes, segs, vals)
            mask = 0
            vbit = {x["id"]: b for b, x in enumerate(g.valves_sorted)}
            for d in done:
                mask |= 1 << vbit[d]
            fed = g.reachable(mask, g.inlet_set)
            ws = sum(w[g.nodes[i]["id"]] for i in g.leak_set if (fed >> i) & 1)
            total += dur[v] * ws
            done.append(v)
        if best is None or total < best or (total == best and list(perm) < best_order):
            best = total
            best_order = list(perm)
    return best, best_order

random.seed(42)
for trial in range(30):
    # 随机小管网: 1 进水点 + 若干中继 + 2~3 漏点, 3~6 阀门
    n_mid = random.randint(1, 3)
    nodes = [{"id": "S", "role": "inlet"}]
    nodes += [{"id": f"M{i}", "role": "normal"} for i in range(n_mid)]
    n_leak = random.randint(1, 3)
    nodes += [{"id": f"L{i}", "role": "leak"} for i in range(n_leak)]
    ids = [n["id"] for n in nodes]
    segs = []
    n_seg = random.randint(len(ids) - 1, len(ids) + 2)
    used = set()
    while len(segs) < n_seg:
        a, b = random.sample(ids, 2)
        key = tuple(sorted((a, b)))
        if key in used:
            continue
        used.add(key)
        segs.append({"id": f"p{len(segs)}", "endpoint_a": a, "endpoint_b": b})
    n_valve = random.randint(1, min(6, len(segs)))
    vsegs = random.sample(segs, n_valve)
    valves = [{"id": f"V{k+1}", "segment_id": sg["id"], "cost": random.randint(1, 9)}
              for k, sg in enumerate(vsegs)]
    net = {"nodes": nodes, "segments": segs, "valves": valves}
    r = solve(net)
    if not r["feasible"] or not r["closed_valves"]:
        continue
    closed = r["closed_valves"]
    if len(closed) > 6:
        continue
    dur = {v: random.randint(1, 9) for v in closed}
    w = {f"L{i}": random.randint(1, 9) for i in range(n_leak)}
    sch = solve_schedule(net, closed, dur, w)
    b_exp, b_order = brute(net, closed, dur, w)
    if sch["total_exposure"] != b_exp or sch["order"] != b_order:
        check(f"随机{trial}: DP==暴力", False,
              f"DP=({sch['total_exposure']},{sch['order']}) 暴力=({b_exp},{b_order})")
    else:
        PASS += 1
print(f"  随机对照完成, PASS={PASS}")

# ---------- 8. 只读: 数据库往返后方案不变 ----------
print("== 8. 只读(数据库往返) ==")
import database
tmpdir = tempfile.mkdtemp()
database.DB_PATH = os.path.join(tmpdir, "t.db")
database.init_db()
with database.get_conn() as conn:
    pid = database.save_plan(conn, res, DEMO_NETWORK)
with database.get_conn() as conn:
    plan = database.get_plan(conn, pid)
before = json.dumps(plan, sort_keys=True, ensure_ascii=False)
sch8 = solve_schedule(plan["network_snapshot"], plan["closed_valves"],
                      {"V2": 4, "V4": 5}, {"L": 10})
with database.get_conn() as conn:
    plan2 = database.get_plan(conn, pid)
after = json.dumps(plan2, sort_keys=True, ensure_ascii=False)
check("快照求解+排程后方案记录不变", before == after)
check("快照排程结果与直接计算一致", sch8["total_exposure"] == 90)

print(f"\n==== 结果: PASS={PASS} FAIL={FAIL} ====")
sys.exit(1 if FAIL else 0)
