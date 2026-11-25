#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
select_subset.py —— 从 winebench.json(4,598 个函数)里按规则抽取评测子集。只读输入,结果写到新目录,不改任何已有文件。

规则(都可用参数改):
  1. 代码行数(含签名的总行数 loc.total)>= --min-loc              默认 15
  2. 测试数 > --min-tests 且 <= --max-tests                        默认 10 < 测试数 <= 50
     测试数用哪个口径由 --tests-field 决定:own = 本模块测试(默认),all = 全部测试
  3. 某个一级分类按 1、2 筛完不足 --target 个(默认 10)时,只对这个分类逐级降低测试数下限
     (10 → 9 → 8 … → 0),行数门槛和测试数上限不变,直到够 --target 个或降到 0 为止。
     原本就达标的全部保留;新放进来的按测试数从高到低补,补到 --target 个为止;
     最后一级如果有多个测试数相同的候选,用固定随机种子(--seed)从中抽。
  4. 达标数量已经 >= --target 的分类全部保留,不做抽样(加 --cap-per-category N 可以把每类限制到 N 个)。

用法:
  python3 select_subset.py --json winebench.json --out ./subset
  python3 select_subset.py --json winebench.json --out ./subset_all50 --max-tests-field all     # 上限按"全部测试"算

输出(都在 --out 目录下):
  winebench_subset.json     子集样本,结构与 winebench.json 相同,每条多一个 "subset" 字段(入选方式、该分类实际用的下限)
  winebench_subset.csv      一行一个函数的清单(不含函数体)
  subset_summary.txt        每个分类的数量、实际用的下限、子集的基本统计
只依赖 Python 3 标准库。
"""
import argparse, collections, csv, json, os, random, statistics, sys, time

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--json", required=True, help="winebench.json")
ap.add_argument("--out", default="./subset")
ap.add_argument("--min-loc", type=int, default=15, help="代码行数下限(含),默认 15")
ap.add_argument("--min-tests", type=int, default=10, help="测试数下限(不含),默认 10,即测试数 > 10")
ap.add_argument("--max-tests", type=int, default=50, help="测试数上限(含),默认 50;0 表示不设上限")
ap.add_argument("--tests-field", choices=["own", "all"], default="own", help="下限用哪个测试数:own = 本模块测试(默认),all = 全部测试")
ap.add_argument("--max-tests-field", choices=["own", "all", "same"], default="same", help="上限用哪个测试数,默认与 --tests-field 相同")
ap.add_argument("--target", type=int, default=10, help="每个一级分类至少要有多少个样本,默认 10")
ap.add_argument("--cap-per-category", type=int, default=0, help="每个一级分类最多保留多少个(0 = 不限);超出时按测试数从高到低取,并列随机")
ap.add_argument("--seed", type=int, default=20261125, help="随机种子(只在测试数并列时用到)")
A = ap.parse_args()
T0 = time.time()
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

FIELD = {"own": "n_tests_own", "all": "n_tests"}
LOW = FIELD[A.tests_field]
HIGH = FIELD[A.tests_field if A.max_tests_field == "same" else A.max_tests_field]
OUT = os.path.abspath(A.out); os.makedirs(OUT, exist_ok=True)

log(f"读取 {A.json}")
with open(A.json, encoding="utf-8") as f: DATA = json.load(f)
S = DATA["samples"]
log(f"共 {len(S)} 个函数")
log(f"规则:行数 >= {A.min_loc};{A.min_tests} < {LOW} " + (f"且 {HIGH} <= {A.max_tests}" if A.max_tests else "(无上限)") + f";每类至少 {A.target} 个,不足时降低下限")

def under_cap(s): return (not A.max_tests) or s["tests"][HIGH] <= A.max_tests
cats = [k for k, _ in collections.Counter(s["category"]["l1"] for s in S).most_common()]
rng = random.Random(A.seed)
chosen = []; report = []
for ci, c in enumerate(cats, 1):
    in_cat = [s for s in S if s["category"]["l1"] == c]
    pool = [s for s in in_cat if s["loc"]["total"] >= A.min_loc and under_cap(s)]          # 行数和上限不放宽
    base = [s for s in pool if s["tests"][LOW] > A.min_tests]
    picked = [(s, "base") for s in base]; bound = A.min_tests; avail = len(base)
    if len(base) < A.target:
        t = A.min_tests
        while len(picked) < A.target and t > 0:
            t -= 1
            level = [s for s in pool if s["tests"][LOW] == t + 1]                           # 这一级新放进来的(测试数恰好为 t+1)
            avail += len(level)
            if not level: continue
            level.sort(key=lambda s: s["id"]); rng.shuffle(level)                             # 同一级内测试数相同,随机顺序(种子固定)
            need = A.target - len(picked)
            picked += [(s, "topup") for s in level[:need]]
            bound = t
    if A.cap_per_category and len(picked) > A.cap_per_category:
        picked.sort(key=lambda p: p[0]["id"]); rng.shuffle(picked)
        picked.sort(key=lambda p: (p[1] != "base", -p[0]["tests"][LOW]))
        picked = picked[:A.cap_per_category]
    n_base = sum(1 for _, how in picked if how == "base")
    report.append(dict(cat=c, total=len(in_cat), pool=len(pool), base=len(base), bound=bound, avail=avail, final=len(picked), topup=len(picked) - n_base))
    for s, how in picked:
        t = collections.OrderedDict(s); t["subset"] = {"selected_by": how, "lower_bound_used": bound, "tests_field": LOW}
        chosen.append(t)
    log(f"[{ci}/{len(cats)}] {c}:达标 {len(base)} 个" + (f",下限降到 > {bound},可选 {avail} 个,补到 {len(picked)} 个" if len(base) < A.target else f",全部保留") )

chosen.sort(key=lambda s: (cats.index(s["category"]["l1"]), s["dll"], s["name"]))
meta = collections.OrderedDict((k, v) for k, v in DATA.items() if k != "samples")
meta["subset_rule"] = dict(min_loc=A.min_loc, min_tests_exclusive=A.min_tests, max_tests_inclusive=A.max_tests, lower_bound_field=LOW, upper_bound_field=HIGH,
                           target_per_category=A.target, cap_per_category=A.cap_per_category, seed=A.seed, source=os.path.basename(A.json), n_source=len(S), n_subset=len(chosen))
meta["samples"] = chosen
with open(os.path.join(OUT, "winebench_subset.json"), "w", encoding="utf-8") as f: json.dump(meta, f, ensure_ascii=False, indent=1)
log(f"写出 winebench_subset.json:{len(chosen)} 个样本")

cols = ["id", "name", "dll", "category_l1", "category_l2", "loc_total", "loc_code", "cyclomatic", "n_tests_own", "n_tests", "n_tests_other", "n_test_dirs",
        "selected_by", "lower_bound_used", "path", "line_start", "line_end", "return_type", "n_params", "n_api_callees", "uses_wineserver", "unix_side", "doc_url", "signature"]
with open(os.path.join(OUT, "winebench_subset.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(cols)
    for s in chosen:
        w.writerow([s["id"], s["name"], s["dll"], s["category"]["l1"], s["category"]["l2"], s["loc"]["total"], s["loc"]["code"], s["cyclomatic"],
                    s["tests"]["n_tests_own"], s["tests"]["n_tests"], s["tests"]["n_tests_other"], s["tests"]["n_dirs"], s["subset"]["selected_by"], s["subset"]["lower_bound_used"],
                    s["location"]["path"], s["location"]["line_start"], s["location"]["line_end"], s["return_type"], s["n_params"], len(s["api_callees"]),
                    s["uses_wineserver"], s["unix_side"], s["doc"].get("url", ""), s["signature"]])
log("写出 winebench_subset.csv")

def dist(v):
    v = sorted(v)
    q = lambda p: v[min(len(v) - 1, int(p * len(v)))]
    return f"最小 {v[0]}  25% {q(.25)}  中位数 {statistics.median(v):g}  75% {q(.75)}  90% {q(.9)}  最大 {v[-1]}  平均 {statistics.mean(v):.1f}"
with open(os.path.join(OUT, "subset_summary.txt"), "w", encoding="utf-8") as f:
    def P(s=""):
        print(s, flush=True); f.write(s + "\n")
    P(f"WineBench 子集:{len(chosen)} 个函数(来源 {os.path.basename(A.json)},{len(S)} 个)")
    P(f"规则:行数 >= {A.min_loc};{A.min_tests} < {LOW}" + (f";{HIGH} <= {A.max_tests}" if A.max_tests else ";无上限") + f";每个一级分类至少 {A.target} 个,不足时只降低该分类的测试数下限;随机种子 {A.seed}")
    P()
    P(f"{'一级分类':<42}{'全集':>6}{'行数和上限内':>8}{'达标':>6}{'实际下限':>8}{'可选':>6}{'入选':>6}{'其中补入':>6}")
    for r in report:
        P(f"{r['cat']:<42}{r['total']:>8}{r['pool']:>12}{r['base']:>8}{('> ' + str(r['bound'])):>10}{r['avail']:>8}{r['final']:>8}{r['topup']:>8}")
    P(f"{'合计':<42}{sum(r['total'] for r in report):>8}{sum(r['pool'] for r in report):>12}{sum(r['base'] for r in report):>8}{'':>10}{'':>8}{sum(r['final'] for r in report):>8}{sum(r['topup'] for r in report):>8}")
    short = [r["cat"] for r in report if r["final"] < A.target]
    if short: P(f"注意:以下分类把下限降到 0 仍不足 {A.target} 个:{', '.join(short)}")
    P()
    if chosen:
        P("行数(loc.total)      " + dist([s["loc"]["total"] for s in chosen]))
        P("圈复杂度              " + dist([s["cyclomatic"] for s in chosen]))
        P("本模块测试数          " + dist([s["tests"]["n_tests_own"] for s in chosen]))
        P("全部测试数            " + dist([s["tests"]["n_tests"] for s in chosen]))
        dl = collections.Counter(s["dll"] for s in chosen)
        P(f"模块数:{len(dl)};最多的 10 个:" + ", ".join(f"{k} {v}" for k, v in dl.most_common(10)))
        P(f"调用了其他 Wine 导出函数的:{sum(1 for s in chosen if s['api_callees'])} 个;Unix 侧实现的:{sum(1 for s in chosen if s['unix_side'])} 个;直接请求 wineserver 的:{sum(1 for s in chosen if s['uses_wineserver'])} 个")
        P(f"全部测试数超过 {A.max_tests or 50} 的(上限按 {HIGH} 算,所以可能仍有):{sum(1 for s in chosen if s['tests']['n_tests'] > (A.max_tests or 50))} 个")
log(f"完成,用时 {time.time() - T0:.1f}s。输出目录:{OUT}")
