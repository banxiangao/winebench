---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the Font C++ class.
ms.assetid: fcc37af2-cd90-42e6-9b7f-20b123f8ab1f
title: Font Functions
ms.topic: reference
ms.date: 05/31/2018
---

# Font Functions

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**Font**](/windows/desktop/api/gdiplusheaders/nl-gdiplusheaders-font) C++ class.

## Font Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                                                     | Wrapper method                                                                                                                                                           | Remarks                                                                                                                                                                                                                                                                                                                                         |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipCreateFont( GDIPCONST GpFontFamily \*fontFamily, REAL emSize, INT style, Unit unit, GpFont \*\*font )<br/>                          | [**Font::Font( IN const FontFamily \* family, IN REAL emSize, IN INT style, IN Unit unit )**](/windows/win32/api/gdiplusheaders/nf-gdiplusheaders-font-font(inconstwchar_inreal_inint_inunit_inconstfontcollection)) | Creates a [**Font**](/windows/desktop/api/gdiplusheaders/nl-gdiplusheaders-font) object based on a font family, a size, a font style, a unit of measurement, and a [**FontCollection**](/windows/desktop/api/gdiplusheaders/nl-gdiplusheaders-fontcollection) object.                                                                                                                                     |
