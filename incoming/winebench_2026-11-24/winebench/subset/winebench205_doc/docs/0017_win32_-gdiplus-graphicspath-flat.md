---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the GraphicsPath C++ class.
ms.assetid: abfb280e-92db-4198-b9e1-d0782cca1ccd
title: GraphicsPath Functions
ms.topic: reference
ms.date: 05/31/2018
---

# GraphicsPath Functions

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**GraphicsPath**](/windows/desktop/api/gdipluspath/nl-gdipluspath-graphicspath) C++ class.

## GraphicsPath Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                                                                                                                   | Wrapper method                                                                                                                                                                                                                                                                                                     | Remarks                                                                                                                                                                                                                                                                                                                 |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipAddPathRectangle(GpPath \*path, REAL x, REAL y, REAL width, REAL height)<br/>                                                                                                                     | [**Status GraphicsPath::AddRectangle(IN const RectF& rect)**](/previous-versions//ms535592(v=vs.85))                                                                                                                                                                                            | Adds a rectangle to this path.<br/>The *x*, *y*, *width*, and *height* parameters in the flat function specify a rectangle that corresponds to the *rect* parameter in the wrapper method.                                                                                                                        |
