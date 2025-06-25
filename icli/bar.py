from dataclasses import dataclass, field
from datetime import datetime, timedelta
from loguru import logger

@dataclass
class OHLC5MinTracker:
    def __init__(self):
        self.previous_bar = None
        self.current_bar = None
        self.current_interval_start = None
        self.skip_until = None

    def _align_to_5min(self, dt: datetime) -> datetime:
        return dt.replace(minute=dt.minute - dt.minute % 5, second=0, microsecond=0)
        # #return dt - timedelta(
        #     minutes=dt.minute % 5,
        #     seconds=0,
        #     microseconds=0
        # )

    def update(self, tick_time: datetime, tick_price: float):
        aligned_time = self._align_to_5min(tick_time)

        if self.skip_until is None:
            self.skip_until = aligned_time + timedelta(minutes=5)
            return

        # Don't build bars until we hit a clean interval after the first tick
        if aligned_time < self.skip_until:
            return

        if aligned_time != self.current_interval_start:
            if self.current_bar:
                self.previous_bar = self.current_bar
            self.current_interval_start = aligned_time
            self.current_bar = {
                'timestamp': aligned_time,
                'open': tick_price,
                'high': tick_price,
                'low': tick_price,
                'close': tick_price
            }
        else:
            self.current_bar['high'] = max(self.current_bar['high'], tick_price)
            self.current_bar['low'] = min(self.current_bar['low'], tick_price)
            self.current_bar['close'] = tick_price

    def get_current_bar(self):
        return self.current_bar

    def get_previous_bar(self):
        return self.previous_bar

    def __repr__(self):
        return f"Current: {self.current_bar}, Previous: {self.previous_bar}"
