---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the Pen C++ class.
ms.assetid: e523339d-639e-4e8e-b0cb-0c9464eeee03
title: Pen Functions (GDI+)
ms.topic: reference
ms.date: 05/31/2018
---

# Pen Functions (GDI+)

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**Pen**](/windows/desktop/api/gdipluspen/nl-gdipluspen-pen) C++ class.

## Pen Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                | Wrapper method                                                                                                                                                              | Remarks                                                                                                                                                                                                                                                                                                                                                 |
|------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipDeletePen(GpPen \*pen)<br/>                                                                    | Pen::~Pen() <br/>                                                                                                                                                     | Releases resources used by the [**Pen**](/windows/desktop/api/gdipluspen/nl-gdipluspen-pen) object.                                                                                                                                                                                                                                                                          |
