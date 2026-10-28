from datetime import datetime
from zoneinfo import ZoneInfo

def as_resort_local(moment: datetime, resort_tz: ZoneInfo) -> datetime:
    """Read a naive datetime as resort local time; leave an aware one as it is."""
    return moment.replace(tzinfo=resort_tz) if moment.tzinfo is None else moment
