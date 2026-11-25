# -*- coding: utf-8 -*-
"""
categorize.py —— WineBench 的函数功能分类。

分类体系(三层 + 一个教科书对照):
  l1        一级类别:微软 "Windows API index" 的 12 个顶层类别
            https://learn.microsoft.com/windows/win32/apiindex/windows-api-list
            (User interface / Windows environment (Shell) / User input and messaging / Data access and storage /
             Diagnostics / Graphics and multimedia / Devices / System services / Security and identity /
             Application installation and servicing / System admin and management / Networking and internet)
            外加一类 "C runtime library"(msvcrt/ucrtbase 不属于 Windows API index,用 CRT 文档自己的分类)
  l2        二级类别:API index 里该顶层类别下的"技术"名(Files and I/O、Memory management、Windows and messages、GDI …);
            CRT 函数用微软 "Universal C runtime routines by category" 的类别名
  header    三级:该函数在微软文档里所属的头文件(fileapi.h、synchapi.h …),原样记录,不做归并
  textbook  教科书对照:Silberschatz《Operating System Concepts》2.3 节的六类系统调用
            (Process control / File management / Device management / Information maintenance / Communications / Protection);
            UI、图形、运行时库等不属于"操作系统内核服务"的,记为 "N/A (not an OS kernel service)"
  basis     这一条分类的依据:header(头文件)> tech_root(文档的技术领域标签)> name_rule(函数名规则)> crt_category > default
            —— 前两种直接来自微软文档的元数据;name_rule 是对 winbase.h / winnt.h / wdm.h 这类"大杂烩"头文件的兜底,客观性弱一些

判定顺序:header 命中 HEADER_MAP → 用它;否则 tech_root 命中 TECH_MAP → 用它;
          否则(或 TECH_MAP 标记为需要细分的 base / winprog / backup / kernel / ifsk)按 NAME_RULES 用函数名细分。
"""
import re

UI, SHELL, INPUT, DATA, DIAG, GFX, DEV, SYS, SEC, INST, ADMIN, NET, CRT = (
    "User interface", "Windows environment (Shell)", "User input and messaging", "Data access and storage", "Diagnostics",
    "Graphics and multimedia", "Devices", "System services", "Security and identity", "Application installation and servicing",
    "System admin and management", "Networking and internet", "C runtime library")

# ───────── 头文件 → (l1, l2)。只收功能含义明确的头文件;winbase / winnt / winuser / wingdi / winternl / wdm 等不在这里 ─────────
HEADER_MAP = {}
def _h(l1, l2, headers):
    for x in headers.split(): HEADER_MAP[x] = (l1, l2)
_h(SYS, "Processes and threads", "processthreadsapi jobapi jobapi2 processtopologyapi fibersapi threadpoolapiset threadpoollegacyapiset processenv wow64apiset enclaveapi")
_h(SYS, "Synchronization", "synchapi interlockedapi")
_h(SYS, "Memory management", "memoryapi heapapi")
_h(SYS, "Dynamic-link libraries", "libloaderapi")
_h(SYS, "Interprocess communications", "namedpipeapi")
_h(SYS, "System information", "sysinfoapi systemtopologyapi")
_h(SYS, "Time", "timezoneapi profileapi realtimeapiset")
_h(SYS, "Handles and objects", "handleapi")
_h(SYS, "Registry", "winreg")
_h(SYS, "Services", "winsvc")
_h(SYS, "Remote Desktop Services", "wtsapi32")
_h(SYS, "Power management", "powrprof powerbase powersetting")
_h(SYS, "COM", "combaseapi objbase ole2 oleidl objidl olectl ocidl urlmon")
_h(SYS, "COM (Automation)", "oleauto oaidl")
_h(SYS, "Windows Runtime (WinRT)", "winstring roapi inspectable roerrorapi rometadataresolution corewindow")
_h(DATA, "Files and I/O", "fileapi lzexpand ioapiset")
_h(SYS, "Compression (Cabinet)", "fci fdi")
_h(DATA, "Structured Storage", "coml2api propidl")
_h(DATA, "Data exchange (DDE, clipboard)", "ddeml dde")
_h(DIAG, "Debugging and error handling", "dbghelp imagehlp debugapi errhandlingapi minidumpapiset")
_h(DIAG, "Process Status (PSAPI)", "psapi")
_h(DIAG, "Performance counters", "pdh perflib")
_h(DIAG, "Event tracing and logging", "evntprov evntrace tdh winevt")
_h(DIAG, "Windows Error Reporting", "werapi errorrep")
_h(DEV, "Tool Help", "tlhelp32")
_h(UI, "Common controls", "commctrl uxtheme dpa_dsa prsht commoncontrols")
_h(UI, "Common dialog boxes", "commdlg")
_h(UI, "Internationalization (NLS, IME, Uniscribe)", "winnls imm usp10 stringapiset datetimeapi")
_h(UI, "Accessibility", "oleacc uiautomationcoreapi uiautomationcore")
_h(UI, "Desktop Window Manager", "dwmapi")
_h(INPUT, "User interaction", "interactioncontext")
_h(SHELL, "Windows Shell", "shlwapi shlobj_core shellapi pathcch shobjidl_core userenv shlobj")
_h(SHELL, "Windows Property System", "propvarutil propsys")
_h(SHELL, "Consoles", "wincon consoleapi consoleapi2 consoleapi3")
_h(GFX, "Windows Color System", "icm")
_h(GFX, "Windows Multimedia", "mmeapi vfw msacm mmiscapi joystickapi timeapi mmsystem playsoundapi mciapi")
_h(GFX, "Microsoft Media Foundation", "mfapi mfidl mfreadwrite mftransform mfd3d12 mfplay dxva2api rtworkq evr mfobjects")
_h(GFX, "Direct3D", "d3d9 d3d10 d3d10_1 d3d10misc d3d10effect d3d10shader d3d11 d3d12 d3dcompiler dxgi dxgi1_3 dxcore d3dkmthk")
_h(GFX, "Direct2D and DirectWrite", "d2d1 d2d1_1 d2d1_2 d2d1helper dwrite")
_h(GFX, "DirectDraw", "ddraw")
_h(GFX, "DirectShow", "dmoreg dmort")
_h(GFX, "XInput", "xinput")
_h(GFX, "Windows Imaging Component", "wincodec")
_h(GFX, "Windows Media Format", "wmsdkidl wmsdkvalidate")
_h(GFX, "GDI+", "gdiplusflat gdiplusinit")
_h(DEV, "Device management and installation", "cfgmgr32 devquery newdev")
_h(DEV, "Human Interface Devices", "hidpi hidsdi hidport")
_h(DEV, "Printing", "winspool winsplp compstui prntvpt")
_h(DEV, "Windows Image Acquisition", "sti wia_xp")
_h(DEV, "Web Services on Devices", "wsdutil wsdbase wsddisco wsdxml")
_h(SEC, "Cryptography", "wincrypt bcrypt ncrypt mscat wintrust softpub dpapi")
_h(SEC, "Authentication", "sspi ntsecapi wincred schannel secext")
_h(SEC, "Authorization", "securitybaseapi aclapi sddl authz winsafer")
_h(SEC, "Directory services", "winldap winber adshlp dsrole dsparse dsgetdc ntdsapi")
_h(INST, "Windows Installer", "msi msiquery")
_h(INST, "Side-by-side assemblies", "winsxs")
_h(NET, "Windows Sockets", "winsock2 winsock ws2tcpip ws2spi mswsock")
_h(NET, "WinINet", "wininet winineti")
_h(NET, "WinHTTP", "winhttp")
_h(NET, "HTTP Server", "http")
_h(NET, "IP Helper", "iphlpapi netioapi ip2string icmpapi")
_h(NET, "Remote Procedure Call", "rpcdce rpcndr rpcproxy midles rpcasync rpcdcep")
_h(NET, "Domain Name System", "windns")
_h(NET, "Network management", "lmaccess lmapibuf lmwksta lmjoin lmserver lmshare")
_h(NET, "SNMP", "snmp winsnmp")
_h(NET, "Windows Web Services", "webservices")
_h(NET, "Wireless networking", "wlanapi bluetoothapis bluetoothleapis")
_h(NET, "Windows Networking (WNet)", "winnetwk")
_h(NET, "WebDAV", "davclnt")
_h(NET, "Routing and Remote Access", "ras")

# ───────── tech.root(小写)→ (l1, l2);l2 为 None 表示这个标签太粗,需要用函数名细分 ─────────
TECH_MAP = {
    "fs": (DATA, "Files and I/O"), "fileio": (DATA, "Files and I/O"), "stg": (DATA, "Structured Storage"), "dataxchg": (DATA, "Data exchange (DDE, clipboard)"),
    "vstor": (DATA, "Files and I/O"),
    "base": (SYS, None), "winprog": (SYS, None), "backup": (SYS, None), "kernel": (SYS, None), "ifsk": (SYS, None), "": (SYS, None),
    "processthreadsapi": (SYS, "Processes and threads"), "procthread": (SYS, "Processes and threads"), "ipc": (SYS, "Interprocess communications"),
    "services": (SYS, "Services"), "termserv": (SYS, "Remote Desktop Services"), "com": (SYS, "COM"), "automat": (SYS, "COM (Automation)"),
    "winrt": (SYS, "Windows Runtime (WinRT)"), "winstation": (SYS, "Window stations and desktops"), "sysinfo": (SYS, "System information"),
    "debug": (DIAG, "Debugging and error handling"), "psapi": (DIAG, "Process Status (PSAPI)"), "perf": (DIAG, "Performance counters"),
    "perfctrs": (DIAG, "Performance counters"), "etw": (DIAG, "Event tracing and logging"), "wes": (DIAG, "Event tracing and logging"),
    "wer": (DIAG, "Windows Error Reporting"), "devtest": (DIAG, "Debugging and error handling"), "debugger": (DIAG, "Debugging and error handling"),
    "toolhelp": (DEV, "Tool Help"),
    "gdi": (GFX, "GDI"), "gdiplus": (GFX, "GDI+"), "wcs": (GFX, "Windows Color System"), "multimedia": (GFX, "Windows Multimedia"),
    "mf": (GFX, "Microsoft Media Foundation"), "medfound": (GFX, "Microsoft Media Foundation"), "mfarchive": (GFX, "Microsoft Media Foundation"),
    "direct3d9": (GFX, "Direct3D"), "direct3d10": (GFX, "Direct3D"), "direct3d11": (GFX, "Direct3D"), "direct3d12": (GFX, "Direct3D"),
    "direct3dhlsl": (GFX, "Direct3D"), "direct3ddxgi": (GFX, "Direct3D"), "dxcore": (GFX, "Direct3D"), "display": (GFX, "Direct3D"),
    "direct2d": (GFX, "Direct2D and DirectWrite"), "directwrite": (GFX, "Direct2D and DirectWrite"), "directdraw": (GFX, "DirectDraw"),
    "dshow": (GFX, "DirectShow"), "opengl": (GFX, "OpenGL"), "wic": (GFX, "Windows Imaging Component"), "wmformat": (GFX, "Windows Media Format"),
    "xinput": (GFX, "XInput"), "coreaudio": (GFX, "Core Audio"), "xps": (DEV, "Printing"),
    "winmsg": (INPUT, "Windows and messages"), "inputdev": (INPUT, "Keyboard and mouse input"), "inputmsg": (INPUT, "User interaction"),
    "input_intcontext": (INPUT, "User interaction"),
    "menurc": (UI, "Resources (menus, icons, cursors, strings)"), "controls": (UI, "Common controls"), "dlgbox": (UI, "Dialog boxes"),
    "intl": (UI, "Internationalization (NLS, IME, Uniscribe)"), "winauto": (UI, "Accessibility"), "hidpi": (UI, "High DPI"), "dwm": (UI, "Desktop Window Manager"),
    "shell": (SHELL, "Windows Shell"), "properties": (SHELL, "Windows Property System"),
    "devinst": (DEV, "Device management and installation"), "devio": (DEV, "Device management and installation"), "hid": (DEV, "Human Interface Devices"),
    "print": (DEV, "Printing"), "printdocs": (DEV, "Printing"), "image": (DEV, "Windows Image Acquisition"), "wia": (DEV, "Windows Image Acquisition"),
    "ncd": (DEV, "Web Services on Devices"),
    "security": (SEC, "Authorization"), "seccrypto": (SEC, "Cryptography"), "secauthn": (SEC, "Authentication"), "secmgmt": (SEC, "Authentication"),
    "ldap": (SEC, "Directory services"), "ad": (SEC, "Directory services"), "adsi": (SEC, "Directory services"),
    "setup": (INST, "Setup API"), "appxpkg": (INST, "App packaging"),
    "winsock": (NET, "Windows Sockets"), "wininet": (NET, "WinINet"), "http": (NET, "WinHTTP"), "iphlp": (NET, "IP Helper"), "rpc": (NET, "Remote Procedure Call"),
    "dns": (NET, "Domain Name System"), "netmgmt": (NET, "Network management"), "snmp": (NET, "SNMP"), "wsw": (NET, "Windows Web Services"),
    "nwifi": (NET, "Wireless networking"), "bluetooth": (NET, "Wireless networking"), "bltooth": (NET, "Wireless networking"), "wnet": (NET, "Windows Networking (WNet)"),
    "webdav": (NET, "WebDAV"), "rras": (NET, "Routing and Remote Access"), "dhcp": (NET, "DHCP"), "qos": (NET, "Quality of Service"),
    "netvista": (NET, "Network drivers"), "tapi3": (NET, "Telephony (TAPI)"), "mapi": (NET, "Windows Messaging (MAPI)"),
    "devnotes": (SYS, None), "shell_conceptual": (SHELL, "Windows Shell"),
}

# ───────── 函数名规则(对 base / winprog / kernel 等粗标签做细分;从上到下第一个命中的生效)─────────
NAME_RULES = [
    (r"^DeviceIoControl$", DEV, "Device management and installation"),
    (r"FileMapping|MapViewOfFile", SYS, "Memory management"),
    (r"FileTime|SystemTime|DateTime|LocalTime", SYS, "Time"),
    (r"Power", SYS, "Power management"),
    (r"DelayLoad", SYS, "Dynamic-link libraries"),
    (r"IoCompletion|^_l(open|creat|read|write|close|lseek)$|^_h(read|write)$", DATA, "Files and I/O"),
    (r"RegisterWait", SYS, "Synchronization"),
    (r"SelfRelative|AbsoluteSD", SEC, "Authorization"),
    (r"specific_handler|IsBad\w+Ptr", DIAG, "Debugging and error handling"),
    (r"EventLog|EventSource|ReportEvent", DIAG, "Event tracing and logging"),
    (r"Exception|Unwind|Debug|^Dbg|RaiseStatus|CaptureContext|StackBackTrace|ErrorMode|^FatalAppExit|IsBadReadPtr|IsBadWritePtr", DIAG, "Debugging and error handling"),
    (r"Sid\b|Sid[A-Z]|Acl|Ace\b|Token|Privilege|SecurityDescriptor|Luid|AccessCheck|Audit|Impersonat|SecurityObject", SEC, "Authorization"),
    (r"^Reg[A-Z]|ValueKey|^(Nt|Zw)\w*Key\b|Key[A-Z]\w*$|RegistryValue|RegistryKey", SYS, "Registry"),
    (r"PrivateProfile|^GetProfile|^WriteProfile", SYS, "Registry"),
    (r"Pipe|Mailslot|Alpc|^(Nt|Zw)\w*Port\b", SYS, "Interprocess communications"),
    (r"Atom", DATA, "Data exchange (DDE, clipboard)"),
    (r"^(Set|Get|Clear|Build|Transmit|Purge|Setup|Escape|Wait)Comm|CommState|CommTimeouts|CommConfig|CommMask|Tape", DEV, "Communications resources"),
    (r"File|Directory|Volume|Disk|Drive|PathName|DosDevice|Oplock|^LZ|FullPathName|TempPath|EaFile", DATA, "Files and I/O"),
    (r"Heap|^Global(?!Atom|Memory)|^Local(?!e|Time)|Virtual|MapView|Section|Memory|MemMove|^Rtl(Copy|Move|Zero|Fill|Compare)Memory|WorkingSet", SYS, "Memory management"),
    (r"Mutex|Mutant|Semaphore|^(Create|Open|Set|Reset|Pulse)Event|^(Nt|Zw|Ke)\w*Event\b|Wait(For|OnAddress)|CriticalSection|SRWLock|ConditionVariable|Interlocked|"
     r"WaitableTimer|InitOnce|RunOnce|Barrier|KeyedEvent|SpinLock|^(Nt|Zw|Ke)\w*Timer|Resource(Exclusive|Shared)Lite|FastMutex|PushLock", SYS, "Synchronization"),
    (r"Thread|Process|Fiber|JobObject|^Tls|^Fls|Environment|QueueUserAPC|Affinity|PriorityClass|WorkItem|Threadpool|^Tp[A-Z]|CommandLine|^WinExec$|Apc\b", SYS, "Processes and threads"),
    (r"Module|Library|ProcAddress|^Ldr|DllDirectory|ActCtx", SYS, "Dynamic-link libraries"),
    (r"Resource", UI, "Resources (menus, icons, cursors, strings)"),
    (r"Time|TickCount|PerformanceCounter|PerformanceFrequency", SYS, "Time"),
    (r"Handle|Object\b|ObjectType|^(Nt|Zw)Close$", SYS, "Handles and objects"),
    (r"Version|SystemInfo|ComputerName|UserName|Firmware|ProductInfo|Processor|Numa|SystemDirectory|WindowsDirectory|SystemInformation|Wow64|NativeMachine|ProductType", SYS, "System information"),
    (r"String|Unicode|Ansi|Oem|Utf8|MultiByte|Upcase|Downcase|^lstr|Char\b|Chars\b|Integer|Bit[sm]|Guid|Random|Uniform|Crc|Hash|Compress|Sort|AvlTable|GenericTable|BitMap|Runs?(Clear|Set)|SignificantBit|Splay|Successor|Predecessor|^RtlDelete", SYS, "Run-time library (strings, bitmaps, utilities)"),
    (r"^(Io|Po|Ob|Ps|Mm|Ke|Ex|Se|Cm|Fs|Flt|Hal|Wmi|Wsk)[A-Z]", SYS, "Kernel-mode driver support routines"),
]
NAME_RULES = [(re.compile(p), a, b) for p, a, b in NAME_RULES]

# ───────── 二级类别 → Silberschatz 的六类系统调用 ─────────
PC, FM, DM, IM, CM, PR, NA = ("Process control", "File management", "Device management", "Information maintenance", "Communications", "Protection",
                              "N/A (not an OS kernel service)")
TEXTBOOK = {
    "Processes and threads": PC, "Synchronization": PC, "Memory management": PC, "Dynamic-link libraries": PC, "Services": PC,
    "Debugging and error handling": PC, "Kernel-mode driver support routines": PC,
    "Files and I/O": FM, "Structured Storage": FM,
    "Device management and installation": DM, "Communications resources": DM, "Human Interface Devices": DM, "Printing": DM,
    "Windows Image Acquisition": DM, "Power management": DM,
    "System information": IM, "Time": IM, "Registry": IM, "Handles and objects": IM, "Process Status (PSAPI)": IM, "Tool Help": IM,
    "Performance counters": IM, "Event tracing and logging": IM, "Windows Error Reporting": IM,
    "Interprocess communications": CM, "Data exchange (DDE, clipboard)": CM, "Windows Sockets": CM, "WinINet": CM, "WinHTTP": CM, "HTTP Server": CM,
    "IP Helper": CM, "Remote Procedure Call": CM, "Domain Name System": CM, "Network management": CM, "SNMP": CM, "Windows Web Services": CM,
    "Wireless networking": CM, "Windows Networking (WNet)": CM, "WebDAV": CM, "Routing and Remote Access": CM, "DHCP": CM, "Quality of Service": CM,
    "Network drivers": CM, "Telephony (TAPI)": CM, "Windows Messaging (MAPI)": CM, "Web Services on Devices": CM, "Remote Desktop Services": CM,
    "Authorization": PR, "Cryptography": PR, "Authentication": PR, "Directory services": PR,
}
CRT_TEXTBOOK = {"File handling": FM, "Directory control": FM, "Input and output": FM, "Process and environment control": PC, "Memory allocation": PC,
                "Exception handling routines": PC, "Time management": IM, "System calls": IM, "Error handling": IM}


def categorize(name, doc):
    """name: 函数名;doc: msdocs_index.csv 的一行(source / header / tech_root / crt_category)。返回 dict(l1, l2, header, textbook, basis)。"""
    src = (doc or {}).get("source", ""); header = (doc or {}).get("header", "") or ""; tech = ((doc or {}).get("tech_root", "") or "").lower()
    hdr = (header + ".h") if header and src in ("win32", "ddi", "win32-gdiplus-flat") else ""
    if src == "crt":
        c = doc.get("crt_category") or "Other CRT routines"
        return dict(l1=CRT, l2=c, header=hdr, textbook=CRT_TEXTBOOK.get(c, NA), basis="crt_category" if doc.get("crt_category") else "default")
    l1 = l2 = None; basis = ""
    if name == "DeviceIoControl": l1, l2, basis = DEV, "Device management and installation", "name_rule"
    elif header in HEADER_MAP: (l1, l2), basis = HEADER_MAP[header], "header"
    elif tech in TECH_MAP:   (l1, l2), basis = TECH_MAP[tech], "tech_root"
    if l2 is None:
        base = re.sub(r"(ExA|ExW|A|W)$", "", name) if re.search(r"[a-z](ExA|ExW|A|W)$", name) else name
        for rx, a, b in NAME_RULES:
            if rx.search(name) or rx.search(base): l1, l2, basis = a, b, "name_rule"; break
    if l2 is None:
        l1, l2, basis = (l1 or SYS), "Other system services", "default"
    return dict(l1=l1, l2=l2, header=hdr, textbook=TEXTBOOK.get(l2, NA), basis=basis)
