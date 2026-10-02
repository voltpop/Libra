# lb_dt.py - calendar arithmetic on Unix time, pure integer maths (no time module, any port)
#
# Used by the Set time page and the console. UTC only: TOTP runs on UTC and the device has no
# time-zone database. Valid for 1970..2399.

_DIM = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def days_in_month(y, m):
    return 29 if m == 2 and is_leap(y) else _DIM[m - 1]


def to_fields(u):
    """Unix seconds -> [year, month, day, hour, minute, second] (UTC)."""
    days, rem = divmod(u, 86400)
    z = days + 719468  # days since 0000-03-01
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    if m <= 2:
        y += 1
    return [y, m, d, rem // 3600, (rem // 60) % 60, rem % 60]


def to_unix(y, m, d, hh=0, mm=0, ss=0):
    """The inverse of to_fields. Raises ValueError for an impossible date or time."""
    if not (1970 <= y <= 2399 and 1 <= m <= 12 and 1 <= d <= days_in_month(y, m)
            and 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise ValueError("not a valid date and time")
    y2 = y - 1 if m <= 2 else y
    era = y2 // 400
    yoe = y2 - era * 400
    mp = m - 3 if m > 2 else m + 9
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    return days * 86400 + hh * 3600 + mm * 60 + ss


def text(u):
    f = to_fields(u)
    return "%04d-%02d-%02d %02d:%02d:%02d" % tuple(f)
