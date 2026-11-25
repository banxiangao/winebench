---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the FontFamily C++ class.
ms.assetid: c1a1e679-a4f5-4693-9c07-0e8c97c877f3
title: FontFamilyFunctions
ms.topic: reference
ms.date: 05/31/2018
---

# FontFamilyFunctions

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**FontFamily**](/windows/desktop/api/gdiplusheaders/nl-gdiplusheaders-fontfamily) C++ class.

## FontFamily Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                                                                        | Wrapper method                                                                                                                                                 | Remarks                                                                                                                                                                                                      |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipCreateFontFamilyFromName(GDIPCONST WCHAR \*name, GpFontCollection \*fontCollection, GpFontFamily \*\*FontFamily)<br/>                                  | [**FontFamily::FontFamily( IN const WCHAR\* name, IN const FontCollection\* fontCollection )**](/windows/win32/api/gdiplusheaders/nf-gdiplusheaders-fontfamily-fontfamily(inconstwchar_inconstfontcollection)) | Creates a [**FontFamily::FontFamily**](/windows/desktop/api/gdiplusheaders/nl-gdiplusheaders-fontfamily) object based on a specified font family.                                                                                         |
