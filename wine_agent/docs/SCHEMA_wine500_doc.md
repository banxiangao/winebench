# 数据集 wine500_doc：字段说明

每个函数一个 JSON 文件，文件名 `<id>_<模块>_<函数名>.json`（如 `0001_kernelbase_PathCchAddExtension.json`），共 500 个，id 从 0001 到 0500 连续。所有文件的字段结构完全相同（没有的内容是空列表 / null，不缺字段）。所有源码位置都是相对 Wine 11.18 源码根目录的路径，行号从 1 开始，`start_line`–`end_line` 是闭区间。

500 个函数都至少有一页微软官方文档。

目录里还有：

| 文件              | 内容                                                                             |
| --------------- | ------------------------------------------------------------------------------ |
| `manifest.json` | 清单：`count` 和每条记录的 id、文件名、模块、导出名、C 函数名、源码位置、`side`、是否做过依赖分析、文档页数                |
| `docs/`         | 每条记录的微软文档页副本（Markdown），文件名 `<id>_<仓库>_<页名>.md`，共 518 个（18 个函数有两页）              |
| `excluded.txt`  | 被人工排除、不再抽入的函数（`模块!导出名`，目前 1 个：`dbghelp!MiniDumpWriteDump`，libclang 无法解析它所在的文件） |
| `pipeline.log`  | 抽样时每个候选被拒绝的原因统计                                                                |

---

## 顶层

| 字段                        | 类型     | 含义                                          |
| ------------------------- | ------ | ------------------------------------------- |
| `id`                      | string | 四位编号 `"0001"`…`"0500"`，也是提示词 / 回复 / 评测文件的名字 |
| `function`                | object | 目标函数本身（见下）                                  |
| `native_tests`            | object | Wine 自带的、引用了该导出名的测试文件（见下）                   |
| `same_name_in_other_dlls` | list   | 其他 DLL 里的同名独立实现（见下）                         |
| `docs`                    | list   | 微软官方文档页（见下）                                 |
| `same_file_dependencies`  | list   | 同一源文件里被目标函数（直接或间接）调用的函数（见下）                 |
| `same_file_definitions`   | object | 目标函数用到的、定义在同一源文件里的私有类型 / 全局变量 / 宏（见下）       |
| `other_dependencies`      | object | 其他文件 / 其他模块 / 系统库的依赖，只记位置不展开（见下）            |
| `meta`                    | object | 生成过程的元信息（见下）                                |

---

## `function` — 目标函数

| 字段                        | 类型             | 含义                                                                                                                                | 例                                                                                                        |
| ------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `name`                    | string         | C 源码里的函数名。可能和导出名不同：user32 导出的 `DrawMenuBar` 实现是 win32u 里的 `NtUserDrawMenuBar`；16 位函数带 `16` 后缀                                     | `"NtUserDrawMenuBar"`                                                                                    |
| `export_name`             | string         | `.spec` 文件里的导出名，即 Windows 程序调用时用的名字；也是查微软文档用的名字                                                                                   | `"DrawMenuBar"`                                                                                          |
| `module`                  | string         | **实现**所在的模块（`dlls/<module>/`）。kernel32 转发到 kernelbase 的函数，这里是 `kernelbase`                                                        | `"kernelbase"`                                                                                           |
| `source_module`           | string         | 源码所在的目录。多数和 `module` 相同；`PARENTSRC` 共用源码时不同，如 msvcr100 的函数源码在 `dlls/msvcrt/`                                                      | `"msvcrt"`                                                                                               |
| `exported_by`             | list[string]   | 所有导出这份实现的模块（同一份代码被多个 DLL 导出时列出全部，如 msvcr100/msvcr110/…/ucrtbase）                                                                  | `["kernel32","kernelbase"]`                                                                              |
| `side`                    | string         | `"PE"`：Windows 侧代码，用 mingw 交叉编译进 `.dll`（477 个）；`"unix"`：ntdll / win32u 的 Unix 侧实现（`#pragma makedep unix`），用宿主 gcc 编译进 `.so`（23 个） | `"PE"`                                                                                                   |
| `arch`                    | string         | 依赖分析时 libclang 使用的目标架构：`x86_64`（默认）、`i686`（只在 32 位编译的代码，如 16 位模块）、`host`（Unix 侧，用宿主 SDK）                                          | `"x86_64"`                                                                                               |
| `file`                    | string         | 源文件路径                                                                                                                             | `"dlls/kernelbase/path.c"`                                                                               |
| `start_line` / `end_line` | int            | 函数定义在文件里的起止行（从返回类型那一行到右大括号）                                                                                                       | `516` / `557`                                                                                            |
| `body_lines`              | int            | 函数体行数（大括号之间，不含空行）；                                                                                                                | `39`                                                                                                     |
| `signature`               | string         | 函数原型，从源码截取（到参数表右括号为止，不含分号）                                                                                                        | `"HRESULT WINAPI PathCchAddExtension(WCHAR *path, SIZE_T size, const WCHAR *extension)"`                 |
| `header_comment`          | string \| null | 函数上方的注释块（`/*****  Name  (MODULE.@) ... */`），没有则 null（102 个）。                                                                      |                                                                                                          |
| `code`                    | string         | 函数定义全文（`start_line`–`end_line` 的原文），评测时按它在源文件里定位并替换；也是"是否与原实现一致"指标的参照                                                             |                                                                                                          |
| `has_fixme`               | bool           | 函数体里是否出现 `FIXME(`：true 表示 Wine 的实现本身不完整（某些分支 / 参数没处理），82 个。全桩（`FIXME("stub")`）的函数在抽样时已排除                                          | `false`                                                                                                  |
| `file_includes`           | list[string]   | 源文件里全部 `#include` 行，按出现顺序；程序员提示词里的"编译上下文"                                                                                         | `["#include <stdarg.h>", …]`                                                                             |
| `resolution`              | list[string]   | 从导出到实现的定位链，每步一行：`模块!导出名 [调用约定 标志] -> 下一步`。单元素表示直接实现；转发 / `-import` / 内部符号名 / 宏生成 / PARENTSRC 都会多一步                                | `["kernel32!OpenMutexW [stdcall -import] -> import from kernelbase", "kernelbase!OpenMutexW [stdcall]"]` |

---

## `native_tests` — Wine 自带测试

| 字段      | 类型           | 含义                                                                                                                                                                                                               |
| ------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `files` | list[string] | `dlls/<导出模块>/tests/*.c` 中出现了该导出名的测试文件。抽样时要求至少一个。评测时对每个文件跑 `make dlls/<模块>/tests/<文件>.ok`。注意测试模块是**导出**模块（kernel32 的函数即使实现在 kernelbase，测试也在 `dlls/kernel32/tests/`）；一个函数最多对应 45 个测试文件（如 `GetLastError` 这类到处都用的函数） |

---

## `same_name_in_other_dlls` — 其他 DLL 里的同名实现

Wine 里同一个函数名有时在多个 DLL 里各有一份独立代码（16 位 / 32 位版本、msvcrt 和 ntdll 各自的 C 运行时函数等）。共用同一份源码的（PARENTSRC、转发）不算，已去重。500 条里有 79 条记录各有 1 个这样的条目；空列表表示没有。

| 字段                                 | 类型           | 含义                                                                                              |
| ---------------------------------- | ------------ | ----------------------------------------------------------------------------------------------- |
| `module`                           | string       | 同名实现所在的模块                                                                                       |
| `source_module`                    | string       | 其源码目录                                                                                           |
| `exported_by`                      | list[string] | 导出这份同名实现的模块                                                                                     |
| `file` / `start_line` / `end_line` |              | 位置                                                                                              |
| `signature` / `code`               | string       | 原型和全文                                                                                           |
| `resolution`                       | list[string] | 同上的定位链                                                                                          |
| `macro_generated`                  | bool         | 该实现是否由宏展开生成（没有常规函数体）                                                                            |
| `win16`                            | bool         | 是否为 16 位模块（`*.exe16` / `*.dll16`）。16 位版本语义常有差异；场景 1.1 / 1.3 的 `same_name_exclude_win16` 默认把它们排除 |

---

## `docs` — 微软官方文档

来自 MicrosoftDocs 的 GitHub 仓库（见 `dataset/docs_index.tsv`），每条 1–2 页，sdk-api 优先。

| 字段                | 类型     | 含义                                                                                                                 | 例                                                                 |
| ----------------- | ------ | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `repo`            | string | 来源仓库：`sdk-api`（Win32 API，432 页）、`cpp-docs`（C 运行时，44）、`win32`（D3DX，24）、`windows-driver-docs-ddi`（Nt*/Rtl* 等内核接口，18） | `"sdk-api"`                                                       |
| `header`          | string | 所属头文件（sdk-api / ddi）；cpp-docs 为 `"crt"`；win32 为 `direct3d9` 等                                                      | `"pathcch"`                                                       |
| `path`            | string | 页面在仓库里的路径                                                                                                          | `"sdk-api-src/content/pathcch/nf-pathcch-pathcchaddextension.md"` |
| `url`             | string | learn.microsoft.com 上的网址                                                                                           |                                                                   |
| `documented_name` | string | 文档里的函数名（小写；cpp-docs 一页常覆盖多个函数，如 `abs`/`_abs64`）                                                                    | `"pathcchaddextension"`                                           |
| `file`            | string | 本地副本，相对数据集目录                                                                                                       | `"docs/0001_sdk-api_nf-pathcch-pathcchaddextension.md"`           |
| `text`            | string | 页面原文（Markdown，含开头的 YAML front matter）。提示词生成时会去掉 YAML 头，并按配置去掉 See-also 等节                                          |                                                                   |

---

## `same_file_dependencies` — 同文件里被调用的函数

目标函数调用链（直接和间接）里、定义在**同一源文件**中的开发者函数，按调用距离排序（直接被调用的在前）。标准库 / 其他文件的不在这里（见 `other_dependencies`）。

| 字段                                 | 类型           | 含义                                                                                                                                                                  |
| ---------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`                             | string       | 函数名                                                                                                                                                                 |
| `file` / `start_line` / `end_line` |              | 位置（文件和目标函数相同）                                                                                                                                                       |
| `static`                           | bool         | 是否 `static`（文件私有）                                                                                                                                                   |
| `signature` / `code`               | string       | 原型和全文                                                                                                                                                               |
| `called_from`                      | list[string] | 调用链内调用它的函数名（目标函数或其他辅助函数）                                                                                                                                            |
| `exclusive_to_target`              | bool         | true：文件里只有目标函数的调用链用到它。场景 1.1 / 1.2 把目标函数"隐去"时，这些辅助函数一起隐去，程序员要自己写；false：别处也在用，保留在文件里，程序员可以调用（提示词里的 "Helper functions already defined in the file that you may call"） |
| `used_outside`                     | list[string] | 当 `exclusive_to_target` 为 false 时，文件里其他使用处的位置（`文件:行`）；exclusive 的条目没有此字段                                                                                            |

---

## `same_file_definitions` — 同文件里用到的私有定义

目标函数（及其同文件辅助函数）用到的、定义在同一源文件中的东西。程序员提示词里的 "Private types, globals and macros already defined in the file"。

| 字段        | 类型   | 含义                                                                                                                                                                            |
| --------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `types`   | list | 结构 / 联合 / 枚举 / typedef。每项：`name`、`kind`（`struct_decl` / `union_decl` / `enum_decl` / `typedef_decl`）、`start_line`、`end_line`、`code`                                           |
| `globals` | list | 全局变量。每项：`name`、`type`（C 类型字符串）、`static`、`start_line`、`end_line`、`code`。`WINE_DEFAULT_DEBUG_CHANNEL(x);` 展开后是一个全局变量 `__wine_dbch___default`，用了 TRACE/FIXME 等调试宏的函数（374 条）都会带上它 |
| `macros`  | list | 宏。每项：`name`、`start_line`、`end_line`、`code`                                                                                                                                    |

---

## `other_dependencies` — 文件之外的依赖

只记名字和位置，不展开代码，也不隐去（它们是模型可以调用的接口）。

| 字段                        | 类型           | 含义                                                                                 | 例                                                                            |
| ------------------------- | ------------ | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `same_module_other_files` | list         | 同模块其他文件里的函数：`name`、`file`、`start_line`                                             | `{"name":"copy_remote_record","file":"dlls/msi/record.c","start_line":1052}` |
| `same_module_exports`     | list         | 同模块导出的其他 API：`name`、`impl`（实现位置列表 `文件:行`）                                          | `{"name":"PathCchFindExtension","impl":["dlls/kernelbase/path.c:680"]}`      |
| `other_dll_exports`       | list         | 其他 DLL 的导出函数：`name`、`module`、`impl`                                                | `{"name":"wcsnlen","module":"ntdll","impl":[…]}`                             |
| `header_inline`           | list[string] | 公共头文件里的 inline 函数（如 `lstrcpyW`、`wine_dbg_log`）                                     |                                                                              |
| `system`                  | list[string] | 系统 / 第三方库函数（libc、zlib 等；主要出现在 Unix 侧或链接第三方库的模块）                                    | `["deflate","deflateEnd"]`                                                   |
| `unresolved`              | list[string] | 调用了但 libclang 没能定位实现的符号（多为宏或汇编实现，如 `__wine_setjmpex`、RPC 存根 `remote_*`）            |                                                                              |
| `server_requests`         | list         | `SERVER_START_REQ(x)` 发往 wineserver 的请求：`request`、`handler`（`server/*.c` 里处理函数的位置） | `{"request":"get_clipboard_info","handler":"server/clipboard.c:563"}`        |
| `unix_calls`              | list         | `WINE_UNIX_CALL` 跨到 Unix 侧的调用：`code`（枚举名）、`function`（Unix 侧函数）、`impl`（位置）          |                                                                              |
| `indirect_calls`          | list         | 函数指针调用：`expr`（表达式）、`in_function`、`at`（位置）、`candidates`（静态分析推测的目标，可能为空）             | `{"expr":"view->ops->modify", …}`                                            |

---

## `meta`

| 字段                    | 类型           | 含义                                                                                                                          |
| --------------------- | ------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `deps_analysed`       | bool         | 是否做过 libclang 依赖分析（本数据集全部为 true；为 false 时没有 `same_file_dependencies` / `same_file_definitions` / `other_dependencies` 三个字段） |
| `parse_errors`        | int          | libclang 解析该文件时的错误数；500 条全部为 0（有错误的候选在生成时被拒绝，见 `excluded.txt`）                                                              |
| `parse_error_samples` | list[string] | 前几条错误信息（有错误时）                                                                                                               |

说明：wine500_doc 生成时先保留了 wine500 里有文档的 390 个函数、再随机补足；原先记录来源的 `meta.kept_from` 在后续 `--add-deps` / `--renumber` 处理中没有保留，需要对应时用 `module` + `name` 和 wine500 匹配即可。

---

## 字段和各场景提示词的对应

| 提示词内容         | 来源字段                                                              |
| ------------- | ----------------------------------------------------------------- |
| 模块、函数名        | `function.module`（或采样时的导出模块）、`function.export_name`               |
| 原型            | `function.signature`                                              |
| 文档（1.4 / 2.1） | `docs[].text`                                                     |
| `#include` 行  | `function.file_includes`                                          |
| 可调用的辅助函数      | `same_file_dependencies` 中 `exclusive_to_target == false` 的条目（原型） |
| 私有类型 / 全局 / 宏 | `same_file_definitions`                                           |
| 同名实现（可选）      | `same_name_in_other_dlls`（默认排除 `win16`）                           |
| 评测：替换位置、原实现   | `function.file`、`start_line`、`end_line`、`code`                    |
| 评测：要跑的测试      | `native_tests.files`                                              |
