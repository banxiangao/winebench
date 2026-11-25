# WineBench 全量表(Wine 11.19,commit 455e3509)

## 文件
| 文件 | 内容 |
|---|---|
| `winebench.json` | **主输出**:4,598 个样本,嵌套结构(见下)。2026-11-24 修正匹配后由 4,268 增至 4,598(只增不减,见"修订记录") |
| `winebench.xlsx` / `winebench.csv` | 同一批样本摊平成一行一个函数的表(xlsx 里超长函数体会截断,以 json/csv 为准) |
| `winebench_all.jsonl.gz` | 全集:全部 7,794 个候选函数,带各项标记和 `excluded_by`(未入选原因),可按自己的口径重新筛 |
| `winebench_untested.jsonl.gz` | 测试源码里没有任何直接调用的其余导出函数(`--dump-untested` 才生成),用于"按函数查" |
| `funnel.txt` | 漏斗统计、测试数分布、功能分类分布 |
| `msdocs_index.csv` | 微软官方文档函数索引(含 tech_root、头文件、DLL、最低系统版本、CRT 类别、一句话描述) |
| `build_doc_index.py` | 生成 msdocs_index.csv |
| `categorize.py` | 功能分类规则(头文件表、技术领域表、函数名兜底规则、教科书对照表) |
| `build_winebench.py` | 抽取脚本:Wine 源码 + relay 日志 + 文档索引 → 上面的全部输出 |
| `winebench_figures.py` | 画 `figures/` 下的 4 张图 |
| `analyze_wine500.py` / `wine500_figures.py` | 用新匹配方案核对之前的 500 个样本(wine500_doc),结果在 `wine500_recheck/` |
| `previous_v1/` | 修正前的 4,268 版 `winebench.json` 和 `funnel.txt`,留作对照 |

## 样本字段(winebench.json)
| 字段 | 含义 |
|---|---|
| `name` / `signature` | 函数名;函数定义的第一行(返回类型、调用约定、函数名、参数表) |
| `body` | 从 `{` 到 `}` 的完整实现 |
| `loc.total` / `loc.body` / `loc.code` | 行数:含签名 / 函数体 / 函数体内有效代码行(不含空行、纯注释、单独的花括号) |
| `location` | `dir`、`file`、`path`(以 Wine 源码根目录为起点)、`line_start`、`line_end` |
| `tests` | `n_tests`(直接调用它的测试函数数)、`n_tests_own` / `n_tests_other`(本模块 / 其他模块)、`n_dirs`、`dirs`(每个测试目录:是否本模块、测试数、文件名)、`list`(文件::测试函数) |
| `category` | `l1` 微软 Windows API index 的顶层类别;`l2` 该类别下的技术;`header` 头文件;`textbook` Silberschatz 六类系统调用对照;`basis` 分类依据 |
| `doc` | 文档地址、来源、一句话描述、最低 Windows 版本、文档写明的 DLL |
| `dll` / `shared_by_dlls` / `exports` | 实现所在 DLL;共用同一份源码的 DLL;所有解析到它的导出名(含转发) |
| `return_type` / `calling_convention` / `n_params` / `variadic` | 从签名解析 |
| `cyclomatic` | 圈复杂度近似值(1 + if/for/while/case/&&/||/?: 的个数) |
| `callees` / `api_callees` | 函数体里调用的函数;其中属于 Wine 导出 API 的 |
| `uses_wineserver` / `unix_side` | 是否直接向 wineserver 发请求;是否在 Unix 侧实现(ntdll/unix、win32u、libs) |
| `runtime_calls` | relay 那次全量运行中它被调用的总次数(含间接调用) |

## 重新生成
```bash
cd /media/banxiangao/D/wine_fuzz/winebench_full
python3 build_doc_index.py --work ./msdocs_repos --out msdocs_index.csv     # 可跳过,直接用现成的 msdocs_index.csv
python3 build_winebench.py --wine ../wine --docs msdocs_index.csv --relay ~/relay_results --out ./out --dump-untested
python3 winebench_figures.py --json ./out/winebench.json
# 核对之前的 500 个样本(--bench 指向含 winebench_all.jsonl[.gz] 和 winebench_untested.jsonl[.gz] 的目录)
python3 analyze_wine500.py --samples ../wine_agent/dataset/wine500_doc --bench ./out --wine ../wine --out ./wine500_recheck
python3 wine500_figures.py --recheck ./wine500_recheck/wine500_recheck.json --bench ./out/winebench.json
```
约 40 秒。只依赖 Python 3 标准库(xlsx 需要 openpyxl,没有会自动跳过)。

## 口径
- **候选**:.spec 导出函数中,被测试源码(`dlls/*/tests/*.c`、`programs/*/tests/*.c`)的函数体直接调用的。四种写法都算:`Func(...)`;经 GetProcAddress 取得的函数指针 `pFunc(...)` / `p_func(...)`(指针指向哪个导出,以 `GetProcAddress(h, "名字")` / `SET(p_x, "名字")` 里的字符串为准);作为"会调用其参数"的宏的实参 `CONVERT(VarI1FromI2, ...)`;作为测试辅助函数的函数指针实参。
- **有测试**:至少一个非 todo 的直接调用点,且 relay 日志确认该函数在调用点所在的测试单元里被调用过。relay 日志里不可能出现的导出(`-norelay`、`varargs` 类型、wine.inf 默认 `RelayExclude` 里的 8 个函数)只按源码判定(`relay` 字段记为 `norelay-flag`);其中 msvcrt 头文件里以 static inline 定义的名字(`sprintf`、`swprintf`、`_snprintf`)直接写名字调用时不算。`n_tests` = 直接调用它的测试函数个数(按 文件::函数 去重),`test_files` = 这些测试函数所在的文件。
- **n_tests_own / n_tests_other**:把 `n_tests` 拆成两部分。own = 测试文件所在模块目录(`dlls/<m>/tests`)就是导出该函数的 DLL 之一,即专门测这个 DLL 的测试;other = 别的模块的测试顺带调用。`memset`、`CloseHandle` 这类辅助调用的测试数几乎全是 other。`test_files_own` 是对应的文件列表。
- **todo**:调用点所在语句、或其后到下一个 API 调用之前(最多 8 行)的断言全部带 `todo_wine` 的,不算测试。
- **本模块有测试**:`n_tests_own ≥ 1`;否则剔除(脚本加 `--keep-no-own-test` 可保留)。原因分四种:`no_own_module_test`(本模块没有测它)、`own_test_unit_not_completed`(本模块有调用点,但所在单元没跑完)、`own_test_in_helper_module`(本模块的调用点在测试驱动里)、`own_test_not_executed`(跑了但没执行到)。
- **辅助模块**:带 `#pragma makedep testdll` 的测试源文件是单独编译的 DLL / 内核驱动(ntoskrnl 的 driver*.c 等)。用户态辅助 DLL 的调用按同目录各单元的 relay 记录确认;内核驱动跑在 winedevice 进程里,测试进程的日志看不到,只在驱动里被调用的函数记为 `helper_module_no_relay`,不入选。
- **有文档**:函数名在 msdocs_index.csv 里(不区分大小写)。
- **完全实现**:.spec 不是 stub;能定位到定义;函数体里没有 `FIXME`、没有 stub / semi-stub 标记。
- 转发(kernel32 → kernelbase、user32 → win32u 等,含 `-import X() Y` 写法和"本 DLL 没有定义、从导入的 DLL 原样再导出"的情况)记在真正实现它的函数上;同一份源码被多个 DLL 编译(msvcrt/msvcr90/ucrtbase)只出一行,见 `shared_by_dlls`。

- **16 位模块不在范围内**:`*.exe16` / `*.dll16` / `*.drv16` / `*.vxd` 目录整个跳过,`.spec` 里只取 x86_64 的导出条目;WineBench 里没有任何 16 位函数。`analyze_wine500.py` 核对旧样本时也默认先剔除 16 位模块的样本(清单写到 `wine500_recheck/wine500_win16_removed.csv`,原始样本文件不动;`--keep-win16` 可保留)。

## 已知局限
- "直接调用"是按测试源码判定、再用已有 relay 日志确认执行;没有做基于返回地址的运行时调用者判定。
- relay 那次运行有 22 个测试单元没跑完(kernel32:process/thread/sync/pipe、user32:input、ntdll:info 等),只在这些单元里被测的 370 个函数因此未入选(`relay_unit_not_completed`),另有 64 个因本模块测试在这些单元里而未入选(`own_test_unit_not_completed`)。重跑这 22 个单元即可补回。
- 491 个函数源码里有调用、单元也跑完了,但 relay 日志里没有(`not_executed_in_relay`):测试在那台机器上被 skip(没有声卡/MIDI/串口/蓝牙设备、区域设置不是 1252、权限不够等)。这是那次运行环境的结果,换环境会变。
- 165 个函数只在内核测试驱动里被调用(`helper_module_no_relay`),主要是 ntoskrnl.exe 的 Io*/Ob*/Ke*。
- varargs 等 relay 看不到的函数只能按源码算,无法确认真的执行过。
- 43 个函数定位不到定义(宏生成、汇编实现等)。
- 文档匹配只按函数名,不核对文档里写的 DLL。
- 通过"函数指针表 + 循环"调用、或宏里用 `##` 拼出函数名的调用识别不到。

## 修订记录
**2026-11-24(4,268 → 4,598,新增 330,无删除,已有样本的测试数只增不减)**——核对旧的 500 样本时发现新方案自己的 6 处漏判,已修:
1. `varargs` 导出(printf 族、`_open`、wsprintf、DbgPrint 等)winebuild 不生成 relay 入口,日志里永远没有,之前被误判成"没执行";默认 `RelayExclude` 里的 TlsSetValue、RtlLeaveCriticalSection 等同理。
2. 经宏参数发起的调用没识别(oleaut32 的 `CONVERT(VarXxFromYy, ...)` 一类,新增的 330 个里占 198 个)。
3. `p_name` 形式的函数指针没识别(msvcrt 测试的主要写法)。
4. `.spec` 里 `-import X() Y` 写法没按内部名 Y 解析(user32 → win32u 的一批);"本 DLL 没定义、从导入 DLL 再导出"只处理了改名的情况(ole32.WriteClassStg → coml2、ntoskrnl.exe 的 Rtl* → ntdll)。
5. 函数定义前紧跟独占一行的宏调用(`DEFINE_THISCALL_WRAPPER(f, 8)`、`IMPL_WIREM_HANDLE(HACCEL)`)时,函数名被解析成宏名。
6. 测试驱动源文件里的调用被记成"单元没跑完",现在单独标为 `helper_module_no_relay`。
