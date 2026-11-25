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
title: getenv, _wgetenv | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/getenv-wgetenv?view=msvc-170
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
description: Describes the Microsoft C runtime library getenv and _wgetenv functions.
api_name:
- getenv
- _wgetenv
- _o__wgetenv
- _o_getenv
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
ms.assetid: 3b9cb9ab-a126-4e0e-a44f-6c5a7134daf4
locale: en-us
document_id: c9fc808d-eadc-6962-aac7-1969d4479512
document_version_independent_id: 7cf42b70-30ca-3bf7-081b-e11349261f40
updated_at: 2022-12-02T18:31:00.0000000Z
original_content_git_url: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/live/docs/c-runtime-library/reference/getenv-wgetenv.md
gitcommit: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/fe1e4033fd3de1981edefede8413356374f4a78a/docs/c-runtime-library/reference/getenv-wgetenv.md
git_commit_id: fe1e4033fd3de1981edefede8413356374f4a78a
default_moniker: msvc-170
site_name: Docs
depot_name: VS.vcppdocs
page_type: conceptual
toc_rel: ../toc.json
pdf_url_template: https://learn.microsoft.com/pdfstore/en-us/VS.vcppdocs/{branchName}{pdfName}
search.mshattr.devlang: cpp
word_count: 749
asset_id: c-runtime-library/reference/getenv-wgetenv
moniker_range_name: 4581682a33ffa46eb75263dee4d6680e
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
item_type: Content
source_path: docs/c-runtime-library/reference/getenv-wgetenv.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: 5a5dc889-d5e0-aa26-ef30-c0a9b4a26c19
---

# getenv, _wgetenv | Microsoft Learn

Gets a value from the current environment. More secure versions of these functions are available; see [`getenv_s`, `_wgetenv_s`](getenv-s-wgetenv-s).

Important

This API cannot be used in applications that execute in the Windows Runtime. For more information, see [CRT functions not supported in Universal Windows Platform apps](../../cppcx/crt-functions-not-supported-in-universal-windows-platform-apps).

## Syntax

```C
char *getenv(
   const char *varname
);
wchar_t *_wgetenv(
   const wchar_t *varname
);
```

### Parameters

*`varname`* Environment variable name.

## Return value

Returns a pointer to the environment table entry containing *`varname`*. It isn't safe to modify the value of the environment variable using the returned pointer. Use the [`_putenv`](putenv-wputenv) function to modify the value of an environment variable. The return value is `NULL` if *`varname`* isn't found in the environment table.

## Remarks

The **`getenv`** function searches the list of environment variables for *`varname`*. **`getenv`** isn't case sensitive in the Windows operating system. **`getenv`** and **`_putenv`** use the copy of the environment pointed to by the global variable **`_environ`** to access the environment. **`getenv`** operates only on the data structures accessible to the run-time library and not on the environment "segment" created for the process by the operating system. Therefore, programs that use the *`envp`* argument to [`main`](../../cpp/main-function-command-line-args) or [`wmain`](../../cpp/main-function-command-line-args) may retrieve invalid information.

If *`varname`* is `NULL`, this function invokes an invalid parameter handler, as described in [Parameter validation](../parameter-validation). If execution is allowed to continue, this function sets `errno` to `EINVAL` and returns `NULL`.

**`_wgetenv`** is a wide-character version of **`getenv`**; the argument and return value of **`_wgetenv`** are wide-character strings. The **`_wenviron`** global variable is a wide-character version of **`_environ`**.

In an MBCS program (for example, in an SBCS ASCII program), **`_wenviron`** is initially `NULL` because the environment is composed of multibyte-character strings. Then, on the first call to [`_wputenv`](putenv-wputenv), or on the first call to **`_wgetenv`** if an (MBCS) environment already exists, a corresponding wide-character string environment is created and is then pointed to by **`_wenviron`**.

Similarly in a Unicode (**`_wmain`**) program, **`_environ`** is initially `NULL` because the environment is composed of wide-character strings. Then, on the first call to **`_putenv`**, or on the first call to **`getenv`** if a (Unicode) environment already exists, a corresponding MBCS environment is created and is then pointed to by **`_environ`**.

When two copies of the environment (MBCS and Unicode) exist simultaneously in a program, the run-time system must maintain both copies, resulting in slower execution time. For example, whenever you call **`_putenv`**, a call to **`_wputenv`** is also executed automatically, so that the two environment strings correspond.

Caution

In rare instances, when the run-time system is maintaining both a Unicode version and a multibyte version of the environment, these two environment versions may not correspond exactly. This is because, although any unique multibyte-character string maps to a unique Unicode string, the mapping from a unique Unicode string to a multibyte-character string is not necessarily unique. For more information, see [`_environ`, `_wenviron`](../environ-wenviron).

Note

The **`_putenv`** and **`_getenv`** families of functions are not thread-safe. **`_getenv`** could return a string pointer while **`_putenv`** is modifying the string, causing random failures. Make sure that calls to these functions are synchronized.

By default, this function's global state is scoped to the application. To change this behavior, see [Global state in the CRT](../global-state).

### Generic-text routine mappings

| `TCHAR.H`routine | `_UNICODE`and`_MBCS`not defined | `_MBCS`defined | `_UNICODE`defined |
| --- | --- | --- | --- |
| **`_tgetenv`** | **`getenv`** | **`getenv`** | **`_wgetenv`** |

To check or change the value of the **`TZ`** environment variable, use **`getenv`**, **`_putenv`** and **`_tzset`** as necessary. For more information about **`TZ`**, see [`_tzset`](tzset) and [`_daylight`, `timezone`, and `_tzname`](../daylight-dstbias-timezone-and-tzname).

## Requirements

| Routine | Required header |
| --- | --- |
| **`getenv`** | `<stdlib.h>` |
| **`_wgetenv`** | `<stdlib.h>` or `<wchar.h>` |

For more compatibility information, see [Compatibility](../compatibility).

## Example

```C
// crt_getenv.c
// compile with: /W3
// This program uses getenv to retrieve
// the LIB environment variable and then uses
// _putenv to change it to a new value.

#include <stdlib.h>
#include <stdio.h>

int main( void )
{
   char *libvar;

   // Get the value of the LIB environment variable.
   libvar = getenv( "LIB" ); // C4996
   // Note: getenv is deprecated; consider using getenv_s instead

   if( libvar != NULL )
      printf( "Original LIB variable is: %s\n", libvar );

   // Attempt to change path. Note that this only affects the environment
   // variable of the current process. The command processor's
   // environment is not changed.
   _putenv( "LIB=c:\\mylib;c:\\yourlib" ); // C4996
   // Note: _putenv is deprecated; consider using putenv_s instead

   // Get new value.
   libvar = getenv( "LIB" ); // C4996

   if( libvar != NULL )
      printf( "New LIB variable is: %s\n", libvar );
}
```

```Output
Original LIB variable is: C:\progra~1\devstu~1\vc\lib
New LIB variable is: c:\mylib;c:\yourlib
```