---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the Graphics Text C++ class.
ms.assetid: 70d35c08-08d9-46a6-a6df-76d989551866
title: Text Functions
ms.topic: reference
ms.date: 05/31/2018
---

# Text Functions

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md). The following flat API functions are wrapped by the [**Graphics**](/windows/desktop/api/gdiplusgraphics/nl-gdiplusgraphics-graphics) Text C++ class.

## Text Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                                                                                                                                                                   | Wrapper method                                                                                                                                                                                                                                                                                                                                                                        | Remarks                                                                                                                                                                                                           |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipMeasureString( GpGraphics \*graphics, GDIPCONST WCHAR \*string, INT length, GDIPCONST GpFont \*font, GDIPCONST RectF \*layoutRect, GDIPCONST GpStringFormat \*stringFormat, RectF \*boundingBox, INT \*codepointsFitted, INT \*linesFilled )<br/> | [**Status Graphics::MeasureString( IN const WCHAR \*string, IN INT length, IN const Font \*font, IN const RectF &layoutRect, IN const StringFormat \*stringFormat, OUT RectF \*boundingBox, OUT INT \*codepointsFitted = 0, OUT INT \*linesFilled = 0 ) const**](/previous-versions//ms535831(v=vs.85))<br/> | Measures the extent of the string in the specified font, format, and layout rectangle.                                                                                                                            |
