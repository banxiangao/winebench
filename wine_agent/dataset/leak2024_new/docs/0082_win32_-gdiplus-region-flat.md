---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the Region C++ class.
ms.assetid: 2f1d3631-7104-421a-a577-ef764bffe034
title: Region Functions (GDI+)
ms.topic: reference
ms.date: 05/31/2018
---

# Region Functions (GDI+)

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**Region**](/windows/desktop/api/gdiplusheaders/nl-gdiplusheaders-region) C++ class.

## Region Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                                            | Wrapper method                                                                                                                                                                                       | Remarks                                                                                                                                                                                                                                                                                                           |
|----------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipIsVisibleRegionPoint(GpRegion \*region, REAL x, REAL y, GpGraphics \*graphics, BOOL \*result)<br/>                         | [**BOOL Region::IsVisible(IN const PointF& point, IN const Graphics\* g) const**](/windows/win32/api/gdiplusheaders/nf-gdiplusheaders-region-isvisible(inconstpointf__inconstgraphics))<br/>                                           | Determines whether a point is inside this region.<br/> The *x* and *y* parameters in the flat function specify the x and y coordinates of a point that corresponds to the *point* parameter in the wrapper method.<br/>                                                                               |
