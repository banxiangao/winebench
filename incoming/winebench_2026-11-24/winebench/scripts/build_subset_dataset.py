#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_subset_dataset.py —— 把 select_subset.py 抽出的子集做成和 wine500_doc 相同格式的数据集
(一个函数一个 NNNN_<模块>_<函数名>.json,外加 docs/、manifest.json、pipeline.log)。

做法:不重新实现,直接调用 wine_bench/scripts 里原来的 build_benchmark.py(build_record / add_deps,libclang 依赖分析),
只替换三处输入:
  1. 抽哪些函数      —— 不再随机抽,用 winebench_subset.json 里的函数,顺序和编号按子集文件;
  2. native_tests    —— 不再用 rg 搜函数名,用 WineBench 新方案确认过的"本模块测试文件"
                         (测试源码里直接调用、非 todo、relay 确认执行过);
  3. docs            —— 用 WineBench 的文档索引(msdocs_index.csv)找页面,格式与 fetch_docs.py attach 写出的一致。
每条记录在原有字段之外多一个 "winebench" 字段(功能分类、行数、测试数、测试函数清单、入选方式),原字段的含义不变。

只读输入;输出写到 --out 指定的新目录,该目录里已有的 NNNN_*.json 会跳过(可断点续跑,--force 重做)。

用法(在自己的机器上):
  # 生成 libclang 需要的头文件(只需一次,不改 Wine 源码树):
  sh ../wine_bench/scripts/setup_wine_build.sh ../wine ./deps_build
  pip install libclang
  python3 build_subset_dataset.py --subset subset/winebench_subset.json --src ../wine --build ./deps_build \\
      --scripts ../wine_bench/scripts --docs-index msdocs_index.csv --docs-cache subset/subset_docs_cache.json \\
      --out ../wine_agent/dataset/winebench205_doc

文档页面正文的来源二选一:--docs-cache(随子集一起给出的缓存文件,不需要联网),或 --msdocs(build_doc_index.py 克隆的仓库目录)。
"""
import argparse, collections, csv, json, os, re, sys, time

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--subset", required=True, help="select_subset.py 输出的 winebench_subset.json")
ap.add_argument("--src", required=True, help="Wine 源码根目录")
ap.add_argument("--build", required=True, help="setup_wine_build.sh 生成的目录(含 widl 生成的头文件和 config.h)")
ap.add_argument("--scripts", required=True, help="wine_bench/scripts 目录(含 build_benchmark.py、wine_deps.py、wine_locate.py)")
ap.add_argument("--docs-index", required=True, help="msdocs_index.csv")
ap.add_argument("--docs-cache", default="", help="文档正文缓存(json);有它就不需要 --msdocs")
ap.add_argument("--msdocs", default="", help="微软文档仓库所在目录(其下有 sdk-api、windows-driver-docs-ddi、cpp-docs、win32)")
ap.add_argument("--save-docs-cache", default="", help="把本次用到的文档正文另存成缓存文件")
ap.add_argument("--out", required=True, help="输出目录(新目录)")
ap.add_argument("--max-pages", type=int, default=2, help="每个函数最多附几页文档(与 fetch_docs.py 的默认值相同)")
ap.add_argument("--no-deps", action="store_true", help="不做依赖分析,只定位、取代码和编译上下文(仍需能 import libclang)")
ap.add_argument("--force", action="store_true", help="重做输出目录里已有的记录")
ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个(调试用)")
A = ap.parse_args()
T0 = time.time()
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

SRC = os.path.realpath(os.path.expanduser(A.src)); BUILD = os.path.realpath(os.path.expanduser(A.build)); OUT = os.path.abspath(A.out)
os.makedirs(os.path.join(OUT, "docs"), exist_ok=True)
os.environ.setdefault("WINE_BENCH_KEEP_PARSE_ERRORS", "1")     # 子集的函数是定好的:解析有报错也保留记录,报错数记在 meta.parse_errors
os.environ["WINE_SRC"] = SRC
sys.path.insert(0, os.path.abspath(os.path.expanduser(A.scripts)))
import wine_locate as WL
WL.ROOT = SRC
try:
    import wine_deps as WD
    import build_benchmark as BB
except Exception as e:
    sys.exit(f"无法导入原流水线({type(e).__name__}: {e})。请确认 --scripts 指向 wine_bench/scripts,并已 pip install libclang。")
WD.SRC = SRC; WD.BUILD = BUILD

log(f"Wine 源码:{SRC}")
log(f"生成头文件目录:{BUILD}" + ("" if os.path.isfile(os.path.join(BUILD, "include", "config.h")) else "  !! 没找到 include/config.h,先运行 setup_wine_build.sh"))
with open(A.subset, encoding="utf-8") as f: SUB = json.load(f)
S = SUB["samples"]
if A.limit: S = S[:A.limit]
log(f"子集:{len(S)} 个函数;输出目录:{OUT}")

# ───────────────────────── 文档 ─────────────────────────
REPO = {"win32": "sdk-api", "ddi": "windows-driver-docs-ddi", "crt": "cpp-docs", "win32-conceptual": "win32", "win32-gdiplus-flat": "win32"}
PREF = {"win32": 0, "ddi": 1, "crt": 2, "win32-conceptual": 3, "win32-gdiplus-flat": 4}
csv.field_size_limit(10 ** 9)
by_name = collections.defaultdict(list); by_url = {}
with open(A.docs_index, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        by_name[r["name_lower"]].append(r); by_url.setdefault(r["url"], r)
log(f"文档索引:{len(by_name)} 个函数名")
CACHE = {}
if A.docs_cache and os.path.isfile(A.docs_cache):
    with open(A.docs_cache, encoding="utf-8") as f: CACHE = json.load(f)
    log(f"文档缓存:{len(CACHE)} 页")
USED = {}
def page_text(repo, path):
    k = f"{repo}:{path}"
    if k not in CACHE:
        p = os.path.join(A.msdocs, repo, path) if A.msdocs else ""
        if not p or not os.path.isfile(p): return None
        with open(p, encoding="utf-8", errors="ignore") as f: CACHE[k] = f.read()
    USED[k] = CACHE[k]
    return CACHE[k]
def flat_excerpt(text, name):
    """GDI+ flat API 的文档是一张几百行的大表(一页几十到两百 KB),每个函数只占一行。只取页面的说明文字、表头和这个函数所在的行。"""
    L = text.split("\n")
    first = next((i for i, l in enumerate(L) if l.lstrip().startswith("|")), None)
    if first is None: return text
    rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"\s*\(")
    rows = [l for l in L[first + 2:] if l.lstrip().startswith("|") and rx.search(l.split("|")[1] if l.count("|") > 1 else l)]
    if not rows: return text
    return "\n".join(L[:first] + L[first:first + 2] + rows) + "\n"
def docs_for(s, rid):
    name = s["name"]; rows = []
    url0 = s["doc"].get("url", "")
    r0 = next((r for r in by_name.get(name.lower(), []) if r["url"] == url0), None) or by_url.get(url0)
    if r0: rows.append(r0)                                                    # WineBench 选中的那一页放第一(可能是按别名匹配到的,如 NtCreateKey → ZwCreateKey)
    for r in sorted(by_name.get(name.lower(), []), key=lambda r: (PREF.get(r["source"], 9), r["url"])):
        if all(r["url"] != x["url"] for x in rows): rows.append(r)
    out = []
    for r in rows[:A.max_pages]:
        repo = REPO.get(r["source"], r["source"]); text = page_text(repo, r["doc_path"])
        if text is None: continue
        d = collections.OrderedDict(repo=repo, header=r["header"], path=r["doc_path"], url=r["url"], documented_name=r["name_lower"])
        if r["source"] == "win32-gdiplus-flat":
            full = len(text); text = flat_excerpt(text, name)
            d["excerpt"] = dict(note="GDI+ flat API page: one table row per function; only the page introduction, the table header and this function's row are kept", full_page_chars=full)
        fn = f"{rid}_{repo}_{os.path.basename(r['doc_path'])}"
        with open(os.path.join(OUT, "docs", fn), "w", encoding="utf-8") as f: f.write(text)
        d["file"] = "docs/" + fn; d["text"] = text
        out.append(d)
    return out

# ───────────────────────── 逐个函数 ─────────────────────────
def own_test_files(s):
    return sorted(f"{d['dir']}/{f}" for d in s["tests"]["dirs"] if d["own"] for f in d["files"])
def locate(s):
    """用原来的 wine_locate 解析导出 → 实现位置,并和 WineBench 记录的位置核对。返回 (导出模块, chain, hit, 备注)。"""
    name = s["name"]; path = s["location"]["path"]; line = s["location"]["line_start"]
    own_mods = [d["dir"].split("/")[1] for d in s["tests"]["dirs"] if d["own"]]
    exp_mods = [e.rsplit(".", 1)[0] for e in s["exports"] if e.rsplit(".", 1)[1] == name]
    order = []
    for m in own_mods + [s["dll"]] + exp_mods:
        if m not in order and m in exp_mods: order.append(m)
    best = None
    for m in order:
        chain, hits = WL.resolve(m, name)
        for h in hits:
            if "(macro)" in h: continue
            hf, hl = h.rsplit(":", 1); hl = int(hl)
            if hf == path and (best is None or abs(hl - line) < abs(best[3] - line)): best = (m, chain, h, hl)
        if best and best[3] == line: break
    if best: return best[0], best[1], best[2], ("" if best[3] == line else f"line differs: wine_locate {best[3]} vs WineBench {line}")
    cname = s["id"].split(".", 1)[1]
    return s["dll"], [f"{s['dll']}!{cname} [located by WineBench]"], f"{path}:{line}", "wine_locate could not resolve this export; location taken from WineBench"

plog = open(os.path.join(OUT, "pipeline.log"), "a", encoding="utf-8")
manifest = []; n_done = n_skip = n_nodeps = n_perr = n_nodoc = 0; notes = []
existing = {f[:4]: f for f in os.listdir(OUT) if re.match(r"\d{4}_.*\.json$", f)}
for i, s in enumerate(S, 1):
    rid = f"{i:04d}"; t1 = time.time()
    if rid in existing and not A.force:
        with open(os.path.join(OUT, existing[rid]), encoding="utf-8") as f: rec = json.load(f)
        n_skip += 1
    else:
        mod, chain, hit, note = locate(s)
        tests = own_test_files(s)
        BB.test_mentions = lambda src_, name_, modules_, _t=tests: list(_t)   # native_tests 用新方案确认过的本模块测试文件
        try:
            rec, why = BB.build_record(SRC, i, mod, s["name"], chain, hit, 0, True, None)
        except Exception as e:
            rec, why = None, f"exception: {type(e).__name__}: {e}"
        if rec is None:
            plog.write(f"FAIL {rid} {s['id']}: {why}\n"); plog.flush(); notes.append(f"{rid} {s['id']}: 未生成({why})")
            log(f"[{i}/{len(S)}] {s['id']}:失败 —— {why}"); continue
        rec["docs"] = docs_for(s, rid)
        if not rec["docs"]: n_nodoc += 1
        if not A.no_deps:
            try:
                r2, why = BB.add_deps(SRC, rec)
            except Exception as e:
                r2, why = None, f"exception: {type(e).__name__}: {e}"
            if r2 is None:
                rec["meta"] = dict(deps_analysed=False, deps_error=why); n_nodeps += 1; notes.append(f"{rid} {s['id']}: 依赖分析失败({why})")
        fn_ = rec["function"]; ws = s["location"]["line_start"]
        if fn_["file"] == s["location"]["path"] and ws < fn_["start_line"] <= ws + 3 and fn_["end_line"] == s["location"]["line_end"]:
            # 返回类型单独占一行的写法(INT WINAPI \n ImageList_Add (...)):wine_locate 从函数名那一行算起,会丢掉返回类型,这里补回来
            path_ = os.path.join(SRC, fn_["file"])
            fn_["start_line"] = ws; fn_["signature"] = BB.signature(path_, ws); fn_["code"] = BB.block_text(path_, ws, fn_["end_line"])
            note = f"return type is on its own line: start_line moved from wine_locate's line to {ws} so that signature and code include it"
        if note: rec["meta"]["locate_note"] = note; notes.append(f"{rid} {s['id']}: {note}")
        rec["native_tests"].update(source="WineBench: own-module test files with a direct, non-todo call confirmed by the relay trace",
                                   n_test_functions=s["tests"]["n_tests_own"])
        rec["winebench"] = collections.OrderedDict(
            id=s["id"], category=s["category"], loc=s["loc"], cyclomatic=s["cyclomatic"], return_type=s["return_type"], n_params=s["n_params"],
            tests=dict(n_tests_own=s["tests"]["n_tests_own"], n_tests=s["tests"]["n_tests"], n_tests_other=s["tests"]["n_tests_other"],
                       own_test_functions=[t for t in s["tests"]["list"] if t.split("::")[0] in set(tests)]),
            doc=s["doc"], exports=s["exports"], subset=s["subset"])
        fname = f"{rid}_{rec['function']['module']}_{re.sub(r'[^A-Za-z0-9_]', '_', rec['function']['name'])}.json"
        text = json.dumps(rec, indent=1, ensure_ascii=False)                  # 先序列化再写,避免留下半个文件
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f: f.write(text)
        existing[rid] = fname; n_done += 1
        pe = rec["meta"].get("parse_errors", 0) or 0
        if pe: n_perr += 1
        plog.write(f"OK {rid} {mod}!{s['name']} -> {fname} ({time.time() - t1:.1f}s; parse_errors {pe}; docs {len(rec['docs'])})\n"); plog.flush()
        el = time.time() - T0
        log(f"[{i}/{len(S)}] {rec['function']['module']}!{rec['function']['name']}:同文件依赖 {len(rec.get('same_file_dependencies', []))} 个,文档 {len(rec['docs'])} 页,"
            f"测试文件 {len(tests)} 个" + (f",解析报错 {pe}" if pe else "") + f"  ({time.time() - t1:.1f}s,已用 {el:.0f}s,预计还需 {el / max(1, n_done) * (len(S) - i):.0f}s)")
    fn = rec["function"]
    manifest.append(collections.OrderedDict(
        id=rec["id"], file=existing[rid], module=fn["module"], export_name=fn["export_name"], name=fn["name"],
        source=f"{fn['file']}:{fn['start_line']}-{fn['end_line']}", side=fn["side"], deps_analysed=rec.get("meta", {}).get("deps_analysed", True),
        docs=len(rec.get("docs", [])), category_l1=rec.get("winebench", {}).get("category", {}).get("l1", ""),
        n_tests_own=rec.get("winebench", {}).get("tests", {}).get("n_tests_own", 0), selected_by=rec.get("winebench", {}).get("subset", {}).get("selected_by", "")))
with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(collections.OrderedDict(count=len(manifest), source=os.path.basename(A.subset), subset_rule=SUB.get("subset_rule"), records=manifest), f, indent=1, ensure_ascii=False)
if A.save_docs_cache:
    with open(A.save_docs_cache, "w", encoding="utf-8") as f: json.dump(USED, f, ensure_ascii=False)
    log(f"文档缓存已保存:{A.save_docs_cache}({len(USED)} 页)")
plog.close()
log(f"完成:{len(manifest)} 条记录(本次新生成 {n_done},已存在跳过 {n_skip});未生成 {len(S) - len(manifest)};"
    f"依赖分析失败 {n_nodeps};有解析报错 {n_perr};没有文档页 {n_nodoc};用时 {time.time() - T0:.0f}s")
if notes:
    log("需要留意的记录:")
    for n in notes: print("    " + n, flush=True)
log(f"输出目录:{OUT}")
