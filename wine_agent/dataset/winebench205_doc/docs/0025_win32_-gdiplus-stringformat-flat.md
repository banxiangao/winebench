---
description: Windows GDI+ exposes a flat API that consists of about 600 functions. These flat API functions are wrapped by the StringFormat C++ class.
ms.assetid: 8e24efb1-8f7d-498a-bd21-79e182b86846
title: String Format Functions
ms.topic: reference
ms.date: 05/31/2018
---

# String Format Functions

Windows GDI+ exposes a flat API that consists of about 600 functions, which are implemented in Gdiplus.dll and declared in Gdiplusflat.h. The functions in the GDI+ flat API are wrapped by a collection of about 40 C++ classes. It is recommended that you do not directly call the functions in the flat API. Whenever you make calls to GDI+, you should do so by calling the methods and functions provided by the C++ wrappers. Microsoft Product Support Services will not provide support for code that calls the flat API directly. For more information on using these wrapper methods, see [GDI+ Flat API](-gdiplus-flatapi-flat.md).

The following flat API functions are wrapped by the [**StringFormat**](/windows/desktop/api/gdiplusstringformat/nl-gdiplusstringformat-stringformat) C++ class.

## StringFormat Functions and Corresponding Wrapper Methods



| Flat function                                                                                                                                                 | Wrapper method                                                                                                                                                                                             | Remarks                                                                                                                                                                                                                                                                                                                                                                                                                   |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| GpStatus WINGDIPAPI GdipCreateStringFormat( INT formatAttributes, LANGID language, GpStringFormat \*\*format )<br/>                                     | [**StringFormat::StringFormat( IN INT formatFlags = 0, IN LANGID language = LANG\_NEUTRAL )**](/windows/win32/api/gdiplusstringformat/nf-gdiplusstringformat-stringformat-stringformat(inint_inlangid))<br/>                              | Creates a [**StringFormat**](/windows/desktop/api/gdiplusstringformat/nl-gdiplusstringformat-stringformat) object based on string format flags and a language.                                                                                                                                                                                                                                                                                                   |
