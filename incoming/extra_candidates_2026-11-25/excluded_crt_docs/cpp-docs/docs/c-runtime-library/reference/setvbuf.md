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
title: setvbuf | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/setvbuf?view=msvc-170
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
description: 'Learn more about: setvbuf'
api_name:
- setvbuf
- _o_setvbuf
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
- api-ms-win-crt-stdio-l1-1-0.dll
api_type:
- DLLExport
topic_type:
- apiref
ms.assetid: 6aa5aa37-3408-4fa0-992f-87f9f9c4baea
locale: en-us
document_id: ede83b72-379a-ca24-f18f-5e55eeb3e9c7
document_version_independent_id: 4025d0d3-60aa-14df-7625-d92dfadab895
updated_at: 2022-12-02T18:31:00.0000000Z
original_content_git_url: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/live/docs/c-runtime-library/reference/setvbuf.md
gitcommit: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/fe1e4033fd3de1981edefede8413356374f4a78a/docs/c-runtime-library/reference/setvbuf.md
git_commit_id: fe1e4033fd3de1981edefede8413356374f4a78a
default_moniker: msvc-170
site_name: Docs
depot_name: VS.vcppdocs
page_type: conceptual
toc_rel: ../toc.json
pdf_url_template: https://learn.microsoft.com/pdfstore/en-us/VS.vcppdocs/{branchName}{pdfName}
search.mshattr.devlang: cpp
word_count: 476
asset_id: c-runtime-library/reference/setvbuf
moniker_range_name: 4581682a33ffa46eb75263dee4d6680e
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
item_type: Content
source_path: docs/c-runtime-library/reference/setvbuf.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/2d774b87-7dcb-40bf-a0b9-5a7a9efff0d1
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/89dc5f37-0e4e-4b05-ad87-5fcd2b941a8a
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: f3758aec-b49c-7f00-258f-9fd8f6f73fa4
---

# setvbuf | Microsoft Learn

Controls stream buffering and buffer size.

## Syntax

```C
int setvbuf(
   FILE *stream,
   char *buffer,
   int mode,
   size_t size
);
```

### Parameters

*`stream`* Pointer to `FILE` structure.

*`buffer`* User-allocated buffer.

*`mode`* Mode of buffering.

*`size`* Buffer size in bytes. Allowable range: 2 &lt;= *`size`* &lt;= INT\_MAX (2147483647). Internally, the value supplied for *`size`* is rounded down to the nearest multiple of 2.

## Return value

Returns 0 if successful.

If *`stream`* is `NULL`, or if *`mode`* or *`size`* isn't within a valid change, the invalid parameter handler is invoked, as described in [Parameter validation](../parameter-validation). If execution is allowed to continue, this function returns -1 and sets `errno` to `EINVAL`.

For information on these and other error codes, see [`errno`, `_doserrno`, `_sys_errlist`, and `_sys_nerr`](../errno-doserrno-sys-errlist-and-sys-nerr).

## Remarks

The **`setvbuf`** function allows the program to control both buffering and buffer size for *`stream`*. *`stream`* must refer to an open file that hasn't undergone an I/O operation since it was opened. The array pointed to by *`buffer`* is used as the buffer, unless *`buffer`* is `NULL`, in which case **`setvbuf`** uses an automatically allocated buffer of length *`size`*/2 \* 2 bytes.

The mode must be `_IOFBF`, `_IOLBF`, or `_IONBF`. If *`mode`* is `_IOFBF` or `_IOLBF`, then *`size`* is used as the size of the buffer. If *`mode`* is `_IONBF`, the stream is unbuffered, and both *`size`* and *`buffer`* are ignored. Values for *`mode`* and their meanings are:

| *`mode`*value | Meaning |
| --- | --- |
| `_IOFBF` | Full buffering; that is, *`buffer`* is used as the buffer and *`size`* is used as the size of the buffer. If *`buffer`* is `NULL`, this mode uses an automatically allocated buffer that's *`size`* bytes long. |
| `_IOLBF` | For some systems, this mode provides line buffering. However, for Win32, the behavior is the same as `_IOFBF` - Full Buffering. |
| `_IONBF` | No buffer is used, regardless of *`buffer`* or *`size`*. |

By default, this function's global state is scoped to the application. To change this behavior, see [Global state in the CRT](../global-state).

## Requirements

| Routine | Required header |
| --- | --- |
| **`setvbuf`** | &lt;stdio.h&gt; |

For more compatibility information, see [Compatibility](../compatibility).

## Libraries

All versions of the [C run-time libraries](../crt-library-features).

## Example

```C
// crt_setvbuf.c
// This program opens two streams: stream1
// and stream2. It then uses setvbuf to give stream1 a
// user-defined buffer of 1024 bytes and stream2 no buffer.
//

#include <stdio.h>

int main( void )
{
   char buf[1024];
   FILE *stream1, *stream2;

   if( fopen_s( &stream1, "data1", "a" ) == 0 &&
       fopen_s( &stream2, "data2", "w" ) == 0 )
   {
      if( setvbuf( stream1, buf, _IOFBF, sizeof( buf ) ) != 0 )
         printf( "Incorrect type or size of buffer for stream1\n" );
      else
         printf( "'stream1' now has a buffer of 1024 bytes\n" );
      if( setvbuf( stream2, NULL, _IONBF, 0 ) != 0 )
         printf( "Incorrect type or size of buffer for stream2\n" );
      else
         printf( "'stream2' now has no buffer\n" );
      _fcloseall();
   }
}
```

```Output
'stream1' now has a buffer of 1024 bytes
'stream2' now has no buffer
```