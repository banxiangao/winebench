#!/usr/bin/env python3
"""wine_deps.py - static dependency extraction for a Wine function (libclang).

    python3 wine_deps.py [options] 'kernel32!CreateFileW'          # an export
    python3 wine_deps.py [options] dlls/kernelbase/file.c:CreateFileW   # file:function

Options:
    --src DIR      Wine source root (default: $WINE_SRC or .)
    --build DIR    build dir holding generated headers (widl output, config.h)
    --depth N      max depth when following module-internal callees (default 8)
    --max N        max number of internal functions to follow (default 300)
    --context F    also write a Markdown bundle with the code of the target,
                   its internal callees and module-private types/macros/globals
    --same-file-only  only expand callees defined in the target's own file; callees in other
                   files of the module are listed as kind "same_module_other_file"
Output: JSON on stdout.

Each dependency is classified as
    internal_functions  defined in the same module (same PE/unix side): followed recursively
    external_functions  other DLL exports (with exporting modules + resolved implementation),
                        inline helpers from public headers, or system (libc) functions
    types / globals / macros  with origin: module | public (include/) | system
    server_requests     SERVER_START_REQ(x)  -> server/ DECL_HANDLER(x)
    unix_calls          WINE_UNIX_CALL/UNIX_CALL -> function in __wine_unix_call_funcs[]
and every internal helper gets "exclusive": true when nothing outside the closure uses it,
i.e. it belongs to the implementation and must be hidden together with the target.
"""
import os, re, sys, json, glob, argparse
from clang import cindex as ci
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wine_locate as WL

K = ci.CursorKind

def _register_missing_kinds():
    """pip's cindex.py lags behind libclang: cursor-kind ids it does not know (e.g. 437, the
    flag_enum attribute used by macOS SDK headers) make Cursor.kind raise ValueError.
    Register known gaps, and map any other unknown id to a placeholder instead of crashing."""
    for i, n in [(437, 'FLAG_ENUM_ATTR')]:
        try: K.from_id(i)
        except ValueError: setattr(K, n, K(i))
    orig = K.from_id
    def from_id(i):
        try: return orig(i)
        except ValueError:
            k = K(i); setattr(K, f'UNKNOWN_KIND_{i}', k); return k
    K.from_id = staticmethod(from_id)
_register_missing_kinds()

SRC = BUILD = None
ARCH = 'x86_64'          # PE target arch; Win16 modules (*16) are always parsed as i686
_gcc = sorted(glob.glob('/usr/lib/gcc/*/*/include'))
GCC_INC = ([d for d in _gcc if 'mingw' not in d] or _gcc or [None])[-1]   # the native compiler's headers, not a cross compiler's
                                                                          # (in the Vulcan container x86_64-w64-mingw32 sorts last: its stddef.h is not found)
# host system headers for the Unix side: gcc's private headers on Linux, the SDK sysroot on macOS
HOST_SYS = []          # Unix side: host system headers
BUILTIN_INC = []       # PE side: only the compiler's builtin headers (x86intrin.h, immintrin.h ...) that Wine's own headers include
if sys.platform == 'darwin':
    # the pip libclang has no builtin headers (stdarg.h, limits.h...) and does not know the SDK:
    # borrow Apple clang's resource dir and point at the SDK explicitly
    _sdk = os.popen('xcrun --show-sdk-path 2>/dev/null').read().strip()
    _res = os.popen('xcrun clang -print-resource-dir 2>/dev/null').read().strip()
    if _res and os.path.isdir(f'{_res}/include'): HOST_SYS += ['-isystem', f'{_res}/include']; BUILTIN_INC = ['-isystem', f'{_res}/include']
    if _sdk: HOST_SYS += ['-isysroot', _sdk, '-isystem', f'{_sdk}/usr/include']
elif GCC_INC: HOST_SYS = BUILTIN_INC = ['-isystem', GCC_INC]

# ---------------------------------------------------------------- paths / makefiles
def rel(p):
    p = os.path.realpath(p)
    if p.startswith(SRC + '/'): return p[len(SRC) + 1:]
    if BUILD and p.startswith(BUILD + '/'): return 'build:' + p[len(BUILD) + 1:]
    return p

def origin(p):
    r = rel(p)
    if r.startswith(('include/', 'build:include/')): return 'public'
    if r.startswith(('dlls/', 'programs/', 'build:dlls/', 'build:programs/')): return 'module'
    return 'system'

def module_dir(mod):
    for b in ('dlls', 'programs'):
        if os.path.isdir(f'{SRC}/{b}/{mod}'): return f'{b}/{mod}'
    return None

_mk = {}
def makevars(mdir):
    if mdir not in _mk:
        v, key = {}, None
        try:
            for l in open(f'{SRC}/{mdir}/Makefile.in'):
                l = l.rstrip('\n')
                if key:                                   # continuation line
                    v[key] += l.rstrip('\\').split()
                    if not l.endswith('\\'): key = None
                    continue
                if '=' in l and not l.startswith('#'):
                    k, _, x = l.partition('='); k = k.strip()
                    v[k] = x.rstrip('\\').split()
                    if l.endswith('\\'): key = k
        except OSError: pass
        _mk[mdir] = v
    return _mk[mdir]

_unix = {}
def is_unix_file(path):
    path = os.path.realpath(path)
    if path not in _unix:
        r = rel(path)
        _unix[path] = '/unix/' in r or '#pragma makedep unix' in open(path, errors='ignore').read()
    return _unix[path]

_extlib = None
def extlib_cflags(var):
    """$(SYMCRYPT_PE_CFLAGS) -> ['-I<src>/libs/symcrypt/inc'] (bundled-library defaults from configure.ac)"""
    global _extlib
    if _extlib is None:
        _extlib = {}
        for l in open(f'{SRC}/configure.ac', errors='ignore'):
            m = re.match(r'WINE_EXTLIB_FLAGS\((\w+),[^,]*,[^,]*(?:,\s*"([^"]*)")?\)', l.replace('"c++ ', '"c++_').strip())
            if m and m.group(2): _extlib[m.group(1)] = m.group(2).replace('\\$(top_srcdir)', SRC).replace('$(top_srcdir)', SRC).split()
    m = re.match(r'\$\((\w+)_PE_CFLAGS\)', var)
    return _extlib.get(m.group(1), []) if m else []

CRT = re.compile(r'^(msvcr|ucrt|crtdll)')
def crt_define(mod, v):
    imps = [i for i in v.get('IMPORTS', []) if CRT.match(i)]
    crt = imps[0] if imps else None
    if not crt:
        if '-nodefaultlibs' in v.get('EXTRADLLFLAGS', []): return '-D_MSVCR_VER=0'
        crt = mod if CRT.match(mod) else 'ucrtbase'
    if crt.startswith('ucrt'): return '-D_UCRT'
    m = re.match(r'msvcr(\d+)', crt)
    return f'-D_MSVCR_VER={m.group(1) if m else 0}'

def clang_args(path, mod):
    """Approximate the flags makedep would use for this source file."""
    mdir = module_dir(mod); v = makevars(mdir)
    inc = [f'-I{BUILD}/{mdir}', f'-I{SRC}/{mdir}']
    if v.get('PARENTSRC'): inc.append('-I' + os.path.normpath(f'{SRC}/{mdir}/{v["PARENTSRC"][0]}'))
    inc += [f'-I{BUILD}/include', f'-I{SRC}/include']
    for x in v.get('EXTRAINCL', []):
        inc += extlib_cflags(x) if x.startswith('$(') else [x]
    defs = ['-D__WINESRC__'] + [d for d in v.get('EXTRADEFS', []) if '$(' not in d]
    common = ['-x', 'c', '-std=gnu11', '-ferror-limit=0', '-Wno-everything']
    if is_unix_file(path):
        return common + ['-DWINE_UNIX_LIB', '-D_GNU_SOURCE', '-fPIC'] + inc + defs + HOST_SYS
    arch = 'i686' if mod.endswith('16') else ARCH
    return common + [f'--target={arch}-w64-windows-gnu', '-nostdinc', '-fshort-wchar', '-fno-builtin',
                     '-D__WINE_PE_BUILD'] + inc + [f'-I{SRC}/include/msvcrt', crt_define(mod, v)] + defs + BUILTIN_INC

# ---------------------------------------------------------------- libclang helpers
_tu, _index = {}, None
def parse(path, mod):
    global _index
    key = (os.path.realpath(path), mod, ARCH)
    if key not in _tu:
        _index = _index or ci.Index.create()
        args = clang_args(path, mod)
        tu = _index.parse(path, args=args, options=ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        errs = [d for d in tu.diagnostics if d.severity >= ci.Diagnostic.Error]
        macros = {}
        for c in tu.cursor.get_children():
            if c.kind == K.MACRO_INSTANTIATION and c.location.file:
                macros.setdefault(os.path.realpath(c.location.file.name), []).append(c)
        _tu[key] = dict(tu=tu, args=args, errors=errs, macros=macros)
    return _tu[key]

def same_file(c, path):
    return c.location.file is not None and os.path.realpath(c.location.file.name) == os.path.realpath(path)

def find_function(tu, path, name, line=None):
    cands = [c for c in tu.cursor.walk_preorder()
             if c.kind == K.FUNCTION_DECL and c.spelling == name and c.is_definition() and same_file(c, path)]
    if line and cands: cands.sort(key=lambda c: abs(c.location.line - line))
    return cands[0] if cands else None

def loc(c):
    return f'{rel(c.location.file.name)}:{c.location.line}' if c and c.location.file else None

def extent_text(c):
    f = c.extent.start.file.name
    L = open(f, errors='ignore').read().split('\n')
    return '\n'.join(L[c.extent.start.line - 1:c.extent.end.line])

def type_decl(c):
    """Return (name, decl cursor) for a type reference."""
    if c is None or c.kind in (K.NO_DECL_FOUND, K.TEMPLATE_TYPE_PARAMETER): return None
    name = c.spelling or c.type.spelling
    return (name, c) if name and c.location.file else None

# ---------------------------------------------------------------- global indexes
_exporters = None
def exporters(name):
    """Modules whose .spec exports `name` (non-stub)."""
    global _exporters
    if _exporters is None:
        _exporters = {}
        for f in glob.glob(f'{SRC}/dlls/*/*.spec'):
            m = os.path.basename(os.path.dirname(f))
            for l in open(f, errors='ignore'):
                x = WL.SPEC.match(l)
                if x and x.group(1) != 'stub': _exporters.setdefault(x.group(3), []).append(m)
    return _exporters.get(name, [])

_handlers = None
def server_handler(req):
    global _handlers
    if _handlers is None:
        _handlers = {}
        for f in sorted(glob.glob(f'{SRC}/server/*.c')):
            for i, l in enumerate(open(f, errors='ignore')):
                m = re.match(r'DECL_HANDLER\(\s*(\w+)\s*\)', l)
                if m: _handlers[m.group(1)] = f'{rel(f)}:{i+1}'
    return _handlers.get(req)

_unix_tables = {}
def unix_table(mod):
    """__wine_unix_call_funcs[] of a module: list of names, or dict for designated initializers."""
    if mod not in _unix_tables:
        tab = None
        mdir = module_dir(mod)
        for f in sorted(glob.glob(f'{SRC}/{mdir}/**/*.c', recursive=True)):
            if '/tests/' in f: continue
            t = open(f, errors='ignore').read()
            m = re.search(r'__wine_unix_call_funcs\s*\[\s*\]\s*=\s*\{(.*?)\};', t, re.S)
            if not m: continue
            body = re.sub(r'/\*.*?\*/|//[^\n]*', '', m.group(1), flags=re.S)
            if re.search(r'^\s*#', body, re.M): sys.stderr.write(f'warning: #if inside unix call table of {mod}\n')
            body = re.sub(r'^\s*#.*$', '', body, flags=re.M)
            if '[' in body: tab = dict(re.findall(r'\[\s*(\w+)\s*\]\s*=\s*(\w+)', body))
            else: tab = [x.strip() for x in body.split(',') if x.strip()]
            tab = (tab, f); break
        _unix_tables[mod] = tab
    return _unix_tables[mod]

def module_def_dirs(mod, unix):
    mdir = module_dir(mod); v = makevars(mdir)
    dirs = [mdir]
    if v.get('PARENTSRC'): dirs.append(os.path.normpath(f'{mdir}/{v["PARENTSRC"][0]}'))
    if unix and os.path.isdir(f'{SRC}/{mdir}/unix'): dirs.insert(0, f'{mdir}/unix')
    return dirs

def find_internal_def(name, mod, unix):
    """Definition of `name` elsewhere in the same module and on the same (PE/unix) side."""
    for d in module_def_dirs(mod, unix):
        for h in WL.index(d)[0].get(name, []):
            f, line = h.rsplit(':', 1)
            if is_unix_file(f'{SRC}/{f}') == unix: return f'{SRC}/{f}', int(line)
    return None

COMMENT = re.compile(r'^\s*(/\*|//|\*\s|\*/|\*$)')

def other_module_refs(names, mdirs):
    """files outside the module that mention any of `names` (e.g. ntdll.so helpers used by win32u)"""
    res = {}
    if not names: return res
    import subprocess, shutil
    roots = [f'{SRC}/{d}' for d in ('dlls', 'programs', 'server', 'loader')]
    own = tuple(f'{SRC}/{d}/' for d in mdirs)
    if shutil.which('rg'):
        cmd = ['rg', '-o', '-w', '-N', '--no-heading', '--with-filename', '-g', '*.c', '-g', '*.h', '-g', '!tests/']
        for n in names: cmd += ['-e', n]
        txt = subprocess.run(cmd + roots, capture_output=True, text=True).stdout
        for line in txt.splitlines():
            f, _, n = line.rpartition(':')
            if not f.startswith(own): res.setdefault(n, set()).add(rel(f))
    else:
        pat = re.compile(r'\b(' + '|'.join(map(re.escape, names)) + r')\b')
        for r in roots:
            for dp, dn, fn in os.walk(r):
                dn[:] = [x for x in dn if x != 'tests']
                for f in fn:
                    p = os.path.join(dp, f)
                    if f.endswith(('.c', '.h')) and not p.startswith(own):
                        for n in set(pat.findall(open(p, errors='ignore').read())): res.setdefault(n, set()).add(rel(p))
    return res

def pointer_targets(member, mod):
    """Functions assigned to a function-pointer field/variable in this module:
    `.member = func`, `->member = func`, `member = func`  (positional initializers are not resolved)"""
    pat = re.compile(r'(?:^|[.\s>])' + re.escape(member) + r'\s*=\s*&?(\w+)\s*[,;}]')
    out = []
    mdir = module_dir(mod)
    for d in module_def_dirs(mod, True):
        for f in WL.cfiles(d):
            for i, l in enumerate(WL.lines(f)):
                m = pat.search(l)
                if m and m.group(1) not in ('NULL', '0') and not m.group(1).isdigit(): out.append(f'{m.group(1)} @ {rel(f)}:{i+1}')
    return sorted(set(out))[:10]

def own_export(mod, name):
    if not os.path.isdir(f'{SRC}/dlls/{mod}'): return False
    e = WL.spec_entry(mod, name)
    return e is not None and e.group(1) != 'stub'

def resolve_impl(name, mod):
    ex = exporters(name)
    if not ex: return None, []
    pref = [m for m in makevars(module_dir(mod)).get('IMPORTS', []) + ['kernelbase', 'kernel32', 'ntdll'] if m in ex]
    m = (pref or ex)[0]
    chain, hits = WL.resolve(m, name)
    return m, hits

# ---------------------------------------------------------------- analysis
def analyze(path, name, mod, line=None, max_depth=8, max_funcs=300, follow_files=True):
    unix = is_unix_file(path)
    P = parse(path, mod)
    root = find_function(P['tu'], path, name, line)
    if root is None and not unix:
        global ARCH
        for alt in ('i686', 'aarch64', 'x86_64'):          # definition may sit in an arch-specific #if branch
            if alt == ARCH: continue
            old, ARCH = ARCH, alt
            P = parse(path, mod); root = find_function(P['tu'], path, name, line)
            if root is not None:
                sys.stderr.write(f'note: {name} is not compiled as C for {old} (asm or #if); analysed for {alt}\n'); break
            ARCH = old
    if root is None: raise SystemExit(f'function {name} not found in {rel(path)} (inactive #if branch or asm/macro-generated)')
    out = dict(target=dict(name=name, module=mod, file=rel(path), start=root.extent.start.line,
                           end=root.extent.end.line, side='unix' if unix else 'PE',
                           arch='host' if unix else ('i686' if mod.endswith('16') else ARCH)),
               parse=[], internal_functions=[], external_functions=[], types=[], globals=[],
               macros=[], server_requests=[], unix_calls=[])
    seen_tu = set()
    internal = {}                          # name -> record (incl. cursor)
    ext, types, gvars, macros, reqs, ucalls = {}, {}, {}, {}, {}, {}
    via_macro = set()
    indirect = {}
    queue = [(root, path, 0, None)]
    while queue:
        fc, fpath, depth, caller = queue.pop(0)
        key = fc.spelling
        if key in internal:
            if caller: internal[key]['called_from'].add(caller)
            continue
        P = parse(fpath, mod)
        if fpath not in seen_tu:
            seen_tu.add(fpath)
            out['parse'].append(dict(file=rel(fpath), errors=len(P['errors']),
                                     first_errors=[f'{rel(d.location.file.name) if d.location.file else "?"}:{d.location.line}: {d.spelling}'
                                                   for d in P['errors'][:3]]))
        internal[key] = dict(name=key, file=rel(fpath), start=fc.extent.start.line, end=fc.extent.end.line,
                             static=fc.storage_class == ci.StorageClass.STATIC, depth=depth,
                             called_from=set([caller] if caller else []), cursor=fc, path=fpath)
        for c in fc.walk_preorder():
            k = c.kind
            if k == K.DECL_REF_EXPR or k == K.MEMBER_REF_EXPR or k == K.TYPE_REF:
                r = c.referenced
                if r is None: continue
                if k == K.MEMBER_REF_EXPR:
                    t = type_decl(r.semantic_parent)
                    if t: types.setdefault(t[0], t[1])
                elif k == K.TYPE_REF:
                    t = type_decl(r)
                    if t:
                        types.setdefault(t[0], t[1])
                        if r.kind == K.TYPEDEF_DECL:      # follow typedef to its struct/enum
                            u = type_decl(r.underlying_typedef_type.get_declaration())
                            if u and origin(u[1].location.file.name) == 'module': types.setdefault(u[0], u[1])
                elif r.kind == K.ENUM_CONSTANT_DECL:
                    t = type_decl(r.semantic_parent)
                    if t: types.setdefault(t[0], t[1])
                elif r.kind == K.VAR_DECL and r.semantic_parent and r.semantic_parent.kind == K.TRANSLATION_UNIT:
                    gvars.setdefault(r.spelling, r.get_definition() or r)
                elif r.kind == K.FUNCTION_DECL:
                    fn = r.spelling
                    if c.location.file and fn not in WL.lines(os.path.realpath(c.location.file.name))[c.location.line - 1]:
                        via_macro.add(fn)             # e.g. wcsnicmp() -> ntdll_wcsnicmp(): text search can't see users
                    if fn.startswith('__builtin') or fn == key: continue
                    d = r.get_definition()
                    if fn in ext: continue
                    if own_export(mod, fn):           # another API of the same module: an interface, not a helper
                        chain, hits = WL.resolve(mod, fn)
                        ext[fn] = dict(name=fn, kind='module_export', decl=loc(r), origin=origin(r.location.file.name),
                                       exported_by=exporters(fn), impl_module=mod, impl=hits)
                        continue
                    if d is not None and origin(d.location.file.name) == 'module' and same_file(d, fpath):
                        if depth + 1 <= max_depth and len(internal) < max_funcs: queue.append((d, fpath, depth + 1, key))
                        elif fn not in internal: ext.setdefault(fn, dict(name=fn, kind='internal_not_followed', decl=loc(d)))
                        continue
                    hit = find_internal_def(fn, mod, unix) if origin(r.location.file.name) != 'system' else None
                    if hit and not follow_files:          # same module, other file: report, don't expand
                        ext[fn] = dict(name=fn, kind='same_module_other_file', decl=f'{rel(hit[0])}:{hit[1]}', origin='module')
                        continue
                    if hit:
                        tp = parse(hit[0], mod)
                        dc = find_function(tp['tu'], hit[0], fn, hit[1])
                        if dc is not None and depth + 1 <= max_depth and len(internal) < max_funcs:
                            queue.append((dc, hit[0], depth + 1, key)); continue
                    o = origin(r.location.file.name)
                    rec = dict(name=fn, decl=loc(r), origin=o)
                    if d is not None and o == 'public': rec['kind'] = 'inline_header'
                    elif o == 'system': rec['kind'] = 'system'
                    else:
                        em, hits = resolve_impl(fn, mod)
                        rec.update(kind='dll_export' if em else 'unresolved', exported_by=exporters(fn), impl_module=em, impl=hits)
                    ext[fn] = rec
            elif k == K.CALL_EXPR and (c.referenced is None or c.referenced.kind != K.FUNCTION_DECL):
                callee = next(c.get_children(), None)
                expr = ''.join(t.spelling for t in callee.get_tokens()) if callee is not None else ''
                member = re.findall(r'(?:\.|->)(\w+)$', expr) or re.findall(r'^\(?\*?(\w+)\)?$', expr)
                if expr and expr not in indirect:
                    indirect[expr] = dict(expr=expr, in_function=key, at=f'{rel(c.location.file.name)}:{c.location.line}' if c.location.file else None,
                                          candidates=pointer_targets(member[0], mod) if member else [])
            elif k == K.CALL_EXPR and c.spelling == '__wine_unix_call':
                for a in c.walk_preorder():
                    if a.kind == K.DECL_REF_EXPR and a.referenced is not None and a.referenced.kind == K.ENUM_CONSTANT_DECL:
                        code = a.referenced.spelling; ent = unix_table(mod); fn = None
                        if ent:
                            tab, tf = ent
                            fn = tab.get(code) if isinstance(tab, dict) else (tab[a.referenced.enum_value] if a.referenced.enum_value < len(tab) else None)
                        hit = find_internal_def(fn, mod, True) if fn else None
                        ucalls.setdefault(code, dict(code=code, function=fn, impl=f'{rel(hit[0])}:{hit[1]}' if hit else None))
                        break
        # macros used inside this function + SERVER_START_REQ
        for m in P['macros'].get(os.path.realpath(fc.extent.start.file.name), []):
            if fc.extent.start.line <= m.location.line <= fc.extent.end.line:
                d = m.referenced
                macros.setdefault(m.spelling, d)
                if m.spelling == 'SERVER_START_REQ':
                    toks = [t.spelling for t in m.get_tokens()]
                    if len(toks) >= 3: reqs.setdefault(toks[2], dict(request=toks[2], handler=server_handler(toks[2])))

    # exclusivity: a helper belongs to the implementation only if every reference to it
    # sits inside the target or inside other exclusive helpers (fixpoint)
    spans = {}
    for r in internal.values(): spans.setdefault(os.path.realpath(r['path']), []).append((r['start'], r['end'], r['name']))
    mdirs = module_def_dirs(mod, unix)
    modfiles = [f for d in mdirs for f in WL.cfiles(d)] + \
               [f for d in mdirs for f in glob.glob(f'{SRC}/{d}/**/*.h', recursive=True) if '/tests/' not in f]
    helpers = list(internal.values())[1:]
    wide = [r for r in helpers if not r['static'] or r['path'].endswith('.h')]
    foreign = other_module_refs([r['name'] for r in wide], mdirs)
    users = {}
    for r in helpers:
        files = [r['path']] if r['static'] and not r['path'].endswith('.h') else modfiles + [r['path']]
        pat = re.compile(r'\b' + re.escape(r['name']) + r'\b')
        inside, outside = set(), []
        for f in set(os.path.realpath(x) for x in files):
            for i, l in enumerate(WL.lines(f)):
                if not pat.search(l) or COMMENT.match(l): continue
                if l[:1].strip() and l.rstrip().endswith(';'): continue          # prototype
                enc = [n for s_, e_, n in spans.get(f, []) if s_ <= i + 1 <= e_]
                if enc:
                    if enc[0] != r['name']: inside.add(enc[0])
                elif not (r['start'] <= i + 1 <= r['end'] and f == os.path.realpath(r['path'])):
                    outside.append(f'{rel(f)}:{i+1}')
        outside += [f'{f} (other module)' for f in sorted(foreign.get(r['name'], []))]
        if r['name'] in via_macro: outside.append('referenced through a macro (conservatively shared)')
        users[r['name']] = (inside, outside)
    excl, changed = {name}, True
    while changed:
        changed = False
        for n, (inside, outside) in users.items():
            if n not in excl and not outside and inside <= excl:
                excl.add(n); changed = True
    for r in list(internal.values())[1:]:
        inside, outside = users[r['name']]
        r['exclusive'] = r['name'] in excl
        if outside: r['used_outside'] = outside[:5]
        elif not r['exclusive']: r['used_by_shared'] = sorted(inside - excl)

    # assemble
    for r in internal.values():
        out['internal_functions'].append({k: (sorted(v) if isinstance(v, set) else v) for k, v in r.items()
                                          if k not in ('cursor', 'path')})
    out['target'].update(exclusive_helpers=[r['name'] for r in out['internal_functions'][1:] if r.get('exclusive')])
    out['external_functions'] = sorted(ext.values(), key=lambda x: (x.get('kind', ''), x['name']))
    for n, d in sorted(types.items()):
        out['types'].append(dict(name=n, kind=d.kind.name.lower(), decl=loc(d), origin=origin(d.location.file.name)))
    for n, d in sorted(gvars.items()):
        out['globals'].append(dict(name=n, decl=loc(d), origin=origin(d.location.file.name),
                                   static=d.storage_class == ci.StorageClass.STATIC, type=d.type.spelling))
    for n, d in sorted(macros.items()):
        o = origin(d.location.file.name) if d is not None and d.location.file else 'builtin'
        out['macros'].append(dict(name=n, decl=loc(d) if d is not None else None, origin=o))
    out['server_requests'] = sorted(reqs.values(), key=lambda x: x['request'])
    out['unix_calls'] = sorted(ucalls.values(), key=lambda x: x['code'])
    out['indirect_calls'] = list(indirect.values())
    out['summary'] = dict(internal=len(out['internal_functions']) - 1, exclusive=len(out['target']['exclusive_helpers']),
                          external=len(out['external_functions']), types=len(out['types']),
                          module_types=sum(t['origin'] == 'module' for t in out['types']),
                          globals=len(out['globals']), macros=len(out['macros']),
                          server_requests=len(out['server_requests']), unix_calls=len(out['unix_calls']),
                          indirect_calls=len(out['indirect_calls']),
                          parse_errors=sum(p['errors'] for p in out['parse']))
    return out, internal, types, gvars, macros

def write_context(fname, out, internal, types, gvars, macros):
    """Markdown bundle: target + internal callees + module-private definitions."""
    md = [f"# {out['target']['name']} ({out['target']['module']}, {out['target']['side']})\n"]
    def block(title, text): md.append(f'## {title}\n```c\n{text}\n```\n')
    for i, r in enumerate(internal.values()):
        tag = 'target' if i == 0 else ('exclusive helper' if r.get('exclusive') else 'shared helper')
        block(f"{r['name']} [{tag}] {rel(r['path'])}:{r['start']}", extent_text(r['cursor']))
    for n, d in sorted(types.items()):
        if origin(d.location.file.name) == 'module' and d.extent.start.file: block(f'type {n} {loc(d)}', extent_text(d))
    for n, d in sorted(gvars.items()):
        if origin(d.location.file.name) == 'module': block(f'global {n} {loc(d)}', extent_text(d))
    for n, d in sorted(macros.items()):
        if d is not None and d.location.file and origin(d.location.file.name) == 'module': block(f'macro {n} {loc(d)}', '#define ' + extent_text(d).strip())
    md.append('## External functions\n' + '\n'.join(f"- `{e['name']}` ({e.get('kind')}) {e.get('decl') or ''}" for e in out['external_functions']))
    open(fname, 'w').write('\n'.join(md) + '\n')

def main():
    global SRC, BUILD
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('target'); ap.add_argument('--src', default=os.environ.get('WINE_SRC', '.'))
    ap.add_argument('--build', default=os.environ.get('WINE_BUILD'))
    ap.add_argument('--depth', type=int, default=8); ap.add_argument('--max', type=int, default=300)
    ap.add_argument('--context')
    ap.add_argument('--arch', default='x86_64', choices=['x86_64', 'i686', 'aarch64'], help='PE target arch')
    ap.add_argument('--same-file-only', action='store_true', help='do not expand callees defined in other files of the module')
    a = ap.parse_args()
    global ARCH
    ARCH = a.arch
    SRC = os.path.realpath(a.src); BUILD = os.path.realpath(a.build) if a.build else SRC
    WL.ROOT = SRC
    resolution = None
    if '!' in a.target:                                       # module!export
        mod, exp = a.target.split('!')
        chain, hits = WL.resolve(mod, exp)
        resolution = chain
        if not hits: raise SystemExit('cannot locate implementation:\n  ' + '\n  '.join(chain))
        last = chain[-1]
        mod = last.split('!')[0].strip()
        m = re.search(r'internal symbol (\w+)', last)
        name = m.group(1) if m else re.match(r'[^!]+!([^\s\[]+)', last).group(1)
        f, line = hits[0].split(' ')[0].rsplit(':', 1)
        path, line = f'{SRC}/{f}', int(line)
    else:                                                      # file.c:function
        f, name = a.target.rsplit(':', 1); path = os.path.realpath(f if os.path.isabs(f) else f'{SRC}/{f}')
        parts = rel(path).split('/'); mod = parts[1]; line = None
    out, internal, types, gvars, macros = analyze(path, name, mod, line, a.depth, a.max, not a.same_file_only)
    if resolution: out['target']['resolution'] = resolution
    if a.context: write_context(a.context, out, internal, types, gvars, macros)
    json.dump(out, sys.stdout, indent=1); print()

if __name__ == '__main__':
    main()
