# winebench205_doc

WineBench 评测子集,205 个函数,格式与 wine500_doc 相同(一个函数一个 `NNNN_<模块>_<函数名>.json`,文档页在 `docs/`,清单在 `manifest.json`)。
源码版本:Wine 11.19(commit 455e3509)。

## 抽取规则
- 来源:winebench.json 的 4,598 个函数(完全实现、有微软文档、有被 relay 确认执行过的本模块测试)。
- 代码行数(含签名)>= 15;本模块测试函数数 > 10 且 <= 50。
- 一级分类不足 10 个时,只降低该分类的测试数下限,补到 10 个;同一测试数下有多个候选时用固定随机种子抽。
- 各分类数量、实际用的下限见 `subset_summary.txt`;完整清单见 `winebench_subset.csv`。

## 与 wine500_doc 的差别
- `native_tests.files`:不再是"测试目录里提到函数名的文件",而是新方案确认过的本模块测试文件
  (测试源码里直接调用该函数、调用点不是 todo、relay 日志确认执行过)。
- `docs`:页面由 WineBench 的文档索引选出,字段与原来相同。GDI+ flat API 的文档是整页大表,
  这 15 个函数只保留页面说明、表头和该函数所在的一行(`docs[].excerpt` 里记了原页面长度)。
- 新增 `winebench` 字段:功能分类、行数、圈复杂度、测试数、本模块测试函数清单、文档地址、入选方式。其余字段含义不变。
- `function`、`same_name_in_other_dlls`、`same_file_dependencies`、`same_file_definitions`、`other_dependencies`、`meta`
  由原来的 build_benchmark.py(build_record / add_deps)生成,没有改动。

## 需要留意的记录
- 0160、0166(msi):依赖分析各有 1 条解析报错(widl 生成的 `s_IWineMsiRemote_v0_0_s_ifspec` 未声明),不影响函数本身的代码和依赖。
- 0196(dbghelp!MiniDumpReadDumpStream):依赖分析有大量解析报错(生成这份数据的环境里,gcc 13 的 intrinsics 头文件与 libclang 不兼容;换环境重跑可能消失),
  `same_file_dependencies` / `other_dependencies` 可能不完整;函数代码、测试、文档不受影响。原流水线会丢弃这种记录,这里保留并在 `meta.parse_errors` 里标出。
- 0079、0080(comctl32):返回类型单独占一行,`start_line` / `signature` / `code` 已补上这一行(`meta.locate_note`)。

## 重新生成
见 `build_subset_dataset.py` 文件开头的说明。
