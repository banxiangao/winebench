#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_doc_index.py —— 建立"微软官方开源文档里有哪些函数"的索引(筛选条件【1】用),并带出文档自带的分类元数据(功能分类用)。

来源(都是微软在 GitHub 上公开的官方文档仓库,learn.microsoft.com 的页面就是由它们生成的):
  sdk-api                  Win32 API 参考        sdk-api-src/content/<header>/nf-<header>-<func>.md
  windows-driver-docs-ddi  驱动/内核(Nt*/Zw*/Rtl*) wdk-ddi-src/content/<header>/nf-<header>-<func>.md
  cpp-docs                 C 运行时(msvcrt/ucrtbase) docs/c-runtime-library/reference/*.md(函数名在 api_name 字段里)
  win32                    概念文档仓库里的独立函数参考页(frontmatter 有 api_name、标题为 "... function"),
                           以及 GDI+ Flat API 表格页 desktop-src/gdiplus/-gdiplus-*-flat.md(GdipXxx 只在表格里列出签名)

输出:msdocs_index.csv,列:
  name_lower   小写函数名(匹配时不区分大小写)
  source       win32 | ddi | crt | win32-conceptual | win32-gdiplus-flat
  header       所属头文件(sdk-api / DDI 来自目录名,如 fileapi)
  doc_path     文档在仓库里的路径
  url          learn.microsoft.com 上的地址
  tech_root    文档 frontmatter 的 tech.root —— 微软自己给这个 API 标的"技术领域"(fs、base、gdi、security、winmsg …);
               概念文档取所在目录名;CRT 留空
  req_dll      文档写明的所在 DLL(req.dll)
  min_client   最低支持的 Windows 客户端版本(req.target-min-winverclnt)
  crt_category CRT 函数在 "Universal C runtime routines by category" 里所属的类别
  description  文档的一句话描述

需要正文,所以会下载约 400 MB(blobless 克隆 + 只检出需要的 md);几分钟。
用法:python3 build_doc_index.py [--work ./msdocs_repos] [--out msdocs_index.csv]
"""
import argparse, csv, os, re, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--work", default="./msdocs_repos", help="克隆仓库的目录")
ap.add_argument("--out", default="msdocs_index.csv")
a = ap.parse_args()
os.makedirs(a.work, exist_ok=True)

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode: sys.exit(f"命令失败: {' '.join(cmd)}\n{r.stdout[-2000:]}")
    return r.stdout
def rd(p, n=None):
    with open(p, encoding="utf-8", errors="replace") as f: return f.read(n) if n else f.read()
def fm_field(fm, key):
    m = re.search(r"^" + re.escape(key) + r":[ \t]*(.*)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else ""
def clean(s): return re.sub(r"\s+", " ", s.replace("\\_", " ").replace("\\", "")).strip()

REPOS = [("sdk-api", ["/sdk-api-src/content/*/nf-*.md"]),
         ("windows-driver-docs-ddi", ["/wdk-ddi-src/content/*/nf-*.md"]),
         ("cpp-docs", ["/docs/c-runtime-library/reference/*.md", "/docs/c-runtime-library/*.md"]),
         ("win32", ["/desktop-src/**/*.md"])]
commits = {}
for i, (r, patterns) in enumerate(REPOS, 1):
    d = os.path.join(a.work, r)
    if not os.path.isdir(os.path.join(d, ".git")):
        log(f"({i}/{len(REPOS)}) 克隆 MicrosoftDocs/{r} ...")
        run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout", f"https://github.com/MicrosoftDocs/{r}", d])
    else:
        log(f"({i}/{len(REPOS)}) {r} 已存在,复用")
    log(f"    检出 {' '.join(patterns)} ...")
    run(["git", "sparse-checkout", "set", "--no-cone"] + patterns, cwd=d)
    run(["git", "checkout", "-q", "HEAD"], cwd=d)
    commits[r] = run(["git", "rev-parse", "HEAD"], cwd=d).strip()
    log(f"    commit {commits[r][:12]}")

rows = []   # (name_lower, source, header, doc_path, url, tech_root, req_dll, min_client, crt_category, description)
# ---- sdk-api / DDI:文件名 nf-<header>-<func>.md;接口方法是 nf-<header>-<iface>-<method>.md(多一段),不要 ----
for repo, root, urlbase, src in (("sdk-api", "sdk-api-src/content", "https://learn.microsoft.com/windows/win32/api/", "win32"),
                                 ("windows-driver-docs-ddi", "wdk-ddi-src/content", "https://learn.microsoft.com/windows-hardware/drivers/ddi/", "ddi")):
    n = 0; base = os.path.join(a.work, repo, root)
    for header in sorted(os.listdir(base)):
        hd = os.path.join(base, header)
        if not os.path.isdir(hd): continue
        for fn in sorted(os.listdir(hd)):
            if not (fn.startswith("nf-") and fn.endswith(".md")): continue
            stem = fn[3:-3]
            if not stem.startswith(header + "-"): continue
            func = stem[len(header) + 1:]
            if "-" in func: continue                       # 接口方法 / 类成员
            head = rd(os.path.join(hd, fn), 8000); fm = head[3:].split("\n---", 1)[0] if head.startswith("---") else ""
            rows.append((func.lower(), src, header, f"{root}/{header}/{fn}", f"{urlbase}{header}/nf-{header}-{func}",
                         fm_field(fm, "tech.root"), fm_field(fm, "req.dll"), fm_field(fm, "req.target-min-winverclnt"), "", clean(fm_field(fm, "description"))[:300]))
            n += 1
            if n % 5000 == 0: log(f"    {src}: 已读 {n} 个函数页 ...")
    log(f"{src}: {n} 个函数页")

# ---- CRT:函数名来自 reference 页的 api_name;类别来自 "routines by category" 各类别页里的链接 ----
crt = os.path.join(a.work, "cpp-docs", "docs", "c-runtime-library")
cat_of = {}                                               # reference 页文件名 -> 类别
toc = rd(os.path.join(crt, "run-time-routines-by-category.md"))
SUBPAGES = {"input-and-output.md": ["stream-i-o.md", "low-level-i-o.md", "console-and-port-i-o.md"]}   # 类别页本身只是目录、函数列在子页里的
GENERIC = ("Debug routines", "Robustness", "Internationalization", "Complex math support", "System calls")   # 一个函数出现在多个类别时,这些泛化类别让位给更具体的
cands = {}
for title, page in re.findall(r"^- \[([^\]]+)\]\(\./([^)]+\.md)\)", toc, re.M):
    txt = "\n".join(re.split(r"^##+ See also", rd(os.path.join(crt, x)), flags=re.M)[0]
                    for x in [page] + SUBPAGES.get(page, []) if os.path.isfile(os.path.join(crt, x)))
    for ref in re.findall(r"\((?:\./)?reference/([^)#]+\.md)", txt):
        cands.setdefault(ref, []).append(title)
for ref, cs in cands.items():
    cat_of[ref] = sorted(cs, key=lambda c: (c in GENERIC, cs.index(c)))[0]
n = 0
for fn in sorted(os.listdir(os.path.join(crt, "reference"))):
    if not fn.endswith(".md"): continue
    head = rd(os.path.join(crt, "reference", fn), 6000); fm = head[3:].split("\n---", 1)[0] if head.startswith("---") else ""
    m = re.search(r"^api_name:\s*\[(.*?)\]", head, re.M | re.S)
    if not m: continue
    url = "https://learn.microsoft.com/cpp/c-runtime-library/reference/" + fn[:-3]
    for nm in re.findall(r'"([^"]+)"', m.group(1)):
        nm = nm.split("/")[-1]
        if nm.startswith("_o_"): continue                  # ucrtbase 的内部转发名
        rows.append((nm.lower(), "crt", "", f"docs/c-runtime-library/reference/{fn}", url, "", "", "", cat_of.get(fn, ""), clean(fm_field(fm, "description"))[:300])); n += 1
log(f"crt: {n} 个函数名({len(set(cat_of.values()))} 个类别)")

# ---- win32 概念文档仓库 ----
d = os.path.join(a.work, "win32"); n1 = n2 = nfiles = 0
for root, _, fns in os.walk(os.path.join(d, "desktop-src")):
    for fn in fns:
        if not fn.endswith(".md"): continue
        nfiles += 1
        if nfiles % 10000 == 0: log(f"    win32: 已扫描 {nfiles} 个 md ...")
        full = os.path.join(root, fn); rel = os.path.relpath(full, d).replace(os.sep, "/")
        folder = rel.split("/")[1]
        url = "https://learn.microsoft.com/windows/win32/" + rel[len("desktop-src/"):-3].lower()
        if rel.startswith("desktop-src/gdiplus/") and fn.endswith("-flat.md"):
            for nm in set(re.findall(r"WINGDIPAPI\s+(Gdip\w+)\s*\(", rd(full).replace("\\", ""))):
                rows.append((nm.lower(), "win32-gdiplus-flat", "gdiplusflat", rel, url, "gdiplus", "gdiplus.dll", "", "", "")); n2 += 1
            continue
        head = rd(full, 4000)
        if not head.startswith("---"): continue
        fm = head[3:].split("\n---", 1)[0]
        m = re.search(r"^api_name:\s*\n((?:- .*\n?)+)", fm, re.M)
        t = fm_field(fm, "title")
        if not m or not re.search(r"\bfunction\b", t, re.I): continue
        loc = re.search(r"^api_location:\s*\n((?:- .*\n?)+)", fm, re.M)
        dll = next((x for x in re.findall(r"^- (\S+)", loc.group(1), re.M) if x.lower().endswith(".dll")), "") if loc else ""
        for nm in re.findall(r"^- (\S+)", m.group(1), re.M):
            if re.fullmatch(r"[A-Za-z_]\w*", nm):
                rows.append((nm.lower(), "win32-conceptual", "", rel, url, folder, dll, "", "", clean(fm_field(fm, "description"))[:300])); n1 += 1
log(f"win32-conceptual: {n1} 个函数名;win32-gdiplus-flat: {n2} 个")

rows = sorted(set(rows))
with open(a.out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["name_lower", "source", "header", "doc_path", "url", "tech_root", "req_dll", "min_client", "crt_category", "description"]); w.writerows(rows)
with open(os.path.splitext(a.out)[0] + ".commits.txt", "w") as f:
    for r, c in commits.items(): f.write(f"MicrosoftDocs/{r} {c}\n")
log(f"共 {len(rows)} 条(不同函数名 {len(set(r[0] for r in rows))} 个)→ {a.out}")
