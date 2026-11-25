"""hide.py - the agent scenarios' starting point: the source file with the answer taken out.

    new_source, info = hide(original_source, record)

  - the target function keeps its header comment and prototype; its body becomes a stub that says what to implement
  - helpers that only the target's call chain uses (same_file_dependencies[].exclusive_to_target) are removed
    (the same "hidden scope" as the programmer stages of scenarios 1.x)
  - everything else in the file stays as it is
info = {"stub_line": line of the stub, "removed": [helper names]}
"""
import re
from .csplice import _target_span, SpliceError

CALLCONV = {'WINAPI', 'CALLBACK', 'CDECL', '__cdecl', '__stdcall', '__fastcall', '__thiscall', 'APIENTRY', 'NTAPI',
            'DECLSPEC_HOTPATCH', 'DECLSPEC_NORETURN', 'static', 'inline', 'extern', 'DECL_SPEC'}

def zero_value(signature, name):
    """a compilable return statement for the stub, from the return type in the prototype"""
    ret = signature[:signature.find(name)]
    words = [w for w in re.findall(r'[\w*]+', ret) if w not in CALLCONV]
    t = ' '.join(words)
    if not t or t == 'void': return ''
    if '*' in t: return 'return NULL;'
    if 'HRESULT' in t: return 'return E_NOTIMPL;'
    if 'NTSTATUS' in t: return 'return STATUS_NOT_IMPLEMENTED;'
    if t in ('BOOL', 'BOOLEAN', 'BOOL16'): return 'return FALSE;'
    return 'return 0;'

def stub(rec):
    f = rec['function']; sig = f['signature'].strip()
    body = [f"    /* TODO(bench): implement {f['module']}!{f['export_name']} - see the task description. */"]
    z = zero_value(sig, f['name'])
    if z: body.append('    ' + z)
    return sig + '\n{\n' + '\n'.join(body) + '\n}'

def hide(src, rec):
    start, end = _target_span(src, rec)
    new = src[:start] + stub(rec) + src[end:]
    removed = []
    for d in rec.get('same_file_dependencies', []):
        if not d.get('exclusive_to_target') or not d.get('code'): continue
        code = d['code'].rstrip('\n')
        if new.count(code) != 1: raise SpliceError(f'helper {d["name"]} not found (or not unique) in {rec["function"]["file"]}')
        new = new.replace(code + '\n\n', '').replace(code, '')     # drop the definition and the blank line after it
        removed.append(d['name'])
    line = new[:new.find('TODO(bench)')].count('\n') + 1
    return new, dict(stub_line=line, removed=removed)
