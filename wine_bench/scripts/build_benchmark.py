#!/usr/bin/env python3
"""build_benchmark.py - scenario 1.1 dataset: one JSON per sampled Wine function.

    python3 build_benchmark.py --src <wine> --build <build-dir> --out <dir> [--n 500] [--seed 1]

Pipeline
  1. candidate pool  = every non-stub export of dlls/*/*.spec whose implementation wine_locate
                       resolves to a unique C function (no third-party code, no macro/asm bodies,
                       no C++ mangled names, no per-module boilerplate entry points such as
                       DllGetClassObject/DllRegisterServer, de-duplicated by implementation location)
  2. filters         = body has at least --min-body lines, no FIXME("...stub") semi-stub,
                       and the export name is referenced in dlls/<exporter>/tests/*.c (native test)
  3. sample          = shuffle with --seed, take the first --n that pass the filters
  4. per function    = wine_deps (libclang) in same-file-only mode -> same-file dependencies,
                       other-file / other-DLL / system calls; same-name exports in other DLLs
                       located with wine_locate; everything stored with file + line range + code
Resumable: existing <out>/NNNN_*.json files are kept and counted.
"""
import os, re, sys, json, glob, random, argparse, subprocess, time, shutil, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wine_locate as WL
import wine_deps as WD

SKIP_MODULES = re.compile(r'^(msvcp\d*|icu\w*|winsqlite3|unicows)$')
IDENT = re.compile(r'^[A-Za-z_]\w*$')
BOILERPLATE = {'DllMain', 'DllGetClassObject', 'DllCanUnloadNow', 'DllRegisterServer', 'DllUnregisterServer',
               'DllGetActivationFactory', 'DllInstall', 'DllGetVersion', 'DllEntryPoint'}   # per-module entry points

def lines_of(path):
    return WL.lines(os.path.realpath(path))

def function_end(path, start):
    """Wine style: '{' at column 0 (or on the signature line) and the matching '}' at column 0."""
    L = lines_of(path); i = start - 1
    while i < len(L) and '{' not in L[i]:
        if i > start + 20: return None
        i += 1
    if i < len(L) and L[i].rstrip().endswith('}') and L[i].count('{') == L[i].count('}'): return i + 1   # one-liner
    i += 1
    while i < len(L) and not L[i].startswith('}'): i += 1
    return i + 1 if i < len(L) else None

def block_text(path, start, end):
    return '\n'.join(lines_of(path)[start - 1:end])

def signature(path, start):
    L = lines_of(path); sig = []
    for i in range(start - 1, min(start + 20, len(L))):
        if L[i].startswith('{'): break
        sig.append(L[i].strip())
    return ' '.join(sig)

def file_includes(path):
    """the #include lines of a source file, in order (compile context for the programmer stage)"""
    return [l.rstrip() for l in lines_of(path) if re.match(r'\s*#\s*include\b', l)]

def comment_above(path, start):
    """Wine's /***** Name (MODULE.@) ... */ header comment right above the function, if any."""
    L = lines_of(path); i = start - 2
    if i < 0 or not L[i].rstrip().endswith('*/'): return None
    j = i
    while j >= 0 and not L[j].lstrip().startswith('/*'): j -= 1
    return '\n'.join(L[j:i + 1]) if j >= 0 and i - j < 60 else None

def brace_block(path, start):
    """Text of a struct/enum/union/typedef definition. libclang reports a typedef at its NAME, which for
    `typedef struct { ... } name;` is the closing line, so first walk back to the opening line."""
    L = lines_of(path)
    if L[start - 1].lstrip().startswith('}'):
        depth = 0
        for i in range(start - 1, max(start - 400, -1), -1):
            depth += L[i].count('}') - L[i].count('{')
            if depth <= 0 and '{' in L[i]:
                start = i + 1
                while start > 1 and re.match(r'\s*(typedef|struct|union|enum)\b', L[start - 2]) and '{' not in L[start - 2]: start -= 1
                break
    depth = 0; seen = False
    for i in range(start - 1, min(start + 400, len(L))):
        depth += L[i].count('{') - L[i].count('}'); seen |= '{' in L[i]
        if (seen and depth <= 0) or (not seen and L[i].rstrip().endswith(';')):
            return '\n'.join(L[start - 1:i + 1]), i + 1
    return L[start - 1], start

def macro_text(path, start):
    L = lines_of(path); out = []
    for i in range(start - 1, len(L)):
        out.append(L[i])
        if not L[i].rstrip().endswith('\\'): break
    return '\n'.join(out), start + len(out) - 1

def is_generated(path):
    head = ''.join(lines_of(path)[:5]).lower()
    return 'automatically generated' in head or 'do not edit' in head

def test_mentions(src, name, modules):
    """test files (dlls/<module>/tests/*.c) that reference `name`; via rg when available."""
    dirs = [f'{src}/dlls/{m}/tests' for m in modules if os.path.isdir(f'{src}/dlls/{m}/tests')]
    if not dirs: return []
    if shutil.which('rg'):
        r = subprocess.run(['rg', '-l', '-w', '-F', name] + dirs, capture_output=True, text=True)
        files = r.stdout.split()
    else:
        pat = re.compile(r'\b' + re.escape(name) + r'\b'); files = []
        for d in dirs:
            for f in glob.glob(f'{d}/*.c'):
                if pat.search(open(f, errors='ignore').read()): files.append(f)
    return sorted(WD.rel(f) for f in files)

def same_name_impls(src, name, target_loc):
    """Exports with the same name in other DLLs, resolved to their own implementation.
    Entries that resolve to the same code (forward / -import / PARENTSRC) are merged into one record."""
    groups = {}
    for m in sorted(set(WD.exporters(name))):
        chain, hits = WL.resolve(m, name)
        if not hits: continue
        groups.setdefault(hits[0], []).append((m, chain))
    out = []
    for h, entries in groups.items():
        if h == target_loc: continue
        f, line = h.split(' ')[0].rsplit(':', 1); line = int(line); path = f'{src}/{f}'
        srcmod = f.split('/')[1]
        mods = [m for m, _ in entries]
        main = srcmod if srcmod in mods else mods[0]
        chain = dict(entries)[main]
        rec = dict(module=main, source_module=srcmod, exported_by=mods, file=f, start_line=line,
                   resolution=chain, macro_generated='(macro)' in h, win16=bool(re.search(r'16$', main)))
        if not rec['macro_generated']:
            end = function_end(path, line)
            if end:
                rec.update(end_line=end, signature=signature(path, line), code=block_text(path, line, end))
        out.append(rec)
    return out

def build_record(src, idx, mod, exp, chain, hit, min_body, lite=False, doc_index=None):
    """lite=True: locate the function, extract its code and compile context, attach nothing else
    (no libclang).  Dependencies can be added later with --add-deps (add_deps())."""
    f, line = hit.rsplit(':', 1); line = int(line); path = f'{src}/{f}'
    impl_mod = chain[-1].split('!')[0]
    m = re.search(r'internal symbol (\w+)', chain[-1])
    fname = m.group(1) if m else re.match(r'[^!]+!([^\s\[]+)', chain[-1]).group(1)   # name of the C function
    if is_generated(path): return None, 'generated source file'
    end = function_end(path, line)
    if not end: return None, 'no function body found'
    code = block_text(path, line, end)
    if end - line - 2 < min_body: return None, f'body shorter than {min_body} lines'
    if re.search(r'FIXME\s*\([^;]*stub', code, re.I): return None, 'semi-stub (FIXME stub)'
    exporters = sorted(set(WD.exporters(exp)))
    tests = test_mentions(src, exp, exporters)
    if not tests: return None, 'no native test references the export'
    if doc_index is not None and exp.lower() not in doc_index: return None, 'no Microsoft documentation page'

    rec = dict(
        id=f'{idx:04d}',
        function=dict(name=fname, export_name=exp, module=impl_mod, source_module=f.split('/')[1], exported_by=exporters,
                      side='unix' if WD.is_unix_file(path) else 'PE', file=f, start_line=line, end_line=end, body_lines=end - line - 2,
                      signature=signature(path, line), header_comment=comment_above(path, line), code=code,
                      has_fixme='FIXME' in code,          # partially implemented: some branch/parameter is not handled
                      file_includes=file_includes(path),
                      resolution=chain),
        native_tests=dict(files=tests),
        same_name_in_other_dlls=same_name_impls(src, exp, hit),
        meta=dict(deps_analysed=False))
    if lite: return rec, None
    return add_deps(src, rec)

def add_deps(src, rec):
    """libclang dependency analysis for an existing record (fills same_file_dependencies, same_file_definitions,
    other_dependencies, meta.parse_errors).  Used by the full build and by --add-deps."""
    fn = rec['function']; path = f"{src}/{fn['file']}"; fname = fn['name']; impl_mod = fn['module']; line = fn['start_line']
    WD._tu.clear()                                             # bound memory: one TU cache per function
    try:
        deps, internal, types, gvars, macros = WD.analyze(path, fname, impl_mod, line, follow_files=False)
    except SystemExit as e:
        return None, f'wine_deps: {e}'
    if deps['summary']['parse_errors'] and not os.environ.get('WINE_BENCH_KEEP_PARSE_ERRORS'):
        return None, 'dependency analysis has parse errors (arch-specific code or unresolved headers)'
    tfile = deps['target']['file']
    same_file, other_file = [], []
    for r in deps['internal_functions'][1:]:
        d = dict(name=r['name'], file=r['file'], start_line=r['start'], end_line=r['end'], static=r['static'],
                 called_from=r['called_from'], exclusive_to_target=r.get('exclusive', False))
        if r.get('used_outside'): d['used_outside'] = r['used_outside']
        if r['file'] == tfile:
            d['signature'] = signature(path, r['start']); d['code'] = block_text(path, r['start'], r['end'])
            same_file.append(d)
        else: other_file.append(d)
    for e in deps['external_functions']:
        if e['kind'] == 'same_module_other_file':
            other_file.append(dict(name=e['name'], file=e['decl'].rsplit(':', 1)[0], start_line=int(e['decl'].rsplit(':', 1)[1])))
    defs = dict(types=[], globals=[], macros=[])
    for t in deps['types']:
        if t['decl'] and t['decl'].rsplit(':', 1)[0] == tfile:
            l = int(t['decl'].rsplit(':', 1)[1]); txt, e = brace_block(path, l)
            defs['types'].append(dict(name=t['name'], kind=t['kind'], start_line=e - txt.count('\n'), end_line=e, code=txt))
    for g in deps['globals']:
        if g['decl'] and g['decl'].rsplit(':', 1)[0] == tfile:
            l = int(g['decl'].rsplit(':', 1)[1]); txt, e = brace_block(path, l)
            defs['globals'].append(dict(name=g['name'], type=g['type'], static=g['static'], start_line=l, end_line=e, code=txt))
    for mc in deps['macros']:
        if mc['decl'] and mc['decl'].rsplit(':', 1)[0] == tfile:
            l = int(mc['decl'].rsplit(':', 1)[1]); txt, e = macro_text(path, l)
            defs['macros'].append(dict(name=mc['name'], start_line=l, end_line=e, code=txt))
    external = dict(
        same_module_exports=[dict(name=e['name'], impl=e.get('impl')) for e in deps['external_functions'] if e['kind'] == 'module_export'],
        other_dll_exports=[dict(name=e['name'], module=e.get('impl_module'), impl=e.get('impl')) for e in deps['external_functions'] if e['kind'] == 'dll_export'],
        header_inline=[e['name'] for e in deps['external_functions'] if e['kind'] == 'inline_header'],
        system=[e['name'] for e in deps['external_functions'] if e['kind'] == 'system'],
        unresolved=[e['name'] for e in deps['external_functions'] if e['kind'] == 'unresolved'])
    fn['side'] = deps['target']['side']; fn['arch'] = deps['target']['arch']
    rec['same_file_dependencies'] = same_file
    rec['same_file_definitions'] = defs
    rec['other_dependencies'] = dict(same_module_other_files=other_file, **external,
                                     server_requests=deps['server_requests'], unix_calls=deps['unix_calls'],
                                     indirect_calls=deps['indirect_calls'])
    rec['meta'] = dict(deps_analysed=True, parse_errors=deps['summary']['parse_errors'],
                       parse_error_samples=[x for p in deps['parse'] for x in p['first_errors']][:3])
    return rec, None

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', default=os.environ.get('WINE_SRC', '.')); ap.add_argument('--build', default=os.environ.get('WINE_BUILD'))
    ap.add_argument('--out', required=True); ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--seed', type=int, default=1); ap.add_argument('--min-body', type=int, default=5)
    ap.add_argument('--no-test-filter', action='store_true')
    ap.add_argument('--exclude-win16', action='store_true', help='drop 16-bit modules (*16, *.exe16, *.drv16)')
    ap.add_argument('--exclude-crt', action='store_true', help='drop the C runtime family (msvcr*, ucrtbase, crtdll, msvcp*)')
    ap.add_argument('--max-per-module', type=int, default=0, help='cap the number of functions taken from one module (0 = no cap)')
    ap.add_argument('--redo-errors', action='store_true',
                    help='re-analyse, in place, the existing records whose meta.parse_errors > 0 (same id, same function)')
    ap.add_argument('--redo', default='', help='comma-separated ids (e.g. 0040,0058) to re-analyse in place, '
                    'taking the function from the file name <id>_<module>_<name>.json')
    ap.add_argument('--backfill', action='store_true', help='recompute has_fixme and same_name_in_other_dlls on existing records')
    ap.add_argument('--renumber', action='store_true', help='renumber existing records to contiguous ids and write manifest.json')
    ap.add_argument('--lite', action='store_true', help='locate + code + compile context only; no dependency analysis (fast, no libclang)')
    ap.add_argument('--doc-index', default='', help='dataset/docs_index.tsv: only sample functions that have a documentation page')
    ap.add_argument('--keep-from', default='', help='seed the new dataset with the records of this existing dataset that pass the filters '
                    '(same order, converted to the requested shape), then sample the rest')
    ap.add_argument('--add-deps', action='store_true', help='run the dependency analysis on existing lite records (meta.deps_analysed = false)')
    ap.add_argument('--exclude', default='', help='comma-separated module!export never to sample; remembered in <out>/excluded.txt')
    a = ap.parse_args()
    src = os.path.realpath(a.src); WL.ROOT = src; WD.SRC = src; WD.BUILD = os.path.realpath(a.build) if a.build else src
    os.makedirs(a.out, exist_ok=True)
    if a.no_test_filter: globals()['test_mentions'] = lambda s, n, m: ['(test filter disabled)']

    doc_index = None
    if a.doc_index:
        import csv
        doc_index = {r['key'] for r in csv.DictReader(open(a.doc_index), delimiter='\t')}

    if a.add_deps:                      # reserved: enrich a lite dataset with the dependency analysis, in place
        n_ok = n_bad = 0
        for f in sorted(glob.glob(f'{a.out}/[0-9]*.json')):
            r = json.load(open(f))
            if r.get('meta', {}).get('deps_analysed'): continue
            rec, why = add_deps(src, r)
            if rec is None: print(f'{os.path.basename(f)}: {why}'); n_bad += 1; continue
            text = json.dumps(rec, indent=1, ensure_ascii=False)          # serialise first: never leave a half-written file
            open(f, 'w').write(text); n_ok += 1
            print(f'{os.path.basename(f)}: deps added ({len(rec["same_file_dependencies"])} same-file helpers)')
        print(f'deps added: {n_ok}, failed: {n_bad}'); return

    if a.renumber:                      # make ids contiguous 0001..N (order = current id) and write manifest.json
        files = sorted(glob.glob(f'{a.out}/[0-9]*.json'), key=lambda f: int(os.path.basename(f)[:4]))
        manifest = []
        for i, f in enumerate(files, 1):
            r = json.load(open(f)); old = r['id']; r['id'] = f'{i:04d}'
            new = os.path.join(a.out, f'{i:04d}_' + os.path.basename(f)[5:])
            for d in r.get('docs', []):                                   # attached documentation pages carry the id too
                if d.get('file', '').startswith(f'docs/{old}_'):
                    nd = d['file'].replace(f'docs/{old}_', f'docs/{r["id"]}_', 1)
                    src_p, dst_p = os.path.join(a.out, d['file']), os.path.join(a.out, nd)
                    if os.path.exists(src_p) and src_p != dst_p: os.rename(src_p, dst_p)
                    d['file'] = nd
            json.dump(r, open(f, 'w'), indent=1, ensure_ascii=False)
            if new != f: os.rename(f, new)
            fn = r['function']
            manifest.append(dict(id=r['id'], file=os.path.basename(new), module=fn['module'], export_name=fn['export_name'],
                                 name=fn['name'], source=f"{fn['file']}:{fn['start_line']}-{fn['end_line']}", side=fn['side'],
                                 deps_analysed=r.get('meta', {}).get('deps_analysed', True), docs=len(r.get('docs', [])),
                                 **({'kept_from': r['meta']['kept_from']} if r.get('meta', {}).get('kept_from') else {})))
            if old != r['id']: print(f'{old} -> {r["id"]}  {os.path.basename(new)}')
        json.dump(dict(count=len(manifest), records=manifest), open(os.path.join(a.out, 'manifest.json'), 'w'), indent=1, ensure_ascii=False)
        print(f'{len(manifest)} records renumbered; manifest.json written'); return

    if a.backfill:                      # recompute the cheap derived fields on existing records (no libclang)
        n = 0
        for f in sorted(glob.glob(f'{a.out}/[0-9]*.json')):
            r = json.load(open(f)); fn = r['function']
            fn['has_fixme'] = 'FIXME' in fn['code']
            fn['file_includes'] = file_includes(f"{src}/{fn['file']}")
            r['same_name_in_other_dlls'] = same_name_impls(src, fn['export_name'], f"{fn['file']}:{fn['start_line']}")
            for t in r.get('same_file_definitions', {}).get('types', []):   # re-extract type definitions (typedef start fix)
                txt, end = brace_block(f"{src}/{fn['file']}", t['start_line'])
                t['code'], t['start_line'], t['end_line'] = txt, end - txt.count('\n'), end
            json.dump(r, open(f, 'w'), indent=1, ensure_ascii=False); n += 1
        print(f'backfilled {n} records'); return

    if a.redo_errors or a.redo:
        wanted = set(x.strip().zfill(4) for x in a.redo.split(',') if x.strip())
        n_ok = n_bad = 0
        for f in sorted(glob.glob(f'{a.out}/[0-9]*.json')):
            old = json.load(open(f)); base = os.path.basename(f)
            if not ((a.redo_errors and old['meta']['parse_errors']) or base[:4] in wanted): continue
            fn = old['function']
            # the function is what the file name says (<module>!<name>); pick the exporter whose
            # resolution lands there, so native tests are looked up in the right module (user32, not win32u)
            fmod, fname = base[5:-5].split('_', 1)
            exp_mod, exp, chain, hits = None, None, None, None
            for m in [fn['resolution'][0].split('!')[0]] + fn['exported_by'] + [fmod]:
                e = fn['export_name'] if m != fmod else fname
                c, h = WL.resolve(m, e)
                if h and c[-1].split('!')[0] == fmod and re.search(r'(internal symbol |!)' + re.escape(fname) + r'\b', c[-1]):
                    exp_mod, exp, chain, hits = m, e, c, h; break
            rec, why = build_record(src, int(old['id']), exp_mod, exp, chain, hits[0], 0, not old.get('meta', {}).get('deps_analysed', True)) if hits else (None, 'cannot locate')
            if rec is None: print(f'{base}: {why}'); n_bad += 1; continue
            json.dump(rec, open(f, 'w'), indent=1, ensure_ascii=False); n_ok += 1
            print(f'{base}: {fn["module"]}!{fn["name"]} -> {rec["function"]["module"]}!{rec["function"]["name"]}, '
                  f'parse_errors {old["meta"]["parse_errors"]} -> {rec["meta"]["parse_errors"]}')
        print(f'redone: {n_ok}, failed: {n_bad}'); return

    # 1. candidate pool
    mods = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(f'{src}/dlls/*/Makefile.in'))
    pool, seen = [], set()
    for m, n in WL.all_exports(mods):
        if SKIP_MODULES.match(m) or not IDENT.match(n) or n in BOILERPLATE: continue
        if a.exclude_win16 and re.search(r'16$', m): continue
        if a.exclude_crt and re.match(r'(msvcr|ucrt|crtdll|msvcp)', m): continue
        chain, hits = WL.resolve(m, n)
        if len(hits) != 1 or '(macro)' in hits[0] or 'THIRD_PARTY' in chain[-1]: continue
        if hits[0] in seen: continue
        seen.add(hits[0]); pool.append((m, n, chain, hits[0]))
    random.Random(a.seed).shuffle(pool)
    print(f'candidate pool: {len(pool)} unique implementations', flush=True)

    # resume
    existing = [json.load(open(f)) for f in glob.glob(f'{a.out}/[0-9]*.json')]
    done = {r['function']['file'] + ':' + str(r['function']['start_line']) for r in existing}
    count = len(existing)                                         # records present (deleted ones are replaced)
    idx = max([int(r['id']) for r in existing] or [0])            # ids keep growing, never reused
    log = open(f'{a.out}/pipeline.log', 'a'); rejected = {}
    per_module = collections.Counter(r['function']['source_module'] for r in existing)
    t0 = time.time()
    if a.keep_from and not existing:                              # seed from another dataset, in its order
        kept = 0
        for f in sorted(glob.glob(f'{a.keep_from}/[0-9]*.json')):
            r = json.load(open(f)); fn = r['function']
            if doc_index is not None and fn['export_name'].lower() not in doc_index: continue
            m, n = fn['resolution'][0].split('!')[0], fn['export_name']
            chain, hits = WL.resolve(m, n)
            if not hits: continue
            rec, why = build_record(src, idx + 1, m, n, chain, hits[0], a.min_body, a.lite, doc_index)
            if rec is None: log.write(f'REJECT (keep-from) {m}!{n}: {why}\n'); continue
            rec['meta']['kept_from'] = dict(dataset=os.path.basename(os.path.normpath(a.keep_from)), id=r['id'])
            idx += 1; count += 1; done.add(hits[0]); per_module[hits[0].split('/')[1]] += 1; kept += 1
            fn2 = f'{a.out}/{idx:04d}_{rec["function"]["module"]}_{re.sub(r"[^A-Za-z0-9_]", "_", rec["function"]["name"])}.json'
            json.dump(rec, open(fn2, 'w'), indent=1, ensure_ascii=False)
            log.write(f'KEEP {idx} {m}!{n} (from {a.keep_from} {r["id"]}) -> {fn2}\n')
        print(f'kept {kept} records from {a.keep_from}; sampling {max(a.n - count, 0)} more', flush=True)
    excl_file = os.path.join(a.out, 'excluded.txt')
    excluded = set(l.strip() for l in open(excl_file)) if os.path.exists(excl_file) else set()
    if a.exclude:
        excluded |= {x.strip() for x in a.exclude.split(',') if x.strip()}
        open(excl_file, 'w').write('\n'.join(sorted(excluded)) + '\n')
    for m, n, chain, hit in pool:
        if count >= a.n: break
        if hit in done: continue
        if f'{m}!{n}' in excluded or any(f'{x}!{n}' in excluded for x in WD.exporters(n)):
            rejected['excluded'] = rejected.get('excluded', 0) + 1; continue
        if a.max_per_module and per_module[hit.split('/')[1]] >= a.max_per_module:
            rejected['module cap'] = rejected.get('module cap', 0) + 1; continue
        try:
            rec, why = build_record(src, idx + 1, m, n, chain, hit, a.min_body, a.lite, doc_index)
        except Exception as e:
            rec, why = None, f'exception: {type(e).__name__}: {e}'
        if rec is None:
            rejected[why.split(':')[0]] = rejected.get(why.split(':')[0], 0) + 1
            log.write(f'REJECT {m}!{n} {hit}: {why}\n'); log.flush(); continue
        idx += 1; count += 1; done.add(hit); per_module[hit.split('/')[1]] += 1
        fn = f'{a.out}/{idx:04d}_{rec["function"]["module"]}_{re.sub(r"[^A-Za-z0-9_]", "_", rec["function"]["name"])}.json'
        json.dump(rec, open(fn, 'w'), indent=1, ensure_ascii=False)
        log.write(f'OK {idx} {m}!{n} -> {fn} ({time.time() - t0:.0f}s)\n'); log.flush()
        if count % 25 == 0: print(f'{count}/{a.n} done, {time.time() - t0:.0f}s, rejected so far: {rejected}', flush=True)
    print(f'finished: {count} records in {a.out}; rejected: {rejected}')

if __name__ == '__main__':
    main()
