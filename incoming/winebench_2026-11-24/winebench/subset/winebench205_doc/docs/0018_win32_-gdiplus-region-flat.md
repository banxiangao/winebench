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
| GpStatus WINGDIPAPI GdipCombineRegionRect(GpRegion \*region, GDIPCONST GpRectF \*rect, CombineMode combineMode)<br/>                               | [**Status Region::Intersect(IN const RectF& rect)**](/windows/win32/api/gdiplusheaders/nf-gdiplusheaders-region-intersect(inconstrectf_))<br/>                                                                                     | Updates this region to the portion of itself that intersects the specified rectangle's interior.<br/> The *combineMode* parameter in the flat function is a member of the [**CombineMode**](/windows/desktop/api/Gdiplusenums/ne-gdiplusenums-combinemode) enumeration that specifies how the region and rectangle are combined.<br/> |
