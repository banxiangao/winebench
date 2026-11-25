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
title: fclose, _fcloseall | Microsoft Learn
canonicalUrl: https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/fclose-fcloseall?view=msvc-170
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
description: 'Learn more about: fclose, _fcloseall'
api_name:
- fclose
- _fcloseall
- _o__fcloseall
- _o_fclose
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
locale: en-us
document_id: ef8f4985-b1ee-d844-ac82-929d99e767ba
document_version_independent_id: 2069cc19-b175-3f1c-53e0-224e39d98965
updated_at: 2022-12-02T18:31:00.0000000Z
original_content_git_url: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/live/docs/c-runtime-library/reference/fclose-fcloseall.md
gitcommit: https://github.com/MicrosoftDocs/cpp-docs-pr/blob/fe1e4033fd3de1981edefede8413356374f4a78a/docs/c-runtime-library/reference/fclose-fcloseall.md
git_commit_id: fe1e4033fd3de1981edefede8413356374f4a78a
default_moniker: msvc-170
site_name: Docs
depot_name: VS.vcppdocs
page_type: conceptual
toc_rel: ../toc.json
pdf_url_template: https://learn.microsoft.com/pdfstore/en-us/VS.vcppdocs/{branchName}{pdfName}
search.mshattr.devlang: cpp
word_count: 314
asset_id: c-runtime-library/reference/fclose-fcloseall
moniker_range_name: 4581682a33ffa46eb75263dee4d6680e
monikers:
- msvc-140
- msvc-150
- msvc-160
- msvc-170
- msvc-180
item_type: Content
source_path: docs/c-runtime-library/reference/fclose-fcloseall.md
cmProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/2d774b87-7dcb-40bf-a0b9-5a7a9efff0d1
- https://authoring-docs-microsoft.poolparty.biz/devrel/540ac133-a371-4dbb-8f94-28d6cc77a70b
spProducts:
- https://authoring-docs-microsoft.poolparty.biz/devrel/89dc5f37-0e4e-4b05-ad87-5fcd2b941a8a
- https://authoring-docs-microsoft.poolparty.biz/devrel/60bfc045-f127-4841-9d00-ea35495a5800
platformId: 899a685c-bf22-878b-54dd-b0df5aa226ae
---

# fclose, _fcloseall | Microsoft Learn

Closes a stream (**`fclose`**) or closes all open streams (**`_fcloseall`**).

## Syntax

```C
int fclose(
   FILE *stream
);
int _fcloseall( void );
```

### Parameters

*`stream`* Pointer to `FILE` structure.

## Return value

**`fclose`** returns 0 if the stream is successfully closed. **`_fcloseall`** returns the total number of streams closed. Both functions return `EOF` to indicate an error.

## Remarks

The **`fclose`** function closes *`stream`*. If *`stream`* is `NULL`, the invalid parameter handler is invoked, as described in [Parameter validation](../parameter-validation). If execution is allowed to continue, **`fclose`** sets `errno` to `EINVAL` and returns `EOF`. It's recommended that you always check the *`stream`* pointer before you call this function.

For more information about return codes, see [`errno`, `_doserrno`, `_sys_errlist`, and `_sys_nerr`](../errno-doserrno-sys-errlist-and-sys-nerr).

The **`_fcloseall`** function closes all open streams except **`stdin`**, **`stdout`**, **`stderr`** (and, in MS-DOS, **`_stdaux`** and **`_stdprn`**). It also closes and deletes any temporary files created by **`tmpfile`**. In both functions, all buffers associated with the stream are flushed prior to closing. System-allocated buffers are released when the stream is closed. Buffers assigned by the user with **`setbuf`** and **`setvbuf`** aren't automatically released.

Note

When `fclose` or `_fcloseall` functions are used to close a stream, the underlying file descriptor and OS file handle (or socket) are closed as well. Thus, if the file was originally opened as a file handle or file descriptor and is closed with **`fclose`**, don't also call **`_close`** to close the file descriptor; and don't call the Win32 function `CloseHandle` to close the file handle.

**`fclose`** and **`_fcloseall`** include code to protect against interference from other threads. For non-locking version of a **`fclose`**, see **`_fclose_nolock`**.

By default, this function's global state is scoped to the application. To change this behavior, see [Global state in the CRT](../global-state).

## Requirements

| Function | Required header |
| --- | --- |
| **`fclose`** | `<stdio.h>` |
| **`_fcloseall`** | `<stdio.h>` |

For more compatibility information, see [Compatibility](../compatibility).

## Example

See the example for [`fopen`](fopen-wfopen).