# lb_settings.py - device settings, with approval needed to weaken protection
#
# store: load() -> dict or raises; save(dict) durable on return, raises on failure.
# A missing or corrupt store falls back to the defaults, and the defaults are the strict ones.
#
# push_to_show: every OTP code is hidden until PTT is held, and hides again on release.
# Turning it ON is free; turning it OFF weakens protection, so set() needs approved=True
# (the UI gets that from a hold on a confirm screen).

# utc_offset_min: minutes east of UTC for display and for typing a time in (the clock itself stays
# UTC, which is what TOTP uses). 15-minute steps, -12:00 to +14:00. No daylight-saving rules:
# change it by hand.
DEFAULTS = {"push_to_show": True, "utc_offset_min": 0}
OFFSET_MIN = -720
OFFSET_MAX = 840


def _valid(name, value):
    if name == "utc_offset_min":
        return OFFSET_MIN <= value <= OFFSET_MAX and value % 15 == 0
    return True

# name -> function(old, new) that is True when the change makes the device less protected
_WEAKENING = {"push_to_show": lambda old, new: bool(old) and not new}


class SettingsError(Exception):
    pass


class UnknownSetting(SettingsError):
    pass


class InvalidSetting(SettingsError):
    pass


class ApprovalRequired(SettingsError):
    pass


class StorageError(SettingsError):
    pass


class Settings:
    def __init__(self, store=None):
        self._v = dict(DEFAULTS)
        self._store = store
        if store is not None:
            try:
                saved = store.load()
            except Exception:
                saved = None
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in DEFAULTS and type(v) is type(DEFAULTS[k]) and _valid(k, v):
                        self._v[k] = v  # anything unknown or mistyped is ignored

    def get(self, name):
        try:
            return self._v[name]
        except KeyError:
            raise UnknownSetting(name)

    def all(self):
        return dict(self._v)

    def set(self, name, value, approved=False):
        if name not in DEFAULTS:
            raise UnknownSetting(name)
        if type(value) is not type(DEFAULTS[name]):
            raise InvalidSetting("%s must be a %s" % (name, type(DEFAULTS[name]).__name__))
        if not _valid(name, value):
            raise InvalidSetting("%s out of range" % name)
        old = self._v[name]
        weaken = _WEAKENING.get(name)
        if weaken is not None and weaken(old, value) and not approved:
            raise ApprovalRequired(name)
        if old == value:
            return
        self._v[name] = value
        if self._store is not None:
            try:
                self._store.save(dict(self._v))
            except Exception:
                self._v[name] = old
                raise StorageError("settings not saved")
