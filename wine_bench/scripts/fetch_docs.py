#!/usr/bin/env python3
"""fetch_docs.py - Microsoft's public API documentation, as a local index and as pages per function.

    python3 scripts/fetch_docs.py index                       # clone the doc repos (file lists only) -> dataset/docs_index.tsv
    python3 scripts/fetch_docs.py attach dataset/wine500_doc  # fetch the page(s) of every record and store them in the records
    python3 scripts/fetch_docs.py lookup CreateFileW _wtol    # where is a function documented?

Sources (MicrosoftDocs on GitHub; cloned with --filter=blob:none, pages are fetched on demand):
    sdk-api                  Win32 API      sdk-api-src/content/<header>/nf-<header>-<name>.md
    windows-driver-docs-ddi  Nt*/Rtl*/Io*   wdk-ddi-src/content/<header>/nf-<header>-<name>.md
    cpp-docs                 C runtime      docs/c-runtime-library/reference/<name[-name...]>.md (one page, several functions)
    win32                    D3DX           desktop-src/direct3d9|direct3d10/<name>.md

Index columns: name (as documented, from the page's api_name when available, else from the file name),
key (lower case), repo, header, path, url.  Repos are cloned into external/msdocs/ (git-ignored;
override with the WINE_BENCH_MSDOCS environment variable).
"""
import os, re, sys, csv, json, glob, subprocess, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import ROOT

EXT = os.environ.get('WINE_BENCH_MSDOCS') or os.path.join(ROOT, 'external', 'msdocs')   # where the doc repos are cloned
INDEX = os.path.join(ROOT, 'dataset', 'docs_index.tsv')
REPOS = {
    'sdk-api':                 ('https://github.com/MicrosoftDocs/sdk-api.git', 'docs'),
    'windows-driver-docs-ddi': ('https://github.com/MicrosoftDocs/windows-driver-docs-ddi.git', 'staging'),
    'cpp-docs':                ('https://github.com/MicrosoftDocs/cpp-docs.git', 'main'),
    'win32':                   ('https://github.com/MicrosoftDocs/win32.git', 'docs'),
}
WEB = {'sdk-api': 'https://learn.microsoft.com/windows/win32/api/{header}/nf-{header}-{key}',
       'windows-driver-docs-ddi': 'https://learn.microsoft.com/windows-hardware/drivers/ddi/{header}/nf-{header}-{key}',
       'cpp-docs': 'https://learn.microsoft.com/cpp/c-runtime-library/reference/{page}',
       'win32': 'https://learn.microsoft.com/windows/win32/{header}/{page}'}

def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout

def clone(repo):
    d = os.path.join(EXT, repo)
    if not os.path.isdir(d):
        os.makedirs(EXT, exist_ok=True)
        print(f'cloning {repo} (file list only)...', flush=True)
        sh('git', 'clone', '--quiet', '--depth', '1', '--filter=blob:none', '--no-checkout', REPOS[repo][0], d)
    return d

def files(repo):
    return sh('git', 'ls-tree', '-r', '--name-only', 'HEAD', cwd=clone(repo)).split('\n')

def page(repo, path):
    """fetch one page lazily and return its text"""
    d = clone(repo); f = os.path.join(d, path)
    if not os.path.exists(f): sh('git', 'checkout', 'HEAD', '--', path, cwd=d)
    return open(f, encoding='utf-8', errors='ignore').read()

def front_matter(text):
    m = re.match(r'---\n(.*?)\n---', text, re.S)
    return m.group(1) if m else ''

def api_names(text):
    """api_name: ["abs", "_abs64"]  (cpp-docs / sdk-api front matter)"""
    m = re.search(r'^api_name:\s*\[(.*?)\]', front_matter(text), re.M | re.S)
    return [x.strip().strip('"\'') for x in m.group(1).split(',')] if m else []

# ---------------------------------------------------------------- index
def build_index():
    rows = []
    for l in files('sdk-api'):
        m = re.match(r'sdk-api-src/content/([^/]+)/nf-\1-(.+)\.md$', l)
        if m: rows.append(dict(name=m.group(2), key=m.group(2), repo='sdk-api', header=m.group(1), path=l,
                               url=WEB['sdk-api'].format(header=m.group(1), key=m.group(2))))
    for l in files('windows-driver-docs-ddi'):
        m = re.match(r'wdk-ddi-src/content/([^/]+)/nf-\1-(.+)\.md$', l)
        if m: rows.append(dict(name=m.group(2), key=m.group(2), repo='windows-driver-docs-ddi', header=m.group(1), path=l,
                               url=WEB['windows-driver-docs-ddi'].format(header=m.group(1), key=m.group(2))))
    crt = [l for l in files('cpp-docs') if re.match(r'docs/c-runtime-library/reference/[^/]+\.md$', l)]
    print(f'fetching {len(crt)} C-runtime pages for their api_name lists...', flush=True)
    sh('git', 'checkout', 'HEAD', '--', 'docs/c-runtime-library/reference', cwd=clone('cpp-docs'))
    for l in crt:
        pg = os.path.basename(l)[:-3]
        for n in api_names(page('cpp-docs', l)):
            rows.append(dict(name=n, key=n.lower(), repo='cpp-docs', header='crt', path=l, url=WEB['cpp-docs'].format(page=pg)))
    for l in files('win32'):
        m = re.match(r'desktop-src/(direct3d9|direct3d10|direct3d11)/([a-z0-9_]+)\.md$', l)
        if m and m.group(2).startswith(('d3dx', 'd3dx10', 'd3dx11')):
            rows.append(dict(name=m.group(2), key=m.group(2), repo='win32', header=m.group(1), path=l,
                             url=WEB['win32'].format(header=m.group(1), page=m.group(2))))
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['name', 'key', 'repo', 'header', 'path', 'url'], delimiter='\t'); w.writeheader(); w.writerows(rows)
    by = {}
    for r in rows: by[r['repo']] = by.get(r['repo'], 0) + 1
    print(f'{len(rows)} entries, {len({r["key"] for r in rows})} distinct names -> {INDEX}  {by}')

def load_index(path=INDEX):
    idx = {}
    for r in csv.DictReader(open(path), delimiter='\t'): idx.setdefault(r['key'], []).append(r)
    return idx

def lookup(idx, name):
    """index entries for a Wine export name; exact (case-insensitive) match only"""
    return idx.get(name.lower(), [])

# ---------------------------------------------------------------- attach
PRIORITY = ['sdk-api', 'windows-driver-docs-ddi', 'cpp-docs', 'win32']
def attach(dataset_dir, idx, max_pages=2):
    ddir = os.path.join(dataset_dir, 'docs'); os.makedirs(ddir, exist_ok=True)
    n = miss = 0
    for f in sorted(glob.glob(os.path.join(dataset_dir, '[0-9]*.json'))):
        rec = json.load(open(f, encoding='utf-8')); name = rec['function']['export_name']
        hits = sorted(lookup(idx, name), key=lambda r: PRIORITY.index(r['repo']))[:max_pages]
        docs = []
        for h in hits:
            text = page(h['repo'], h['path'])
            out = os.path.join(ddir, f"{rec['id']}_{h['repo']}_{os.path.basename(h['path'])}")
            open(out, 'w', encoding='utf-8').write(text)
            docs.append(dict(repo=h['repo'], header=h['header'], path=h['path'], url=h['url'],
                             documented_name=h['name'], file=os.path.relpath(out, dataset_dir), text=text))
        rec['docs'] = docs
        json.dump(rec, open(f, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        n += 1; miss += not docs
    print(f'{n} records updated, {n - miss} with documentation, {miss} without; pages in {ddir}')

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['index', 'attach', 'lookup']); ap.add_argument('args', nargs='*')
    ap.add_argument('--max-pages', type=int, default=2, help='attach: pages per function (sdk-api first)')
    a = ap.parse_args()
    if a.cmd == 'index': build_index()
    elif a.cmd == 'attach':
        if not a.args: sys.exit('attach: give the dataset directory')
        attach(a.args[0], load_index(), a.max_pages)
    else:
        idx = load_index()
        for n in a.args:
            hs = lookup(idx, n)
            print(n + ':' + ('' if hs else ' (not documented)')); [print(f"  {h['repo']:24} {h['path']}") for h in hs]

if __name__ == '__main__':
    main()
