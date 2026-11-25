---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the Matrix C++ class.
ms.assetid: 89be396f-7421-4a58-890b-6c7c34fe090c
title: Matrix Functions
ms.topic: reference
ms.date: 05/31/2018
---

# Matrix Functions

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**Matrix**](/windows/desktop/api/gdiplusmatrix/nl-gdiplusmatrix-matrix) C++ class.

## Matrix Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                     | Wrapper method                                                                                              | Description                                                                                                                                                                                                                                                                                                                                                           |
|-----------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipCreateMatrix2(REAL m11, REAL m12, REAL m21, REAL m22, REAL dx, REAL dy, GpMatrix \*\*matrix)<br/>   | [**Matrix::Matrix**](/windows/win32/api/gdiplusmatrix/nf-gdiplusmatrix-matrix-matrix(inreal_inreal_inreal_inreal_inreal_inreal))                               | Creates and initializes a [**Matrix::Matrix**](/windows/win32/api/gdiplusmatrix/nf-gdiplusmatrix-matrix-matrix(inreal_inreal_inreal_inreal_inreal_inreal)) object based on six numbers that define an affine transformation.                                                                                                                                                                                             |
