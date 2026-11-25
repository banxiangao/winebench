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
| GpStatus WINGDIPAPI GdipAddPathLine(GpPath \*path, REAL x1, REAL y1, REAL x2, REAL y2)<br/>                                                                                                                               | [**Status GraphicsPath::AddLine(IN REAL x1, IN REAL y1, IN REAL x2, IN REAL y2)**](/windows/win32/api/gdipluspath/nf-gdipluspath-graphicspath-addline(inreal_inreal_inreal_inreal))                                                                                                                                                       | Adds a line to the current figure of this path.                                                                                                                                                                                                                                                                         |
