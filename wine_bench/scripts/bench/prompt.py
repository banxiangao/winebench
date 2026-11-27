"""Prompt building: a template with {{placeholders}} + a record (+ an upstream reply) -> system / messages.

Placeholders come from three sources:
  1. plain fields:   {{dll}} {{function}} {{file}} {{start_line}} {{end_line}} {{signature}} {{project_name}} {{answer_language}}
  2. sections:       functions registered in SECTIONS, each builds one block of text from the record
                     under the control of the stage's [inputs] switches (switch off -> empty text)
  3. anything else is left untouched

A section receives (rec, ic, scn, ctx): the dataset record, the stage's [inputs] table, the scenario,
and ctx = {"from_model": name, "upstream": the reply of the previous stage for this id (or None)}.
Adding a new kind of input for a new scenario = add one function here decorated with
@section('name'); then use {{name}} in that scenario's templates.
"""
import json

SECTIONS = {}
def section(name):
    def deco(f): SECTIONS[name] = f; return f
    return deco

def fill(template, **vars):
    for k, v in vars.items(): template = template.replace('{{' + k + '}}', str(v))
    return template

def clip(code, max_lines):
    lines = code.split('\n')
    if not max_lines or len(lines) <= max_lines: return code
    return '\n'.join(lines[:max_lines]) + f'\n/* ... {len(lines) - max_lines} more lines omitted ... */'

def none_text(ic): return ic.get('none_text', 'None provided.')

def sampled_dll(rec):
    """the DLL whose export was sampled (user32 for DrawMenuBar, even though win32u implements it)"""
    return rec['function']['resolution'][0].split('!')[0]

# ---------------------------------------------------------------- sections
@section('extra_lines')
def extra_lines(rec, ic, scn, ctx=None):
    fn = rec['function']; dll = sampled_dll(rec); out = []
    own_impl = {m for x in rec['same_name_in_other_dlls'] for m in x.get('exported_by', [x['module']])}
    others = [m for m in fn['exported_by'] if m != dll and m not in own_impl]      # re-exports of this very code
    if ic.get('show_all_exporters', True) and others: out.append(f'Also exported by: {", ".join(others)}')
    if ic.get('show_internal_name', True) and fn['name'] != fn['export_name']:
        out.append(f'Implemented in {fn["module"]} under the internal name {fn["name"]}')
    if ic.get('show_signature', False): out.append(f'Prototype: {fn["signature"]}')
    return '\n'.join(out) + '\n' if out else ''

@section('code')
def code(rec, ic, scn, ctx=None):
    """the original implementation (for a stage that is shown it; none of the current scenarios)"""
    if not ic.get('show_code', False): return ''
    fn = rec['function']; c = clip(fn['code'], ic.get('code_max_lines', 0))
    if ic.get('show_header_comment', False) and fn.get('header_comment'): c = fn['header_comment'] + '\n' + c
    return c

@section('same_name_section')
def same_name(rec, ic, scn, ctx=None):
    """independent same-named implementations in other DLLs"""
    if not ic.get('show_same_name_code', True): return none_text(ic)
    items = rec['same_name_in_other_dlls']
    if ic.get('same_name_exclude_win16', True): items = [x for x in items if not x.get('win16')]
    items = [x for x in items if x.get('code')][:ic.get('same_name_max_items', 4)]
    if not items: return none_text(ic)
    tpl = scn.template(ic.get('same_name_item_template', 'templates/same_name_item.txt'))
    return '\n'.join(fill(tpl, module=x['module'], file=x['file'], code=clip(x['code'], ic.get('same_name_max_lines', 0)),
                          exported_by=', '.join(x.get('exported_by', [x['module']]))) for x in items)

@section('same_file_deps_section')
def same_file_deps(rec, ic, scn, ctx=None):
    """helper functions from the same file, with code"""
    if not ic.get('show_same_file_deps', False): return ''
    all_deps = rec['same_file_dependencies']                 # ordered by call distance: direct callees first
    if not all_deps: return none_text(ic)
    mx = ic.get('same_file_deps_max_items', 0)
    deps, rest = (all_deps[:mx], all_deps[mx:]) if mx else (all_deps, [])
    tpl = scn.template(ic.get('dependency_item_template', 'templates/dependency_item.txt'))
    out = '\n'.join(fill(tpl, name=d['name'], file=d['file'], start_line=d['start_line'], end_line=d['end_line'],
                         code=clip(d['code'], ic.get('same_file_deps_max_lines', 0)),
                         shared='only used by this function' if d.get('exclusive_to_target') else 'also used elsewhere in the module')
                    for d in deps)
    if rest: out += f"\n{len(rest)} more helpers from the same file are not shown: " + ', '.join(d['name'] for d in rest)
    return out

@section('same_file_defs_section')
def same_file_defs(rec, ic, scn, ctx=None):
    """private types / globals / macros from the same file"""
    if not ic.get('show_same_file_defs', False): return ''
    out = []
    for kind in ('types', 'globals', 'macros'):
        for d in rec['same_file_definitions'].get(kind, []):
            if d['name'].startswith('__wine_dbch'): continue                      # debug channel declaration: noise
            out.append(f"/* {kind[:-1]} {d['name']}, {rec['function']['file']}:{d['start_line']} */\n{clip(d['code'], ic.get('same_file_defs_max_lines', 0))}")
    return ('```c\n' + '\n\n'.join(out) + '\n```') if out else none_text(ic)

@section('other_deps_section')
def other_deps(rec, ic, scn, ctx=None):
    """everything else the function calls: names and locations only"""
    if not ic.get('show_other_deps', False): return ''
    o = rec['other_dependencies']; lines = []
    if o.get('same_module_other_files'):
        lines.append('Functions in other files of the same module: ' + ', '.join(f"{d['name']} ({d['file']})" for d in o['same_module_other_files']))
    if o.get('same_module_exports'): lines.append('Other exported APIs of the same module: ' + ', '.join(d['name'] for d in o['same_module_exports']))
    if o.get('other_dll_exports'): lines.append('APIs of other DLLs: ' + ', '.join(f"{d['name']} ({d['module']})" for d in o['other_dll_exports']))
    inl = [x for x in o.get('header_inline', []) if not x.startswith(('wine_dbg', '__wine_dbg'))]    # TRACE/FIXME plumbing: noise
    if inl: lines.append('Inline helpers from public headers: ' + ', '.join(inl))
    if o.get('system'): lines.append('C library / system calls: ' + ', '.join(o['system']))
    if o.get('server_requests'): lines.append('wineserver requests: ' + ', '.join(r['request'] for r in o['server_requests']))
    if o.get('unix_calls'): lines.append('Unix-side calls: ' + ', '.join(u['code'] for u in o['unix_calls']))
    if o.get('indirect_calls'): lines.append('Indirect calls through function pointers: ' + ', '.join(i['expr'] for i in o['indirect_calls']))
    return '\n'.join('- ' + l for l in lines) if lines else none_text(ic)

@section('spec_section')
def spec(rec, ic, scn, ctx=None):
    """the requirement specification written by the architect stage (ctx['upstream'])"""
    if not ic.get('show_spec', False): return ''
    up = (ctx or {}).get('upstream')
    if not up: return none_text(ic)
    parsed = up.get('parsed')
    if isinstance(parsed, dict): return json.dumps(parsed, indent=2, ensure_ascii=False)
    return up.get('response', '').strip() or none_text(ic)

@section('file_includes_section')
def file_includes(rec, ic, scn, ctx=None):
    """#include lines of the file the function lives in (the compile context)"""
    if not ic.get('show_file_includes', False): return ''
    inc = rec['function'].get('file_includes') or []
    return '\n'.join(inc) if inc else none_text(ic)

@section('shared_helpers_section')
def shared_helpers(rec, ic, scn, ctx=None):
    """same-file helpers that stay in the file when the target is removed (not exclusive to it):
    the programmer may call them.  Signatures only, or with code (shared_helpers_show_code)."""
    if not ic.get('show_shared_helpers', False): return ''
    deps = [d for d in rec['same_file_dependencies'] if not d.get('exclusive_to_target')]
    mx = ic.get('shared_helpers_max_items', 0)
    if mx: deps = deps[:mx]
    if not deps: return none_text(ic)
    if ic.get('shared_helpers_show_code', False):
        return '```c\n' + '\n\n'.join(clip(d['code'], ic.get('shared_helpers_max_lines', 0)) for d in deps) + '\n```'
    return '```c\n' + '\n'.join(d['signature'].rstrip(';') + ';' for d in deps) + '\n```'

@section('docs_section')
def docs(rec, ic, scn, ctx=None):
    """Microsoft documentation pages attached to the record (scenarios 1.2 and 2.2): YAML front matter removed"""
    if not ic.get('show_docs', False): return ''
    import re
    pages = rec.get('docs') or []
    if not pages: return none_text(ic)
    out = []
    for d in pages[:ic.get('docs_max_pages', 2)]:
        text = re.sub(r'^---\n.*?\n---\n', '', d['text'], count=1, flags=re.S).strip()
        if ic.get('docs_strip_sections'):                       # e.g. ["-see-also", "-requirements"]
            for sec in ic['docs_strip_sections']:
                text = re.sub(r'\n## ' + re.escape(sec) + r'\b.*?(?=\n## |\Z)', '', text, flags=re.S)
        mx = ic.get('docs_max_chars', 0)
        if mx and len(text) > mx: text = text[:mx] + '\n[... documentation truncated ...]'
        head = f"Source: {d['url']}" if ic.get('docs_show_url', True) else f"Source: {d['repo']}"
        out.append(head + '\n\n' + text)
    return '\n\n---\n\n'.join(out)

# ---------------------------------------------------------------- assembly
def build_prompt(rec, scn, stage, ctx=None):
    st = scn.stage(stage); ic = st.get('inputs', {}); fn = rec['function']
    common = dict(project_name=st.get('project_name', 'a Windows compatibility layer'),
                  answer_language=st.get('answer_language', 'English'))
    fields = dict(dll=sampled_dll(rec), function=fn['export_name'], file=fn['file'], signature=fn['signature'],
                  start_line=fn['start_line'], end_line=fn['end_line'], **common)
    user_tpl = scn.template(st['user_template'])
    fields.update({name: f(rec, ic, scn, ctx) for name, f in SECTIONS.items() if '{{' + name + '}}' in user_tpl})   # only what the template uses
    messages = []
    if st.get('one_shot', False):
        messages += [{'role': 'user', 'content': fill(scn.template(st['example_user_template']), **common)},
                     {'role': 'assistant', 'content': fill(scn.template(st['example_assistant_template']), **common)}]
    messages.append({'role': 'user', 'content': fill(user_tpl, **fields)})
    return dict(id=rec['id'], dll=fields['dll'], function=fn['export_name'], c_name=fn['name'], stage=stage,
                from_model=(ctx or {}).get('from_model'),
                system=fill(scn.template(st['system_template']), **common), messages=messages)

def to_markdown(p):
    md = [f"# {p['id']} {p['dll']}!{p['function']} ({p['stage']})\n", '## system\n', p['system'], '']
    n = len(p['messages'])
    for i, m in enumerate(p['messages']):
        md += [f"## {m['role'] + ' (one-shot example)' if i < n - 1 else 'user (the task)'}\n", m['content'], '']
    return '\n'.join(md)
