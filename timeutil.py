"""
أدوات الوقت: كل الحسابات المرتبطة بمواعيد العطاءات بتتم بتوقيت القاهرة،
والـ DST (UTC+2 شتاءً / UTC+3 صيفًا) بيتحدد تلقائيًا من قاعدة بيانات المناطق الزمنية.
"""

from datetime import datetime

import pytz

import constants as C


def cairo_tz():
    return pytz.timezone(C.TIMEZONE)


def cairo_now() -> datetime:
    """الوقت الحالي بتوقيت القاهرة كـ datetime بدون tzinfo (الساعة كما هي على الحائط)."""
    return datetime.now(cairo_tz()).replace(tzinfo=None)
