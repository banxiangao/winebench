#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_winebench.py —— 从 Wine 源码(+ relay 日志 + 微软文档索引)抽取 WineBench 全量表。

每一行是 Wine 里的一个 API 实现函数,给出:
  函数名、所属 DLL、函数签名、函数体、所在文件与起止行号、有多少个测试、测试分布在哪些文件里。

筛选漏斗(每一步的数量写进 funnel.txt;每个函数的各项标记都保留在 winebench_all.jsonl 里,后人可以按自己的口径重新筛):
  [0] 候选   = Wine 各 DLL 的 .spec 导出函数中,被测试源码(dlls/*/tests/*.c、programs/*/tests/*.c)直接调用的那些
               ——"直接调用"按源码判定:测试 .c 文件的函数体里出现 Func(...) 或 pFunc(...)(GetProcAddress 取到的指针)
  [T] 有测试 = 至少有一个"非 todo"的直接调用点,并且(给了 --relay 时)WINEDEBUG=+relay 日志确认这个函数
               在该调用点所在的测试单元(module:subtest = tests/<subtest>.c)运行时确实被调用过
               ——todo 判定:调用点所在语句或其后紧跟的断言全部带 todo_wine 的,记为 todo,不算测试
  [T'] 本模块有测试 = 上述测试里至少有一个位于导出该函数的 DLL 自己的测试目录(dlls/<dll>/tests);
               只被别的模块的测试顺带调用的函数剔除(--keep-no-own-test 可保留)
  [1] 有文档 = 函数名出现在微软官方开源文档索引 msdocs_index.csv 里(build_doc_index.py 生成)
  [2] 完全实现 = (a) .spec 里不是 stub;(b) 能在源码里定位到函数定义;
               (c) 函数体里没有 FIXME、没有 stub / semi-stub 标记

导出 → 实现的解析:
  kernel32.CreateFileW 这类在 .spec 里带 -import 或写明 "otherdll.Name" 的是转发,顺着找到真正实现它的 DLL(如 kernelbase);
  "@ stdcall Name(args) InternalName" 用 InternalName 找定义;-syscall 的在 unix/ 源码里;
  PARENTSRC(如 ucrtbase ← ../msvcrt)按 Makefile.in 解析;只保留对 x86_64 生效的条目,跳过 16 位模块。

输出(--out 目录):
  winebench.json       通过全部筛选的样本(主输出,嵌套结构:签名、函数体、行数、位置、测试及其所在目录、功能分类、文档、辅助信息)
  winebench.csv        同上,摊平成一行一个函数的表
  winebench.xlsx       同上,便于浏览(函数体超过 Excel 单元格上限 32767 字符的会截断,完整内容以 JSON/CSV 为准)
  winebench_all.jsonl  全部候选函数及各项标记、未通过原因(全集)
  funnel.txt           漏斗统计

用法:
  python3 build_winebench.py --wine ~/wine_fuzz/wine --docs msdocs_index.csv --relay ~/relay_results --out ./out
  (--relay 可省略:省略时"有测试"只按源码里的直接调用判定,不做运行确认)
"""
import argparse, collections, csv, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categorize import categorize

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--wine", required=True, help="Wine 源码根目录")
ap.add_argument("--docs", required=True, help="msdocs_index.csv")
ap.add_argument("--relay", default=None, help="relay 结果目录(含 per_unit/*.func.csv 和 summary.json);可省略")
ap.add_argument("--out", default="./winebench_out")
ap.add_argument("--no-xlsx", action="store_true")
ap.add_argument("--keep-no-own-test", action="store_true", help="保留本模块测试目录里没有测试、只被别的模块顺带调用的函数(默认剔除)")
ap.add_argument("--dump-untested", action="store_true",
                help="另外输出 winebench_untested.jsonl:测试源码里没有任何直接调用的导出函数(不进漏斗,只为了能按位置/导出名查到任意函数)")
A = ap.parse_args()
SRC = os.path.abspath(os.path.expanduser(A.wine)); OUT = os.path.abspath(A.out); os.makedirs(OUT, exist_ok=True)
T0 = time.time()
def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def rd(p):
    with open(p, encoding="utf-8", errors="replace") as f: return f.read()

# ───────────────────────── C 源码的轻量解析 ─────────────────────────
_TOK = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
def strip_cs(text):
    """把注释和字符串/字符常量的内容换成空格,长度与换行位置不变(用于结构分析)。"""
    def rep(m):
        s = m.group(0)
        return "".join(c if c == "\n" else " " for c in s)
    return _TOK.sub(rep, text)

ATTR_WORDS = {"__attribute__", "__declspec", "DECLSPEC_ALIGN", "__ASM_CFI", "DECLSPEC_HIDDEN", "__WINE_ALLOC_SIZE", "__WINE_DEALLOC", "__WINE_MALLOC"}
KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "do", "else", "case", "defined"}
_ID_PAREN = re.compile(r"([A-Za-z_]\w*)\s*\(")
_MACRO_LINE = re.compile(r"[A-Z_][A-Z0-9_]*\s*\([^()]*\)")

def parse_functions(text):
    """返回顶层函数定义列表:dict(name, sig, l0, lb, l1, static)。行号从 1 开始;l0=签名首行,lb='{' 所在行,l1='}' 所在行。
    依赖 Wine 的代码风格:定义从第 0 列开始,函数体的 '{' 和 '}' 独占第 0 列。"""
    lines = text.split("\n"); st = strip_cs(text).split("\n"); n = len(lines); out = []; i = 0
    while i < n:
        s = st[i]
        if not s or not (s[0].isalpha() or s[0] == "_"):
            i += 1; continue
        j = i; ok = False
        while j < n and j - i <= 40:
            t = st[j]
            if j > i and t.rstrip() == "{": ok = True; break
            if t.startswith("#") or ";" in t or "{" in t or "}" in t: break
            j += 1
        if not ok: i += 1; continue
        while i < j - 1 and _MACRO_LINE.fullmatch(st[i].strip()): i += 1      # DEFINE_THISCALL_WRAPPER(f, 8) / IMPL_WIREM_HANDLE(HACCEL) 这类独占一行的宏调用不属于后面的函数签名
        hdr = " ".join(x.strip() for x in st[i:j]); hdr_orig = " ".join(x.strip() for x in lines[i:j])
        if "(" not in hdr or "=" in hdr or not hdr.rstrip().endswith(")"):
            i += 1; continue
        depth = 0; name = None; pos = 0
        for m in _ID_PAREN.finditer(hdr):          # 取第一个处于括号深度 0、且不是属性宏的 "标识符("
            depth += hdr.count("(", pos, m.start()) - hdr.count(")", pos, m.start()); pos = m.start()
            if depth == 0 and m.group(1) not in ATTR_WORDS:
                name = m.group(1); break
        if not name or name in KEYWORDS: i += 1; continue
        k = j + 1
        while k < n and not st[k].startswith("}"): k += 1
        if k >= n: break
        if name == "START_TEST": name = re.sub(r"\s+", "", hdr)
        out.append(dict(name=name, sig=re.sub(r"\s+", " ", hdr_orig).strip(), l0=i + 1, lb=j + 1, l1=k + 1,
                        static=bool(re.match(r"\s*(static|inline|__inline)\b", hdr))))
        i = k + 1
    return out

def parse_makefile(path):
    """读 Makefile.in 的变量(处理续行)。"""
    v = {}
    if not os.path.isfile(path): return v
    txt = re.sub(r"\\\n", " ", rd(path))
    for m in re.finditer(r"^([A-Za-z_0-9]+)\s*\+?=\s*(.*)$", txt, re.M):
        v[m.group(1)] = (v.get(m.group(1), "") + " " + m.group(2)).strip()
    return v

# ───────────────────────── 1. 读取所有 .spec ─────────────────────────
log(f"Wine 源码:{SRC}({rd(os.path.join(SRC, 'VERSION')).strip() if os.path.isfile(os.path.join(SRC, 'VERSION')) else '?'})")
SPEC_LINE = re.compile(r"^\s*(@|\d+)\s+(stdcall|cdecl|varargs|thiscall|fastcall|stub|extern|variable|equate|pascal)\b\s*(.*)$")
def arch_ok(flags):
    for f in flags:
        if f == "-i386": return False
        if f.startswith("-arch="):
            items = f[6:].split(",")
            pos = [x for x in items if not x.startswith("!")]; neg = [x[1:] for x in items if x.startswith("!")]
            if pos and not ({"win64", "x86_64"} & set(pos)): return False
            if {"win64", "x86_64"} & set(neg): return False
    return True

exports = {}                       # dll(目录名) -> {导出名: dict(type, flags, target)}
makefiles = {}
dll_dirs = sorted(d for d in os.listdir(os.path.join(SRC, "dlls")) if os.path.isdir(os.path.join(SRC, "dlls", d)))
for d in dll_dirs:
    if re.search(r"(16|\.vxd)$", d): continue                       # 16 位模块
    spec = os.path.join(SRC, "dlls", d, d + ".spec")
    if not os.path.isfile(spec): continue
    makefiles[d] = parse_makefile(os.path.join(SRC, "dlls", d, "Makefile.in"))
    ex = {}
    for line in rd(spec).split("\n"):
        line = line.split("#", 1)[0]
        m = SPEC_LINE.match(line)
        if not m: continue
        ordn, typ, rest = m.group(1), m.group(2), m.group(3).split()
        if typ in ("extern", "variable", "equate", "pascal"): continue
        flags = []
        while rest and rest[0].startswith("-"): flags.append(rest.pop(0))
        if not rest or not arch_ok(flags): continue
        rest = " ".join(rest)
        mm = re.match(r"([^\s(]+)\s*(\([^)]*\))?\s*(\S+)?", rest)
        if not mm: continue
        name, target = mm.group(1), mm.group(3)
        if name == "@" : continue
        if name not in ex or ex[name]["type"] == "stub":
            ex[name] = dict(type=typ, flags=flags, target=target, ord=(ordn if ordn != "@" else None))
    exports[d] = ex
DLLKEY = {d.lower(): d for d in exports}
for d in list(exports): DLLKEY.setdefault(os.path.splitext(d)[0].lower(), d)
log(f"[1/6] .spec:{len(exports)} 个 DLL,{sum(len(v) for v in exports.values())} 个 x86_64 导出条目"
    f"(其中 stub {sum(1 for v in exports.values() for e in v.values() if e['type'] == 'stub')})")

# ───────────────────────── 2. 实现源码索引(按需、带缓存) ─────────────────────────
_file_funcs = {}
def funcs_of_file(path):
    if path not in _file_funcs:
        try: _file_funcs[path] = parse_functions(rd(path))
        except Exception: _file_funcs[path] = []
    return _file_funcs[path]

_dll_sources = {}
def dll_sources(dll):
    """该 DLL 的 C 源文件(Makefile.in 的 SOURCES;本目录没有的到 PARENTSRC 里找)。"""
    if dll in _dll_sources: return _dll_sources[dll]
    base = os.path.join(SRC, "dlls", dll); mk = makefiles.get(dll, {}); res = []
    parent = os.path.normpath(os.path.join(base, mk["PARENTSRC"])) if mk.get("PARENTSRC") else None
    srcs = [s for s in mk.get("SOURCES", mk.get("C_SRCS", "")).split() if s.endswith(".c")]
    if not srcs and os.path.isdir(base): srcs = sorted(f for f in os.listdir(base) if f.endswith(".c"))
    for s in srcs:
        p = os.path.join(base, s)
        if not os.path.isfile(p) and parent: p = os.path.join(parent, s)
        if os.path.isfile(p): res.append(p)
    _dll_sources[dll] = res; return res

_musl = None
def musl_index():
    global _musl
    if _musl is None:
        _musl = collections.defaultdict(list); root = os.path.join(SRC, "libs", "musl", "src")
        for dp, _, fns in os.walk(root):
            for fn in sorted(fns):
                if fn.endswith(".c"):
                    p = os.path.join(dp, fn)
                    for f in funcs_of_file(p): _musl[f["name"]].append((p, f))
    return _musl

_dll_index = {}
def find_impl(dll, cname, syscall=False):
    if dll not in _dll_index:
        idx = collections.defaultdict(list)
        for p in dll_sources(dll):
            for f in funcs_of_file(p): idx[f["name"]].append((p, f))
        _dll_index[dll] = idx
    c = _dll_index[dll].get(cname, [])
    if not c and "MUSL_PE_LIBS" in makefiles.get(dll, {}).get("IMPORTS", ""):       # msvcrt/ucrtbase 的数学函数等来自静态库 libs/musl
        c = musl_index().get(cname, [])
    if not c: return None, 0
    def rank(pf):
        p, f = pf; unix = (os.sep + "unix" + os.sep) in p
        return ("SYSCALL_API" in f["sig"], f["static"], unix != syscall, p, f["l0"])   # 跳过 PE 侧的系统调用跳板(win32u/main.c);非 static 优先;syscall 优先 unix/
    c = sorted(c, key=rank)
    return c[0], len(c)

def resolve(dll, name, depth=0):
    """(dll, 导出名) → ('impl', 实现DLL, C函数名) | ('stub', dll, name) | None"""
    e = exports.get(dll, {}).get(name)
    if e is None or depth > 8: return None
    if e["type"] == "stub": return ("stub", dll, name)
    t = e["target"]
    if t and "." in t:
        d2, n2 = t.rsplit(".", 1); d2 = DLLKEY.get(d2.lower())
        return resolve(d2, n2, depth + 1) if d2 else None
    cname = t or name
    if "-import" in e["flags"]:                               # 显式声明"这个导出其实是导入的";带内部名时按内部名去找
        mk = makefiles.get(dll, {})                            #   (user32: "-import GetKeyState(long) NtUserGetKeyState" → win32u.NtUserGetKeyState)
        for imp in (mk.get("IMPORTS", "") + " " + mk.get("DELAYIMPORTS", "")).split() + ["kernel32", "ntdll"]:   # kernel32/ntdll 是隐式导入(psapi 没写 IMPORTS)
            imp = DLLKEY.get(imp.lower())
            if imp and imp != dll and cname in exports.get(imp, {}) and exports[imp][cname]["type"] != "stub":
                return resolve(imp, cname, depth + 1)
        return None
    if find_impl(dll, cname)[0] is None:                       # 本 DLL 的源码里没有这个函数的定义 → 它是从别的 DLL 导入后原样再导出的
        mk = makefiles.get(dll, {})                            #   (user32 的 PostQuitMessage → win32u.NtUserPostQuitMessage;ole32.WriteClassStg → coml2.WriteClassStg)
        for imp in (mk.get("IMPORTS", "") + " " + mk.get("DELAYIMPORTS", "")).split() + ["ntdll", "kernel32"]:   # ntdll/kernel32 是隐式导入(ntoskrnl.exe 的 Rtl* 等)
            imp = DLLKEY.get(imp.lower())
            if imp and imp != dll and cname in exports.get(imp, {}) and exports[imp][cname]["type"] != "stub":
                r2 = resolve(imp, cname, depth + 1)
                if r2 and r2[0] == "impl": return r2
    return ("impl", dll, cname)

RES = {}                            # (dll, name) -> resolve 结果
name_exporters = collections.defaultdict(list)
aliases = collections.defaultdict(set)   # (实现DLL, C名) -> {"dll.导出名"}
for d, ex in exports.items():
    for nme in ex:
        r = resolve(d, nme); RES[(d, nme)] = r; name_exporters[nme].append(d)
        if r and r[0] == "impl": aliases[(r[1], r[2])].add(f"{d}.{nme}")
log(f"      导出 → 实现:{len(aliases)} 个不同的实现函数(已解析 {len(_file_funcs)} 个源文件)")

FIXME_MACRO = re.compile(r"\bFIXME(?:_\(\w+\))?\s*\(")
FIXME_WORD = re.compile(r"\bFIXME\b|\bfixme\b")
STUB_MARK = re.compile(r"semi[- ]?stub|\bstubs?\s*(?:\\n|!|\")|[:\-(,]\s*stub\b|\bstub\s*\*/|/\*\s*stub\b", re.I)

# ───────────────────────── 3. relay 数据 ─────────────────────────
relay = None; relay_status = {}
if A.relay:
    R = os.path.abspath(os.path.expanduser(A.relay)); relay = {}; relay_total = collections.Counter()
    sm = os.path.join(R, "summary.json")
    if os.path.isfile(sm):
        for u in json.load(open(sm)).get("units", []): relay_status[u["unit"]] = u.get("status", "")
    pu = os.path.join(R, "per_unit"); fl = sorted(f for f in os.listdir(pu) if f.endswith(".func.csv"))
    for k, fn in enumerate(fl, 1):
        unit = fn[:-len(".func.csv")].replace("__", ":", 1); s = set()
        with open(os.path.join(pu, fn), newline="", encoding="utf-8", errors="replace") as f:
            r = csv.reader(f); next(r, None)
            for row in r:
                if len(row) >= 2:
                    k_ = (row[0] + "." + row[1]).lower(); s.add(k_)           # 拼成 "dll.func" 再比较,兼容带扩展名的模块
                    if len(row) >= 3 and row[2].isdigit(): relay_total[k_] += int(row[2])
        relay[unit] = s
        if k % 200 == 0 or k == len(fl): log(f"      relay 单元 {k}/{len(fl)}")
    log(f"[2/6] relay:{len(relay)} 个测试单元的调用记录(状态:{dict(collections.Counter(relay_status.values()))})")
else:
    log("[2/6] 未提供 --relay:只按源码里的直接调用判定是否有测试")

# ───────────────────────── 4. 扫描测试源码里的直接调用点 ─────────────────────────
ASSERT_RE = re.compile(r"\b(?:ok|ok_\w+|expect\w*|todo_wine\w*|check_\w+|test_\w+)\b")
test_dirs = []
for top in ("dlls", "programs"):
    for d in sorted(os.listdir(os.path.join(SRC, top))):
        td = os.path.join(SRC, top, d, "tests")
        if os.path.isdir(td) and os.path.isfile(os.path.join(td, "Makefile.in")): test_dirs.append((top, d, td))
IMPLICIT = ["msvcrt", "kernel32", "ntdll"]
UNIVERSE = set(name_exporters)
# wine.inf 默认写进注册表的 RelayExclude:这几个函数永远不会出现在 relay 日志里
RELAY_EXCLUDE = {"ntdll.rtlentercriticalsection", "ntdll.rtltryentercriticalsection", "ntdll.rtlleavecriticalsection",
                 "kernel32.tlsgetvalue", "kernel32.tlssetvalue", "kernel32.flsgetvalue", "kernel32.flssetvalue", "kernel32.setlasterror"}
def relay_blind(dll_, name_):
    """这个导出在 relay 日志里不可能出现:-norelay,或 varargs(winebuild 只给 stdcall/cdecl 生成 relay 入口),或在默认 RelayExclude 里。"""
    e_ = exports.get(dll_, {}).get(name_)
    return bool(e_ and ("-norelay" in e_["flags"] or e_["type"] == "varargs")) or f"{dll_}.{name_}".lower() in RELAY_EXCLUDE

def msvcrt_header_inlines():
    """include/msvcrt/*.h 里、非 _UCRT 分支下以 static inline 定义的函数名(测试默认链接 msvcrt,用的就是这个分支)。
    测试里直接写 swprintf(buf, size, ...) 时编译进去的是头文件里的内联函数(它调的是 _vsnwprintf),不是 msvcrt.swprintf 这个导出。"""
    out = set(); hd = os.path.join(SRC, "include", "msvcrt")
    if not os.path.isdir(hd): return out
    for fn_ in sorted(os.listdir(hd)):
        if not fn_.endswith(".h"): continue
        stack = []                                       # 每层:True = 当前分支只在 _UCRT 下生效
        for line in strip_cs(rd(os.path.join(hd, fn_))).split("\n"):
            t_ = line.strip()
            if t_.startswith("#"):
                d_ = t_[1:].strip()
                if re.match(r"if(def)?\b", d_):
                    stack.append(("ucrt" if re.match(r"(ifdef\s+_UCRT\b|if\s+defined\s*\(?\s*_UCRT\b)", d_) else
                                  "noucrt" if re.match(r"(ifndef\s+_UCRT\b|if\s+!\s*defined\s*\(?\s*_UCRT\b)", d_) else "other", True))
                elif re.match(r"ifndef\b", d_): stack.append(("noucrt" if re.match(r"ifndef\s+_UCRT\b", d_) else "other", True))
                elif re.match(r"(else|elif)\b", d_) and stack: stack[-1] = (stack[-1][0], False)
                elif re.match(r"endif\b", d_) and stack: stack.pop()
                continue
            if any((k_ == "ucrt" and first) or (k_ == "noucrt" and not first) for k_, first in stack): continue
            m_ = re.match(r"static\s+inline\b[^;{=]*?\b(\w+)\s*\(", t_)
            if m_: out.add(m_.group(1))
    return out
HDR_INLINE = msvcrt_header_inlines()

_DEFINE = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)\(([^)]*)\)(.*)$", re.M)
def macro_call_params(st_text, known=None):
    """函数式宏里"哪个参数被当成函数来调用":#define CONVERT(func, val) ... func(in, &out) → {'CONVERT': {0}}。
    宏把参数再传给另一个这样的宏也算(迭代到不再变化)。known:已知的(头文件里的)宏。"""
    defs = []
    for m in _DEFINE.finditer(re.sub(r"\\\n", "  ", st_text)):
        params = [x.strip() for x in m.group(2).split(",")]
        if params and all(re.fullmatch(r"[A-Za-z_]\w*|\.\.\.", x) for x in params): defs.append((m.group(1), params, m.group(3)))
    out = dict(known or {})
    for _ in range(4):
        changed = False
        for name, params, body in defs:
            idx = set(out.get(name, ()))
            for i, p_ in enumerate(params):
                if p_ == "..." or i in idx: continue
                if re.search(r"(?<![\w.>#])" + re.escape(p_) + r"\s*\(", body): idx.add(i); continue
                for other, oidx in out.items():           # 把参数原样传给另一个"会调用其参数"的宏
                    for mm in re.finditer(r"(?<!\w)" + re.escape(other) + r"\s*\(", body):
                        args = split_args(body, mm.end() - 1)
                        if args and any(j < len(args) and args[j][0].strip() == p_ for j in oidx): idx.add(i)
            if idx != set(out.get(name, ())): out[name] = idx; changed = True
        if not changed: break
    return out
def split_args(text, lp):
    """text[lp] == '(';返回 [(实参文本, 起始偏移)],括号不配对则返回 None。"""
    depth = 0; args = []; start = lp + 1
    for k in range(lp, min(len(text), lp + 4000)):
        ch = text[k]
        if ch in "([{": depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0: args.append((text[start:k], start)); return args
        elif ch == "," and depth == 1: args.append((text[start:k], start)); start = k + 1
    return None
def fnptr_params(sig, body_text):
    """测试文件里的辅助函数:哪个形参是函数指针、并且在函数体里被调用了。static void check(HRESULT (WINAPI *fn)(...), ...) { ... fn(...) } → {0}"""
    lp = sig.find("(")
    args = split_args(sig, lp) if lp >= 0 else None
    out = set()
    for i, (a_, _) in enumerate(args or []):
        m = re.search(r"\(\s*(?:\w+\s+)*\*\s*(\w+)\s*\)\s*\(", a_)
        if m and re.search(r"(?<![\w.>])" + re.escape(m.group(1)) + r"\s*\(", body_text): out.add(i)
    return out
sites = collections.defaultdict(list)      # 实现键 或 ('stub',dll,name) -> [dict(调用点)]
n_files = n_sites = n_amb = n_indirect = n_aux_files = 0
for ti, (top, d, td) in enumerate(test_dirs, 1):
    mk = parse_makefile(os.path.join(td, "Makefile.in"))
    testdll = DLLKEY.get(os.path.splitext(mk.get("TESTDLL", d))[0].lower()) or DLLKEY.get(mk.get("TESTDLL", d).lower()) or DLLKEY.get(d.lower())
    imports = [DLLKEY[x.lower()] for x in mk.get("IMPORTS", "").split() if x.lower() in DLLKEY]
    hdr_macros = {}                                      # 测试目录里头文件定义的"会调用其参数"的宏
    for h in sorted(x for x in os.listdir(td) if x.endswith(".h")):
        hdr_macros = macro_call_params(strip_cs(rd(os.path.join(td, h))), hdr_macros)
    dir_ufuncs = None                                    # 这个测试目录所有跑完的单元里出现过的调用(给辅助模块用)
    if relay is not None:
        dir_ufuncs = set()
        for u_, s_ in relay.items():
            if u_.startswith(d + ":") and relay_status.get(u_, "completed") == "completed": dir_ufuncs |= s_
    for src in sorted(s for s in mk.get("SOURCES", mk.get("C_SRCS", "")).split() if s.endswith(".c")):
        p = os.path.join(td, src)
        if not os.path.isfile(p): continue
        n_files += 1
        text = rd(p); st_text = strip_cs(text); st = st_text.split("\n"); orig = text.split("\n")
        funcs = parse_functions(text); local = {f["name"] for f in funcs}
        local |= set(re.findall(r"^\s*#\s*define\s+(\w+)\s*\(", text, re.M))
        fptrs = set(re.findall(r"\*\s*(p\w+)\s*\)\s*\(", st_text))        # 声明过的函数指针:(WINAPI *pFoo)(...)
        ptrmap = {}                                      # 函数指针 -> 它实际指向的导出名:pFoo = GetProcAddress(h, "Foo") / SET(p_btowc, "btowc")
        for m in re.finditer(r'^[^\n]*?\b(p\w+)\b[^;\n"]*"([^"\n]+)"', text, re.M):
            pn, sn = m.group(1), m.group(2)
            if pn in fptrs and sn in UNIVERSE and (sn in (pn[1:], pn[2:]) or "GetProcAddress" in m.group(0) or re.match(r"\s*[A-Z_][A-Z0-9_]*\s*\(", m.group(0)) or "?" in sn):
                ptrmap.setdefault(pn, sn)
        def ptr_target(nm_):
            """声明过的函数指针 → 导出名;不是函数指针或认不出就返回 None。"""
            if nm_ not in fptrs: return None
            t_ = ptrmap.get(nm_) or (nm_[1:] if nm_[1:] in UNIVERSE else nm_[2:] if nm_.startswith("p_") and nm_[2:] in UNIVERSE else None)
            return t_ if t_ and t_ not in local else None
        unit = f"{d}:{src[:-2]}"; ufuncs = relay.get(unit) if relay is not None else None
        # 辅助模块:带 "#pragma makedep testdll" 的源文件被单独编译成一个 DLL/驱动(ntoskrnl 的 driver*.c 等),不是测试程序本身的一部分
        aux = bool(re.search(r"^[ \t]*#[ \t]*pragma[ \t]+makedep[ \t]+testdll", text, re.M))
        f_imports, f_implicit = imports, [DLLKEY[x] for x in IMPLICIT if x in DLLKEY]
        if aux:
            f_imports = [DLLKEY[x.lower()] for x in mk.get(src[:-2] + "_IMPORTS", "").split() if x.lower() in DLLKEY]
            if "-nodefaultlibs" in mk.get(src[:-2] + "_EXTRADLLFLAGS", ""): f_implicit = []
        # 内核驱动跑在另一个进程(winedevice)里,测试进程的 relay 日志里不会有它的调用;用户态的辅助 DLL 加载在测试进程里,日志里有
        aux_driver = aux and ("subsystem,native" in mk.get(src[:-2] + "_EXTRADLLFLAGS", "") or any(x in ("ntoskrnl.exe", "hal") for x in f_imports))
        call_macros = macro_call_params(st_text, hdr_macros)                      # 宏名 -> 被调用的参数下标
        call_helpers = {f["name"]: ix for f in funcs for ix in [fnptr_params(f["sig"], "\n".join(st[f["lb"]:f["l1"]]))] if ix}
        indirect = dict(call_helpers); indirect.update(call_macros)
        rel = os.path.relpath(p, SRC).replace(os.sep, "/")
        line_api = collections.defaultdict(list)         # 行号 -> 该行的 API 调用
        for f in funcs:
            for ln in range(f["lb"], f["l1"]):           # 只看函数体内部(0 基下标 = 行号-1 … 这里 ln 是 '{' 之后的行)
                s = st[ln]
                if "(" not in s: continue
                for m in _ID_PAREN.finditer(s):
                    nm = m.group(1); ptr = False
                    if nm in local or nm in KEYWORDS: continue
                    if nm not in UNIVERSE or nm in fptrs:
                        nm = ptr_target(nm); ptr = True
                        if not nm: continue
                    line_api[ln].append((nm, ptr, f["name"]))
            if indirect:                                 # 通过宏参数 / 辅助函数的函数指针参数发起的调用:CONVERT(VarUI1FromDec, ...)、check_fn(VarAdd, ...)
                btxt = "\n".join(st[f["lb"]:f["l1"]])
                for m in _ID_PAREN.finditer(btxt):
                    ix = indirect.get(m.group(1))
                    if not ix or m.group(1) == f["name"]: continue
                    args = split_args(btxt, m.end() - 1)
                    if not args: continue
                    for j in ix:
                        if j >= len(args): continue
                        nm = args[j][0].strip().lstrip("&").strip(); ptr = True
                        if not re.fullmatch(r"[A-Za-z_]\w*", nm) or nm in local: continue
                        if nm not in UNIVERSE or nm in fptrs:
                            nm = ptr_target(nm)
                            if not nm: continue
                        ln = f["lb"] + btxt.count("\n", 0, m.start())
                        if (nm, ptr, f["name"]) not in line_api[ln] and (nm, False, f["name"]) not in line_api[ln]:
                            line_api[ln].append((nm, ptr, f["name"])); n_indirect += 1
        api_lines = sorted(line_api)
        for idx, ln in enumerate(api_lines):
            nxt = api_lines[idx + 1] if idx + 1 < len(api_lines) else ln + 9
            # —— todo 判定:本行,以及到下一个 API 调用行之前(最多 8 行)的断言 ——
            n_ok = n_todo = 0; pending = False
            if re.search(r"\btodo_wine\b(?!_if)", st[ln - 1]) and not re.search(r"\b(ok|expect)\w*\s*\(", st[ln - 1]): pending = True
            for q in range(ln, min(nxt, ln + 9, len(st))):
                s = st[q]
                if q > ln and s.startswith("}"): break
                has_todo = bool(re.search(r"\btodo_wine\b(?!_if)", s))
                has_assert = bool(re.search(r"\b(?:ok|ok_\w+|expect\w*)\s*\(", s))
                if has_assert:
                    if has_todo or pending: n_todo += 1
                    else: n_ok += 1
                    pending = False
                elif has_todo: pending = True
            status = "ok" if n_ok else ("todo" if n_todo else "unchecked")
            for nm, ptr, fn in line_api[ln]:
                # —— 这个名字是哪个 DLL 的导出?→ 实现键 ——
                cands = name_exporters[nm]
                impls = collections.OrderedDict()
                for c in cands:
                    r = RES.get((c, nm))
                    if r: impls.setdefault(r, []).append(c)
                if not impls: continue
                chosen = None
                if len(impls) == 1: chosen = next(iter(impls))
                else:
                    if ufuncs is not None:               # 先用 relay:哪个候选 DLL 的这个函数在本单元里真的被调用过
                        hit = [r for r, cs in impls.items() if any(f"{c}.{nm}".lower() in ufuncs for c in cs) or f"{r[1]}.{nm}".lower() in ufuncs]
                        if len(hit) == 1: chosen = hit[0]
                    if chosen is None:
                        order = ([testdll] if ptr and testdll and not aux else []) + f_imports + f_implicit + ([testdll] if testdll else [])
                        for c in order:
                            if c in cands and RES.get((c, nm)): chosen = RES[(c, nm)]; break
                    if chosen is None: n_amb += 1; continue
                # executed:True/False = relay 确认/否认;"norelay" = relay 日志里不可能出现(-norelay、varargs、默认 RelayExclude),只能按源码算;
                #           "norun" = 该单元没跑完(或没有这个单元的日志);"aux" = 调用在辅助模块(测试 DLL/驱动)里,且测试进程的日志里找不到
                executed = None
                if relay is not None:
                    keys = {f"{c}.{nm}".lower() for c in impls[chosen]} | {f"{chosen[1]}.{nm}".lower()} | {a.lower() for a in aliases.get((chosen[1], chosen[2]), ())}
                    keys |= {f"{c}.{exports[c][nm]['ord']}".lower() for c in impls[chosen] if exports[c][nm].get("ord")}     # 只按序号导出的,relay 记的是序号
                    blind = any(relay_blind(c, nm) for c in impls[chosen]) or any(relay_blind(*a.rsplit(".", 1)) for a in aliases.get((chosen[1], chosen[2]), ()))
                    if aux: executed = True if (not aux_driver and dir_ufuncs and keys & dir_ufuncs) else "aux"
                    elif ufuncs is None or relay_status.get(unit, "completed") != "completed": executed = "norun"
                    else:
                        executed = bool(keys & ufuncs)
                        if not executed and blind and (ptr or nm not in HDR_INLINE): executed = "norelay"
                sites[chosen].append(dict(file=rel, line=ln + 1, func=fn, name=nm, ptr=ptr, status=status, unit=unit, executed=executed, aux=aux))
                n_sites += 1
    if ti % 40 == 0 or ti == len(test_dirs): log(f"      测试目录 {ti}/{len(test_dirs)},已扫描 {n_files} 个测试文件,{n_sites} 个调用点")
log(f"[3/6] 测试源码:{n_files} 个文件,{n_sites} 个直接调用点(其中经宏参数/函数指针参数发起的 {n_indirect} 个),涉及 {len(sites)} 个函数(无法判定归属 DLL 的调用点 {n_amb} 个)")

# ───────────────────────── 5. 文档索引 ─────────────────────────
docs = collections.defaultdict(list); PREF = {"win32": 0, "ddi": 1, "crt": 2, "win32-conceptual": 3, "win32-gdiplus-flat": 4}
with open(A.docs, newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f): docs[r["name_lower"]].append(r)
log(f"[4/6] 文档索引:{len(docs)} 个函数名")

# ───────────────────────── 6. 汇总、筛选 ─────────────────────────
rows = []; funnel = collections.OrderedDict()
def bump(k): funnel[k] = funnel.get(k, 0) + 1
def is_syscall(dll, cname):
    e = exports.get(dll, {})
    return any(any(fl.startswith("-syscall") for fl in e[n]["flags"]) for n in e if (e[n]["target"] or n) == cname and e[n]["type"] != "stub")
CONV = {"WINAPI", "CDECL", "__cdecl", "__stdcall", "WINGDIPAPI", "APIENTRY", "CALLBACK", "WINAPIV", "__thiscall", "__fastcall", "NTAPI", "PASCAL",
        "WSAAPI", "RPC_ENTRY", "__RPC_USER", "__RPC_STUB", "STDMETHODCALLTYPE", "FASTCALL", "WINAPI_INLINE", "STDAPICALLTYPE"}
NOISE = re.compile(r"^(TRACE|WARN|ERR|FIXME|MESSAGE|debugstr_\w+|wine_dbgstr_\w+|wine_dbg_\w+|TRACE_ON|WARN_ON|ERR_ON|assert|ARRAY_SIZE|offsetof|"
                   r"FIELD_OFFSET|CONTAINING_RECORD|LIST_FOR_EACH\w*|SERVER_START_REQ|max|min|ARRAYSIZE|HIWORD|LOWORD|MAKELONG|MAKEWORD|ULongToHandle|HandleToULong)$")
def describe(sig, body, cname):
    """从签名和函数体算一些辅助信息:返回类型、调用约定、参数个数、代码行数、圈复杂度、调用了哪些函数。"""
    d = {}
    i = sig.find(cname + "("); i = i if i >= 0 else sig.find(cname)
    toks = sig[:i].replace("*", " * ").split() if i > 0 else []
    d["calling_convention"] = next((t for t in toks if t in CONV), "")
    d["return_type"] = re.sub(r"\s+\*", " *", " ".join(t for t in toks if t not in CONV and t not in ("static", "inline", "extern", "SYSCALL_API")
                                                         and not t.startswith(("DECLSPEC_", "__WINE_", "__attribute__")))).strip()
    j = sig.find("(", i if i >= 0 else 0); depth = 0; k = j; params = ""
    while 0 <= k < len(sig):
        if sig[k] == "(": depth += 1
        elif sig[k] == ")":
            depth -= 1
            if depth == 0: params = sig[j + 1:k]; break
        k += 1
    parts = []; depth = 0; cur = ""
    for ch in params:
        if ch in "([": depth += 1
        elif ch in ")]": depth -= 1
        if ch == "," and depth == 0: parts.append(cur.strip()); cur = ""
        else: cur += ch
    if cur.strip(): parts.append(cur.strip())
    d["variadic"] = any(x == "..." for x in parts)
    d["n_params"] = 0 if parts in ([], ["void"]) else len([x for x in parts if x != "..."])
    st = strip_cs(body)
    d["loc_code"] = sum(1 for ln in st.split("\n") if ln.strip() and ln.strip() not in ("{", "}"))      # 函数体里的有效代码行(不含空行、纯注释行、单独的花括号)
    d["cyclomatic"] = 1 + len(re.findall(r"\b(?:if|for|while|case)\b|&&|\|\||\?", st))
    cal = []
    for m in _ID_PAREN.finditer(st):
        n_ = m.group(1)
        if n_ in KEYWORDS or n_ == cname or NOISE.match(n_) or n_ in cal: continue
        cal.append(n_)
    d["callees"] = cal
    d["api_callees"] = [c for c in cal if c in UNIVERSE]
    d["uses_wineserver"] = bool(re.search(r"SERVER_START_REQ|wine_server_call", body))
    return d

# 同一份源码被多个 DLL 编译(PARENTSRC:msvcrt / msvcr90 / ucrtbase …)时,同一个函数定义只出一行,测试合并
groups = collections.OrderedDict()
for key, ss in sorted(sites.items(), key=lambda kv: (kv[0][1], kv[0][2])):
    gid = key
    if key[0] == "impl":
        hit, _ = find_impl(key[1], key[2], is_syscall(key[1], key[2]))
        if hit: gid = ("loc", hit[0], hit[1]["l0"])
    groups.setdefault(gid, []).append((key, ss))
for gid, members in groups.items():
    if gid[0] == "loc":                                  # 主 DLL = 源文件所在目录对应的那个;没有就取第一个
        home = os.path.relpath(gid[1], os.path.join(SRC, "dlls")).split(os.sep)[0]
        members.sort(key=lambda m: (m[0][1] != home, m[0][1]))
    key = members[0][0]; kind, dll, cname = key
    ss = [x for _, s_ in members for x in s_]
    shared = [m[0][1] for m in members]
    called = collections.Counter(s["name"] for s in ss)
    func = called.most_common(1)[0][0]
    live = [s for s in ss if s["status"] != "todo"]
    confirmed = [s for s in live if s["executed"] in (True, "norelay")] if relay is not None else live
    tests = sorted({(s["file"], s["func"]) for s in confirmed})
    tfiles = sorted({s["file"] for s in confirmed})
    # "本模块测试":测试文件所在的模块目录(dlls/<m>/tests)就是导出这个函数的 DLL 之一 —— 即专门测这个 DLL 的测试;
    # 其余是别的模块的测试顺带调用(memset、CloseHandle 这类辅助调用的测试数几乎全来自后者)
    # 判定按调用点做:测试所在模块 m 是实现它的 DLL,或 m 以"测试里调用的这个名字"导出它(kernel32.CreateFileW → kernelbase);
    # 只是以别的名字转发到它的 DLL(crypt32.CreateFileU)不算
    member_dlls = {m[0][1] for m in members}
    alias_set = {a for m in members for a in aliases.get((m[0][1], m[0][2]), [])} if kind == "impl" else set()
    def site_own(s_):
        mod = s_["file"].split("/")[1]
        return mod in member_dlls or f"{mod}.{s_['name']}" in alias_set
    own_tests = {(s_["file"], s_["func"]) for s_ in confirmed if site_own(s_)}; own_files = {s_["file"] for s_ in confirmed if site_own(s_)}
    is_own = lambda f: f in own_files
    tests_own = [t for t in tests if t in own_tests]; tfiles_own = [f for f in tfiles if f in own_files]
    by_dir = collections.OrderedDict()
    for f_, t_ in tests:
        e_ = by_dir.setdefault(os.path.dirname(f_), dict(dir=os.path.dirname(f_), own=is_own(f_), n_tests=0, files=[]))
        e_["n_tests"] += 1
        if os.path.basename(f_) not in e_["files"]: e_["files"].append(os.path.basename(f_))
    test_dirs = sorted(by_dir.values(), key=lambda e_: (not e_["own"], -e_["n_tests"], e_["dir"]))
    rec = dict(function=func, dll=dll, shared_by_dlls=shared, impl_name=cname, test_dirs=test_dirs, n_test_dirs=len(test_dirs),
               exports=sorted({a for m in members for a in aliases.get((m[0][1], m[0][2]), [])}) if kind == "impl" else [f"{dll}.{cname}"],
               n_tests=len(tests), n_test_files=len(tfiles), test_files=tfiles, tests=[f"{a}::{b}" for a, b in tests],
               n_tests_own=len(tests_own), n_tests_other=len(tests) - len(tests_own), n_test_files_own=len(tfiles_own), test_files_own=tfiles_own,
               n_call_sites=len(ss), n_call_sites_ok=sum(s["status"] == "ok" for s in ss), n_call_sites_todo=sum(s["status"] == "todo" for s in ss),
               n_call_sites_unchecked=sum(s["status"] == "unchecked" for s in ss),
               n_call_sites_executed=(sum(s["executed"] is True for s in ss) if relay is not None else None),
               n_call_sites_norelay=sum(s["executed"] == "norelay" for s in ss), n_call_sites_unit_not_completed=sum(s["executed"] == "norun" for s in ss),
               n_call_sites_helper_module=sum(s["executed"] == "aux" for s in ss), n_call_sites_not_called=sum(s["executed"] is False for s in ss),
               relay=("" if relay is None else "confirmed" if any(s["executed"] is True for s in live) else "norelay-flag" if any(s["executed"] == "norelay" for s in live)
                      else "unit-not-completed" if live and all(s["executed"] == "norun" for s in live)
                      else "helper-module-only" if live and all(s["executed"] in ("aux", "norun") for s in live) else "not-called"),
               units=sorted({s["unit"] for s in confirmed}),
               spec_stub=(kind == "stub"), signature="", body="", file="", line_start=0, line_end=0, n_defs=0, impl_flags=[], doc_source="", doc_url="")
    # 文档
    names = {func.lower()} | {a.rsplit(".", 1)[1].lower() for a in rec["exports"]} | {n.lower() for n in called}
    dd = sorted((d for n in names for d in docs.get(n, [])), key=lambda d: (PREF.get(d["source"], 9), d["name_lower"] != func.lower(), d["name_lower"], d["url"]))
    if dd:
        rec["doc_source"], rec["doc_url"] = dd[0]["source"], dd[0]["url"]
        rec["doc"] = {k: dd[0].get(k, "") for k in ("source", "url", "doc_path", "header", "tech_root", "req_dll", "min_client", "crt_category", "description")}
        rec["category"] = categorize(func, rec["doc"])
    # 实现
    if kind == "impl":
        (hit, ndef) = find_impl(dll, cname, is_syscall(dll, cname))
        if hit:
            p, f = hit; lines = rd(p).split("\n")
            body = "\n".join(lines[f["lb"] - 1:f["l1"]])
            rec.update(signature=f["sig"], body=body, file=os.path.relpath(p, SRC).replace(os.sep, "/"), line_start=f["l0"], line_end=f["l1"], n_defs=ndef,
                       loc_total=f["l1"] - f["l0"] + 1, loc_body=f["l1"] - f["lb"] + 1, **describe(f["sig"], body, cname))
            rec["unix_side"] = "/unix/" in rec["file"] or rec["file"].startswith(("dlls/win32u/", "libs/"))
            if relay is not None:
                rec["runtime_calls"] = sum(relay_total.get(a_.lower(), 0) for a_ in rec["exports"])
            fl = []
            if FIXME_MACRO.search(body): fl.append("FIXME()")
            elif FIXME_WORD.search(body): fl.append("FIXME-comment")
            m = STUB_MARK.search(body)
            if m: fl.append("semi-stub" if "semi" in m.group(0).lower() else "stub")
            rec["impl_flags"] = fl
    # 漏斗
    bump("0 候选:被测试源码直接调用的导出函数")
    why = []
    if not live: why.append("only_todo")
    elif relay is not None and not confirmed:
        why.append({"unit-not-completed": "relay_unit_not_completed", "helper-module-only": "helper_module_no_relay"}.get(rec["relay"], "not_executed_in_relay"))
    if not why: bump("T 有测试(非 todo 且 relay 确认执行)" if relay is not None else "T 有测试(非 todo)")
    if not why and not A.keep_no_own_test and rec["n_tests_own"] == 0:
        # 别的模块的测试确认调用到了它,但本模块的测试没有:要么本模块根本没有测它(no_own_module_test),
        # 要么本模块有调用点、只是没法确认(所在单元没跑完 / 在辅助模块里 / 跑了但没执行到)
        ex_own = {s_["executed"] for s_ in live if site_own(s_)}
        why.append("no_own_module_test" if not ex_own else "own_test_unit_not_completed" if ex_own <= {"norun"}
                   else "own_test_in_helper_module" if ex_own <= {"aux", "norun"} else "own_test_not_executed")
    if not why and not A.keep_no_own_test: bump("T' 且本模块测试目录里至少有 1 个测试")
    if not rec["doc_url"]: why.append("no_doc")
    elif not why: bump("1 且有微软官方文档")
    if rec["spec_stub"]: why.append("spec_stub")
    elif not rec["file"]: why.append("impl_not_found")
    elif rec["impl_flags"]: why.append("body_" + "+".join(rec["impl_flags"]))
    if not why: bump("2 且完全实现(非 stub、定位到定义、函数体无 FIXME/stub)= WineBench")
    rec["excluded_by"] = why; rec["in_bench"] = not why
    rows.append(rec)
log(f"[5/6] 汇总 {len(rows)} 个候选函数")

bench = [r for r in rows if r["in_bench"]]
with open(os.path.join(OUT, "winebench_all.jsonl"), "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ───────────────────────── 6b. (可选)没有任何直接测试调用的导出函数 ─────────────────────────
# 这些函数不是候选(漏斗第 0 步就不在),默认不输出。--dump-untested 时写到 winebench_untested.jsonl,
# 字段与 winebench_all.jsonl 对齐(n_tests=0,excluded_by 以 no_direct_test_call 开头),供 analyze_wine500.py 这类"按函数查"的脚本用。
if A.dump_untested:
    done_keys = {m[0] for members in groups.values() for m in members}
    done_locs = {(g[1], g[2]) for g in groups if g[0] == "loc"}
    ug = collections.OrderedDict(); n_alias = 0
    for (dll, cname), al in sorted(aliases.items()):
        n_alias += 1
        if n_alias % 5000 == 0: log(f"      untested:已处理 {n_alias}/{len(aliases)} 个实现函数 ...")
        if ("impl", dll, cname) in done_keys: continue
        hit, ndef = find_impl(dll, cname, is_syscall(dll, cname))
        if hit and (hit[0], hit[1]["l0"]) in done_locs: continue          # 同一份定义已经在候选里(msvcrt 家族共享源码)
        gid = ("loc", hit[0], hit[1]["l0"]) if hit else ("impl", dll, cname)
        ug.setdefault(gid, []).append((dll, cname, hit, ndef))
    n_un = 0
    with open(os.path.join(OUT, "winebench_untested.jsonl"), "w", encoding="utf-8") as f:
        for gid, members in ug.items():
            if gid[0] == "loc":
                home = os.path.relpath(gid[1], os.path.join(SRC, "dlls")).split(os.sep)[0]
                members.sort(key=lambda m: (m[0] != home, m[0]))
            dll, cname, hit, ndef = members[0]
            exps = sorted({a_ for m in members for a_ in aliases.get((m[0], m[1]), [])})
            enames = [a_.rsplit(".", 1)[1] for a_ in exps]
            func = cname if cname in enames else collections.Counter(enames).most_common(1)[0][0]
            rec = dict(function=func, dll=dll, shared_by_dlls=sorted({m[0] for m in members}), impl_name=cname, test_dirs=[], n_test_dirs=0, exports=exps,
                       n_tests=0, n_test_files=0, test_files=[], tests=[], n_tests_own=0, n_tests_other=0, n_call_sites=0, n_call_sites_todo=0,
                       relay="", spec_stub=False, signature="", body="", file="", line_start=0, line_end=0, n_defs=0, impl_flags=[], doc_source="", doc_url="")
            names = {func.lower(), cname.lower()} | {n_.lower() for n_ in enames}
            dd = sorted((d for n_ in names for d in docs.get(n_, [])), key=lambda d: (PREF.get(d["source"], 9), d["name_lower"] != func.lower(), d["name_lower"], d["url"]))
            if dd:
                rec["doc_source"], rec["doc_url"] = dd[0]["source"], dd[0]["url"]
                rec["doc"] = {k: dd[0].get(k, "") for k in ("source", "url", "doc_path", "header", "tech_root", "req_dll", "min_client", "crt_category", "description")}
                rec["category"] = categorize(func, rec["doc"])
            if hit:
                p, fn_ = hit; lines = rd(p).split("\n"); body = "\n".join(lines[fn_["lb"] - 1:fn_["l1"]])
                rec.update(signature=fn_["sig"], body=body, file=os.path.relpath(p, SRC).replace(os.sep, "/"), line_start=fn_["l0"], line_end=fn_["l1"], n_defs=ndef,
                           loc_total=fn_["l1"] - fn_["l0"] + 1, loc_body=fn_["l1"] - fn_["lb"] + 1, **describe(fn_["sig"], body, cname))
                rec["unix_side"] = "/unix/" in rec["file"] or rec["file"].startswith(("dlls/win32u/", "libs/"))
                fl = []
                if FIXME_MACRO.search(body): fl.append("FIXME()")
                elif FIXME_WORD.search(body): fl.append("FIXME-comment")
                m_ = STUB_MARK.search(body)
                if m_: fl.append("semi-stub" if "semi" in m_.group(0).lower() else "stub")
                rec["impl_flags"] = fl
            why = ["no_direct_test_call"]
            if not rec["doc_url"]: why.append("no_doc")
            if not rec["file"]: why.append("impl_not_found")
            elif rec["impl_flags"]: why.append("body_" + "+".join(rec["impl_flags"]))
            rec["excluded_by"] = why; rec["in_bench"] = False
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); n_un += 1
    log(f"      --dump-untested:{n_un} 个没有直接测试调用的实现函数 → winebench_untested.jsonl")

def sample(r):
    """主输出 winebench.json 里的一条样本(嵌套结构)。"""
    c = r.get("category", {}); d = r.get("doc", {})
    return collections.OrderedDict([
        ("id", f"{r['dll']}.{r['impl_name']}"),
        ("name", r["function"]),
        ("signature", r["signature"]),                                     # 函数定义的第一行:返回类型、调用约定、函数名、参数表
        ("body", r["body"]),                                               # 从 '{' 到 '}' 的完整实现
        ("loc", {"total": r["loc_total"], "body": r["loc_body"], "code": r["loc_code"]}),   # 行数:含签名 / 函数体 / 函数体内有效代码行
        ("location", {"dir": os.path.dirname(r["file"]), "file": os.path.basename(r["file"]), "path": r["file"],
                      "line_start": r["line_start"], "line_end": r["line_end"]}),            # 以 Wine 源码根目录为起点
        ("tests", {"n_tests": r["n_tests"], "n_tests_own": r["n_tests_own"], "n_tests_other": r["n_tests_other"],
                   "n_dirs": r["n_test_dirs"], "dirs": r["test_dirs"], "list": r["tests"]}),
        ("category", {"l1": c.get("l1", ""), "l2": c.get("l2", ""), "header": c.get("header", ""), "textbook": c.get("textbook", ""), "basis": c.get("basis", "")}),
        ("doc", {"url": d.get("url", ""), "source": d.get("source", ""), "description": d.get("description", ""), "min_windows": d.get("min_client", ""),
                 "documented_dll": d.get("req_dll", "")}),
        ("dll", r["dll"]), ("shared_by_dlls", r["shared_by_dlls"]), ("exports", r["exports"]),
        ("return_type", r["return_type"]), ("calling_convention", r["calling_convention"]), ("n_params", r["n_params"]), ("variadic", r["variadic"]),
        ("cyclomatic", r["cyclomatic"]), ("callees", r["callees"]), ("api_callees", r["api_callees"]),
        ("uses_wineserver", r["uses_wineserver"]), ("unix_side", r["unix_side"]), ("runtime_calls", r.get("runtime_calls")),
    ])
samples = [sample(r) for r in bench]
with open(os.path.join(OUT, "winebench.json"), "w", encoding="utf-8") as f:
    json.dump({"wine_version": rd(os.path.join(SRC, "VERSION")).strip() if os.path.isfile(os.path.join(SRC, "VERSION")) else "",
               "n_samples": len(samples), "samples": samples}, f, ensure_ascii=False, indent=1)

def cell(v): return "; ".join(map(str, v)) if isinstance(v, list) else v
def flat(x):
    """把一条样本摊平成表格的一行。"""
    return collections.OrderedDict([
        ("name", x["name"]), ("signature", x["signature"]), ("body", x["body"]),
        ("loc_total", x["loc"]["total"]), ("loc_code", x["loc"]["code"]),
        ("dir", x["location"]["dir"]), ("file", x["location"]["file"]), ("line_start", x["location"]["line_start"]), ("line_end", x["location"]["line_end"]),
        ("n_tests", x["tests"]["n_tests"]), ("n_tests_own", x["tests"]["n_tests_own"]), ("n_test_dirs", x["tests"]["n_dirs"]),
        ("test_dirs", "; ".join(f"{e['dir']} ({e['n_tests']})" for e in x["tests"]["dirs"])),
        ("category_l1", x["category"]["l1"]), ("category_l2", x["category"]["l2"]), ("header", x["category"]["header"]),
        ("category_textbook", x["category"]["textbook"]), ("category_basis", x["category"]["basis"]),
        ("description", x["doc"]["description"]), ("doc_url", x["doc"]["url"]), ("min_windows", x["doc"]["min_windows"]),
        ("dll", x["dll"]), ("exports", cell(x["exports"])), ("return_type", x["return_type"]), ("calling_convention", x["calling_convention"]),
        ("n_params", x["n_params"]), ("cyclomatic", x["cyclomatic"]), ("n_callees", len(x["callees"])), ("api_callees", cell(x["api_callees"])),
        ("uses_wineserver", x["uses_wineserver"]), ("unix_side", x["unix_side"]), ("runtime_calls", x["runtime_calls"]),
    ])
table = [flat(x) for x in samples]
with open(os.path.join(OUT, "winebench.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    if table:
        w.writerow(list(table[0].keys()))
        for t in table: w.writerow(list(t.values()))

reasons = collections.Counter(x for r in rows for x in (r["excluded_by"][:1] if r["excluded_by"] else []))
allreasons = collections.Counter(re.sub(r"body_.*", "body_FIXME/stub", x) for r in rows for x in r["excluded_by"])
per_dll = collections.Counter(r["dll"] for r in bench)
with open(os.path.join(OUT, "funnel.txt"), "w", encoding="utf-8") as f:
    def P(s=""):
        print(s); f.write(s + "\n")
    P(f"WineBench 漏斗({rd(os.path.join(SRC, 'VERSION')).strip() if os.path.isfile(os.path.join(SRC, 'VERSION')) else SRC})")
    for k, v in funnel.items(): P(f"  {v:>7}  {k}")
    P(); P("被排除的原因(一个函数可同时命中多项):")
    for k, v in allreasons.most_common(): P(f"  {v:>7}  {k}")
    P(); P(f"WineBench:{len(bench)} 个函数,分布在 {len(per_dll)} 个 DLL;测试数合计 {sum(r['n_tests'] for r in bench)},"
           f"中位数 {sorted(r['n_tests'] for r in bench)[len(bench)//2] if bench else 0}")
    if bench:
        def dist(key):
            v = sorted(r[key] for r in bench); n = len(v); q = lambda p_: v[min(n - 1, int(n * p_))]
            return f"最小 {v[0]}  25% {q(.25)}  中位数 {q(.5)}  75% {q(.75)}  90% {q(.9)}  99% {q(.99)}  最大 {v[-1]}  平均 {sum(v)/n:.1f}"
        P("每个函数的测试数分布:")
        P("  n_tests(全部)        " + dist("n_tests"))
        P("  n_tests_own(本模块)  " + dist("n_tests_own"))
        P("  n_tests_other(其他模块)" + dist("n_tests_other"))
        P(f"  本模块测试数为 0 的函数:{sum(r['n_tests_own'] == 0 for r in bench)} 个;只有 1 个本模块测试的:{sum(r['n_tests_own'] == 1 for r in bench)} 个")
    P("函数最多的 20 个 DLL:" + ", ".join(f"{d} {n}" for d, n in per_dll.most_common(20)))
    P(); P("功能分类(一级 / 二级):")
    l1c = collections.Counter(r["category"]["l1"] for r in bench); l2c = collections.defaultdict(collections.Counter)
    for r in bench: l2c[r["category"]["l1"]][r["category"]["l2"]] += 1
    for k, v in l1c.most_common():
        P(f"  {v:>5}  {k}")
        for k2, v2 in l2c[k].most_common(): P(f"         {v2:>5}  {k2}")
    P(); P("教科书(Silberschatz 六类系统调用)对照:" + ", ".join(f"{k} {v}" for k, v in collections.Counter(r["category"]["textbook"] for r in bench).most_common()))
    P("分类依据:" + ", ".join(f"{k} {v}" for k, v in collections.Counter(r["category"]["basis"] for r in bench).most_common()))

if not A.no_xlsx:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        wb = Workbook(write_only=False); ws = wb.active; ws.title = "WineBench"
        XC = list(table[0].keys()) if table else []
        ws.append(XC)
        for c in ws[1]: c.font = Font(bold=True)
        def xl(v):
            if isinstance(v, str):
                v = ILLEGAL_CHARACTERS_RE.sub("", v)
                if len(v) > 32000: v = v[:32000] + "\n/* ... 截断,完整内容见 winebench.json ... */"
            return v
        for t in table: ws.append([xl(v) for v in t.values()])
        from openpyxl.utils import get_column_letter
        W = {"name": 30, "signature": 60, "body": 70, "dir": 22, "file": 16, "test_dirs": 50, "category_l1": 26, "category_l2": 30, "header": 18,
             "category_textbook": 24, "description": 60, "doc_url": 40, "exports": 30, "api_callees": 40}
        for i_, c_ in enumerate(XC, 1): ws.column_dimensions[get_column_letter(i_)].width = W.get(c_, 12)
        ws.freeze_panes = "B2"; ws.auto_filter.ref = ws.dimensions
        top = Alignment(vertical="top", wrap_text=False)
        for row in ws.iter_rows(min_row=2):
            for c in row: c.alignment = top
        wb.save(os.path.join(OUT, "winebench.xlsx"))
    except ImportError:
        log("      未安装 openpyxl,跳过 xlsx(pip install openpyxl)")
log(f"[6/6] 完成,用时 {time.time() - T0:.0f}s。输出目录:{OUT}")
