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
title: atoi, _atoi_l, _wtoi, _wtoi_l | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/atoi-atoi-l-wtoi-wtoi-l?view=msvc-170
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
description: 'Learn more about: atoi, _atoi_l, _wtoi, _wtoi_l'
api_name:
- _wtoi
- _wtoi_l
- atoi
- _atoi_l
- _o__atoi_l
- _o__wtoi
- _o__wtoi_l
- _o_atoi
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
- api-ms-win-crt-convert-l1-1-0.dll
- ntoskrnl.exe
api_type:
- DLLExport
topic_type:
- apiref
ms.assetid: ad7fda30-28ab-421f-aaad-ef0b8868663a
locale: en-us
document_id: 70ffa4cf-db37-d151-cf38-c31ebcef71e4
document_version_independent_id: 7655b8b3-c3a0-95f2-0f67-79646e2efee4
updated_at: 2023-11-15T19:25:00.0000000Z
original_content_git_url: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/live/docs/c-runtime-library/reference/atoi-atoi-l-wtoi-wtoi-l.md
gitcommit: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/026efdf8b8d0d7721d2ca1e0757341744e7c40c0/docs/c-runtime-library/reference/atoi-atoi-l-wtoi-wtoi-l.md
git_commit_id: 026efdf8b8d0d7721d2ca1e0757341744e7c40c0
default_moniker: msvc-170
site_name: Docs
depot_name: VS.vcppdocs
page_type: conceptual
toc_rel: ../toc.json
pdf_url_template: https://learn.microsoft.com/pdfstore/en-us/VS.vcppdocs/{branchName}{pdfName}
search.mshattr.devlang: cpp
word_count: 518
asset_id: c-runtime-library/reference/atoi-atoi-l-wtoi-wtoi-l
moniker_range_name: 4581682a33ffa46eb75263dee4d6680e
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
item_type: Content
source_path: docs/c-runtime-library/reference/atoi-atoi-l-wtoi-wtoi-l.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: 114a3cbc-477d-41cb-feaf-39ccd8b01b6c
---

# atoi, _atoi_l, _wtoi, _wtoi_l | Microsoft Learn

Convert a string to integer.

## Syntax

```C
int atoi(
   const char *str
);
int _wtoi(
   const wchar_t *str
);
int _atoi_l(
   const char *str,
   _locale_t locale
);
int _wtoi_l(
   const wchar_t *str,
   _locale_t locale
);
```

### Parameters

*`str`* String to be converted.

*`locale`* Locale to use.

## Return value

Each function returns the **`int`** value produced by interpreting the input characters as a number. The return value is 0 for **`atoi`** and **`_wtoi`**, if the input can't be converted to a value of that type.

When the functions overflow with large negative integral values, `LONG_MIN` is returned. **`atoi`** and **`_wtoi`** return `INT_MAX` and `INT_MIN` on these conditions. In all out-of-range cases, `errno` is set to `ERANGE`. If the parameter passed in is `NULL`, the invalid parameter handler is invoked, as described in [Parameter validation](../parameter-validation). If execution is allowed to continue, these functions set `errno` to `EINVAL` and return 0.

## Remarks

These functions convert a character string to an integer value (**`atoi`** and **`_wtoi`**). The input string is a sequence of characters that can be interpreted as a numerical value of the specified type. The function stops reading the input string at the first character that it can't recognize as part of a number. This character may be the null character ('\0' or L'\0') terminating the string.

The *`str`* argument to **`atoi`** and **`_wtoi`** has the following form:

> 
> [*`whitespace`*] [*`sign`*] [*`digits`*]

A *`whitespace`* consists of space or tab characters, which are ignored; *`sign`* is either plus (+) or minus (-); and *`digits`* are one or more digits.

The versions of these functions with the **`_l`** suffix are identical except that they use the locale parameter passed in instead of the current locale. For more information, see [Locale](../locale).

By default, this function's global state is scoped to the application. To change this behavior, see [Global state in the CRT](../global-state).

### Generic-text routine mappings

| `TCHAR.H`routine | `_UNICODE`and`_MBCS`not defined | `_MBCS`defined | `_UNICODE`defined |
| --- | --- | --- | --- |
| **`_tstoi`** | **`atoi`** | **`atoi`** | **`_wtoi`** |
| **`_ttoi`** | **`atoi`** | **`atoi`** | **`_wtoi`** |

## Requirements

| Routines | Required header |
| --- | --- |
| **`atoi`** | `<stdlib.h>` |
| **`_atoi_l`**, **`_wtoi`**, **`_wtoi_l`** | `<stdlib.h>` or `<wchar.h>` |

## Example

This program shows how numbers stored as strings can be converted to numeric values using the **`atoi`** functions.

```C
// crt_atoi.c
// This program shows how numbers
// stored as strings can be converted to
// numeric values using the atoi functions.

#include <stdlib.h>
#include <stdio.h>
#include <errno.h>

int main( void )
{
    char    *str = NULL;
    int     value = 0;

    // An example of the atoi function.
    str = "  -2309 ";
    value = atoi( str );
    printf( "Function: atoi( \"%s\" ) = %d\n", str, value );

    // Another example of the atoi function.
    str = "31412764";
    value = atoi( str );
    printf( "Function: atoi( \"%s\" ) = %d\n", str, value );

    // Another example of the atoi function
    // with an overflow condition occurring.
    str = "3336402735171707160320";
    value = atoi( str );
    printf( "Function: atoi( \"%s\" ) = %d\n", str, value );
    if (errno == ERANGE)
    {
       printf("Overflow condition occurred.\n");
    }
}
```

```Output
Function: atoi( "  -2309 " ) = -2309
Function: atoi( "31412764" ) = 31412764
Function: atoi( "3336402735171707160320" ) = 2147483647
Overflow condition occurred.
```