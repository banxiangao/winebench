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
title: strcmp, wcscmp, _mbscmp, _mbscmp_l | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/strcmp-wcscmp-mbscmp?view=msvc-170
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
description: 'Learn more about: strcmp, wcscmp, _mbscmp, _mbscmp_l'
api_name:
- wcscmp
- _mbscmp
- _mbscmp_l
- strcmp
- _o__mbscmp
- _o__mbscmp_l
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
- ntdll.dll
- ucrtbase.dll
- api-ms-win-crt-multibyte-l1-1-0.dll
- api-ms-win-crt-string-l1-1-0.dll
- ntoskrnl.exe
api_type:
- DLLExport
topic_type:
- apiref
ms.assetid: 5d216b57-7a5c-4cb3-abf0-0f4facf4396d
locale: en-us
document_id: 4c346890-de61-d9aa-76f4-bd91ab800c97
document_version_independent_id: baa04c75-b8dd-e81a-1178-76fdf68f7066
updated_at: 2022-12-02T18:31:00.0000000Z
original_content_git_url: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/live/docs/c-runtime-library/reference/strcmp-wcscmp-mbscmp.md
gitcommit: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/fe1e4033fd3de1981edefede8413356374f4a78a/docs/c-runtime-library/reference/strcmp-wcscmp-mbscmp.md
git_commit_id: fe1e4033fd3de1981edefede8413356374f4a78a
default_moniker: msvc-170
site_name: Docs
depot_name: VS.vcppdocs
page_type: conceptual
toc_rel: ../toc.json
pdf_url_template: https://learn.microsoft.com/pdfstore/en-us/VS.vcppdocs/{branchName}{pdfName}
search.mshattr.devlang: cpp
word_count: 812
asset_id: c-runtime-library/reference/strcmp-wcscmp-mbscmp
moniker_range_name: 4581682a33ffa46eb75263dee4d6680e
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
item_type: Content
source_path: docs/c-runtime-library/reference/strcmp-wcscmp-mbscmp.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: 5bcbce71-0ca7-1ed5-0ba5-1e2f791207b9
---

# strcmp, wcscmp, _mbscmp, _mbscmp_l | Microsoft Learn

Compare strings.

Important

**`_mbscmp`** and **`_mbscmp_l`** cannot be used in applications that execute in the Windows Runtime. For more information, see [CRT functions not supported in Universal Windows Platform apps](../../cppcx/crt-functions-not-supported-in-universal-windows-platform-apps).

## Syntax

```C
int strcmp(
   const char *string1,
   const char *string2
);
int wcscmp(
   const wchar_t *string1,
   const wchar_t *string2
);
int _mbscmp(
   const unsigned char *string1,
   const unsigned char *string2
);
int _mbscmp_l(
   const unsigned char *string1,
   const unsigned char *string2,
   _locale_t locale
);
```

### Parameters

*`string1`*, *`string2`* Null-terminated strings to compare.

*`locale`* Locale to use.

## Return value

The return value for each of these functions indicates the ordinal relation of *`string1`* to *`string2`*.

| Value | Relationship of`string1`to`string2` |
| --- | --- |
| &lt; 0 | *`string1`* is less than *`string2`* |
| 0 | *`string1`* is identical to *`string2`* |
| &gt; 0 | *`string1`* is greater than *`string2`* |

On a parameter validation error, **`_mbscmp`** and **`_mbscmp_l`** return `_NLSCMPERROR`, which is defined in `<string.h>` and `<mbstring.h>`.

## Remarks

The **`strcmp`** function performs an ordinal comparison of *`string1`* and *`string2`* and returns a value that indicates their relationship. **`wcscmp`** and **`_mbscmp`** are, respectively, wide-character and multibyte-character versions of **`strcmp`**. **`_mbscmp`** recognizes multibyte-character sequences according to the current multibyte code page and returns `_NLSCMPERROR` on an error. **`_mbscmp_l`** has the same behavior, but uses the locale parameter that's passed in instead of the current locale. For more information, see [Code pages](../code-pages). Also, if *`string1`* or *`string2`* is a null pointer, **`_mbscmp`** invokes the invalid parameter handler, as described in [Parameter validation](../parameter-validation). If execution is allowed to continue, **`_mbscmp`** and **`_mbscmp_l`** return `_NLSCMPERROR` and set `errno` to `EINVAL`. **`strcmp`** and **`wcscmp`** don't validate their parameters. These functions behave identically otherwise.

By default, this function's global state is scoped to the application. To change this behavior, see [Global state in the CRT](../global-state).

### Generic-text routine mappings

| `TCHAR.H`routine | `_UNICODE`and`_MBCS`not defined | `_MBCS`defined | `_UNICODE`defined |
| --- | --- | --- | --- |
| `_tcscmp` | **`strcmp`** | **`_mbscmp`** | **`wcscmp`** |

The **`strcmp`** functions differ from the **`strcoll`** functions in that **`strcmp`** comparisons are ordinal, and aren't affected by locale. **`strcoll`** compares strings lexicographically by using the `LC_COLLATE` category of the current locale. For more information about the `LC_COLLATE` category, see [`setlocale`, `_wsetlocale`](setlocale-wsetlocale).

In the "C" locale, the order of characters in the character set (ASCII character set) is the same as the lexicographic character order. However, in other locales, the order of characters in the character set may differ from the lexicographic order. For example, in certain European locales, the character '`a`' (value 0x61) comes before the character '`ä`' (value 0xE4) in the character set, but the character '`ä`' comes in front of the character '`a`' lexicographically.

In locales for which the character set and the lexicographic character order differ, you can use **`strcoll`** instead of **`strcmp`** for lexicographic comparison of strings. Alternatively, you can use **`strxfrm`** on the original strings, and then use **`strcmp`** on the resulting strings.

The **`strcmp`** functions are case-sensitive. **`_stricmp`**, **`_wcsicmp`**, and **`_mbsicmp`** compare strings by first converting them to their lowercase forms. Two strings that contain characters that are located between 'Z' and 'a' in the ASCII table ('`[`', '`\\`', '`]`', '`^`', '`_`', and '```') compare differently, depending on their case. For example, the two strings "`ABCDE`" and "`ABCD^`" compare one way if the comparison is lowercase ("`abcde`" &gt; "`abcd^`") and the other way ("`ABCDE`" &lt; "`ABCD`^") if the comparison is uppercase.

## Requirements

| Routine | Required header |
| --- | --- |
| **`strcmp`** | `<string.h>` |
| **`wcscmp`** | `<string.h>` or `<wchar.h>` |
| **`_mbscmp`** | `<mbstring.h>` |

For more compatibility information, see [Compatibility](../compatibility).

## Libraries

All versions of the [C run-time libraries](../crt-library-features).

## Example

```C
// crt_strcmp.c

#include <string.h>
#include <stdio.h>
#include <stdlib.h>

char string1[] = "The quick brown dog jumps over the lazy fox";
char string2[] = "The QUICK brown dog jumps over the lazy fox";

int main( void )
{
   char tmp[20];
   int result;

   // Case sensitive
   printf( "Compare strings:\n   %s\n   %s\n\n", string1, string2 );
   result = strcmp( string1, string2 );
   if( result > 0 )
      strcpy_s( tmp, _countof(tmp), "greater than" );
   else if( result < 0 )
      strcpy_s( tmp, _countof (tmp), "less than" );
   else
      strcpy_s( tmp, _countof (tmp), "equal to" );
   printf( "   strcmp:   String 1 is %s string 2\n", tmp );

   // Case insensitive (could use equivalent _stricmp)
   result = _stricmp( string1, string2 );
   if( result > 0 )
      strcpy_s( tmp, _countof (tmp), "greater than" );
   else if( result < 0 )
      strcpy_s( tmp, _countof (tmp), "less than" );
   else
      strcpy_s( tmp, _countof (tmp), "equal to" );
   printf( "   _stricmp:  String 1 is %s string 2\n", tmp );
}
```

```Output
Compare strings:
   The quick brown dog jumps over the lazy fox
   The QUICK brown dog jumps over the lazy fox

   strcmp:   String 1 is greater than string 2
   _stricmp:  String 1 is equal to string 2
```