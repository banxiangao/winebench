---
layout: Conceptual
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
defaultMoniker: msvc-170
versioningType: Ranged
title: _putenv, _wputenv | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/putenv-wputenv?view=msvc-170
config_moniker_range: '>= msvc-140'
breadcrumb_path: ../../_breadcrumb/toc.json
uhfHeaderId: MSDocsHeader-CPP
ROBOTS: INDEX,FOLLOW
manager: coxford
ms.date: 2020-04-02T00:00:00.0000000Z
ms.topic: reference
audience: developer
ms.service: visual-cpp
ms.tgt_pltfrm: Windows
ms.workload:
- cplusplus
feedback_system: Standard
feedback_product_url: https://developercommunity.visualstudio.com/cpp/
feedback_help_link_url: https://learn.microsoft.com/en-us/answers/tags/314/cpp
feedback_help_link_type: get-help-at-qna
ms.subservice: ucrt
ms.update-cycle: 3650-days
author: TylerMSFT
ms.author: twhitney
description: 'Learn more about: _putenv, _wputenv'
api_name:
- _putenv
- _wputenv
- _o__putenv
- _o__wputenv
api_location:
- msvcrt.dll
- msvcr80.dll
- msvcr90.dll
- msvcr100.dll
- msvcr100_clr0400.dll
- msvcr110.dll
- msvcr110_clr0400.dll
- msvcr120.dll
- msvcr120_clr0400.dll
- ucrtbase.dll
- api-ms-win-crt-environment-l1-1-0.dll
api_type:
- DLLExport
topic_type:
- apiref
locale: en-us
document_id: 3a814b8f-2e20-321d-a2a4-b093f71f9f4c
document_version_independent_id: dbe717ea-5a64-6df6-8c5a-6a3c0bc84cc8
updated_at: 2022-12-02T18:31:00.0000000Z
original_content_git_url: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/live/docs/c-runtime-library/reference/putenv-wputenv.md
gitcommit: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/fe1e4033fd3de1981edefede8413356374f4a78a/docs/c-runtime-library/reference/putenv-wputenv.md
git_commit_id: fe1e4033fd3de1981edefede8413356374f4a78a
default_moniker: msvc-170
site_name: Docs
depot_name: VS.vcppdocs
page_type: conceptual
toc_rel: ../toc.json
pdf_url_template: https://learn.microsoft.com/pdfstore/en-us/VS.vcppdocs/{branchName}{pdfName}
search.mshattr.devlang: cpp
word_count: 530
asset_id: c-runtime-library/reference/putenv-wputenv
moniker_range_name: 4581682a33ffa46eb75263dee4d6680e
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
item_type: Content
source_path: docs/c-runtime-library/reference/putenv-wputenv.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: ade9459a-9478-4806-2735-bd9d99e46aae
---

# _putenv, _wputenv | Microsoft Learn

Creates, modifies, or removes environment variables. More secure versions of these functions are available; see [`_putenv_s`, `_wputenv_s`](putenv-s-wputenv-s).

Important

This API cannot be used in applications that execute in the Windows Runtime. For more information, see [CRT functions not supported in Universal Windows Platform apps](../../cppcx/crt-functions-not-supported-in-universal-windows-platform-apps).

## Syntax

```C
int _putenv(
   const char *envstring
);
int _wputenv(
   const wchar_t *envstring
);
```

### Parameters

*`envstring`* Environment-string definition.

## Return value

The functions return 0 if successful, or -1 if there's an error.

## Remarks

The **`_putenv`** function adds new environment variables or modifies the values of existing environment variables. Environment variables define the environment in which a process executes (for example, the default search path for libraries to be linked with a program). **`_wputenv`** is a wide-character version of **`_putenv`**; the *`envstring`* argument to **`_wputenv`** is a wide-character string.

By default, this function's global state is scoped to the application. To change this behavior, see [Global state in the CRT](../global-state).

### Generic-text routine mappings

| `Tchar.h`routine | `_UNICODE and _MBCS`not defined | `_MBCS`defined | `_UNICODE`defined |
| --- | --- | --- | --- |
| `_tputenv` | **`_putenv`** | **`_putenv`** | **`_wputenv`** |

The *`envstring`* argument must be a pointer to a string of the form *`varname=value_string`*, where *`varname`* is the name of the environment variable to be added or modified and *`value_string`* is the variable's value. If *`varname`* is already part of the environment, its value is replaced by *`value_string`*; otherwise, the new *`varname`* variable and its *`value_string`* value are added to the environment. You can remove a variable from the environment by specifying an empty *`value_string`*, or in other words, by specifying only *`varname`*=.

**`_putenv`** and **`_wputenv`** affect only the environment that is local to the current process; you can't use them to modify the command-level environment. That is, these functions operate only on data structures accessible to the run-time library. They don't operate on the environment segment created for a process by the operating system. When the current process terminates, the environment reverts to the level of the calling process (in most cases, the operating-system level). However, the modified environment can be passed to any new processes created by **`_spawn`**, **`_exec`**, or **`system`**, and these new processes get any new items added by **`_putenv`** and **`_wputenv`**.

Don't change an environment entry directly: instead, use **`_putenv`** or **`_wputenv`** to change it. In particular, direct freeing elements of the **`_environ[]`** global array might lead to invalid memory being addressed.

**`_getenv`** and **`_putenv`** use the global variable **`_environ`** to access the environment table; **`_wgetenv`** and **`_wputenv`** use **`_wenviron`**. **`_putenv`** and **`_wputenv`** might change the value of **`_environ`** and **`_wenviron`**, thus invalidating the **`_envp`** argument to **`main`** and the **`_wenvp`** argument to **`wmain`**. Therefore, it's safer to use **`_environ`** or **`_wenviron`** to access the environment information. For more information about the relation of **`_putenv`** and **`_wputenv`** to global variables, see [`_environ`, `_wenviron`](../environ-wenviron).

Note

The **`_putenv`** and **`_getenv`** families of functions are not thread-safe. **`_getenv`** could return a string pointer while **`_putenv`** is modifying the string, causing random failures. Make sure that calls to these functions are synchronized.

## Requirements

| Routine | Required header |
| --- | --- |
| **`_putenv`** | `<stdlib.h>` |
| **`_wputenv`** | `<stdlib.h>` or `<wchar.h>` |

For more compatibility information, see [Compatibility](../compatibility).

## Example

For a sample of how to use **`_putenv`**, see [`getenv`, `_wgetenv`](getenv-wgetenv).