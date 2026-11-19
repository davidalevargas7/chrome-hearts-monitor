import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import ww_slots_monitor as monitor


class TimezoneTests(unittest.TestCase):
    def load(self, api_timezone, override=""):
        with patch.object(monitor, "TIMEZONE", override), \
             patch.object(monitor, "get_json", return_value={
                 "name": "Chrome Hearts - Las Vegas Fontainebleau",
                 "timeZone": api_timezone,
             }):
            return monitor.load_location(None)[1]

    def test_override_wins_over_null_or_conflicting_api_timezone(self):
        for api_timezone in (None, "America/New_York"):
            with self.subTest(api_timezone=api_timezone):
                self.assertEqual(self.load(api_timezone, "America/Los_Angeles").key,
                                 "America/Los_Angeles")

    def test_without_override_preserves_api_and_new_york_fallback(self):
        for api_timezone, expected in ((None, "America/New_York"),
                                       ("America/Chicago", "America/Chicago"),
                                       ("invalid", "America/New_York")):
            with self.subTest(api_timezone=api_timezone):
                self.assertEqual(self.load(api_timezone).key, expected)

    def test_override_survives_location_api_failure(self):
        with patch.object(monitor, "TIMEZONE", "America/Los_Angeles"), \
             patch.object(monitor, "get_json", return_value=None):
            self.assertEqual(monitor.load_location(None)[1].key, "America/Los_Angeles")

    def test_pacific_slot_two_hours_from_now_is_kept(self):
        # 18:00 UTC is 10:00 PST / 11:00 PDT, but 13:00 EST / 14:00 EDT.
        for month, slot_date in ((11, "2026-11-19T12:00"),
                                 (7, "2026-07-19T13:00")):
            with self.subTest(month=month):
                fixed_now = datetime(2026, month, 19, 18, tzinfo=timezone.utc)

                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return fixed_now.astimezone(tz)

                slots = [{"date": slot_date, "numAvailableSpots": 1}]
                tz = self.load(None, "America/Los_Angeles")
                with patch.object(monitor, "datetime", Clock), \
                     patch.object(monitor, "SERVICE_FILTER", []):
                    self.assertIn(slot_date, monitor.open_slots(slots, {}, tz))
                    self.assertEqual(monitor.open_slots(
                        slots, {}, ZoneInfo("America/New_York")), {})

    def test_alert_labels_pacific_standard_and_daylight_time(self):
        tz = self.load(None, "America/Los_Angeles")
        for date, label in (("2026-11-19T12:00", "PST"),
                            ("2026-07-19T12:00", "PDT")):
            with self.subTest(label=label):
                alert = monitor.build_alert(
                    {date: {"avail": 1}}, "Chrome Hearts - Las Vegas Fontainebleau", tz)
                self.assertIn(f"12:00 PM {label}", alert)

    def test_honolulu_slot_two_hours_from_now_is_kept_and_alerted_in_hst(self):
        # Hawaii stays UTC-10 in both winter and summer, unlike New York.
        for month in (11, 7):
            with self.subTest(month=month):
                fixed_now = datetime(2026, month, 19, 19, tzinfo=timezone.utc)
                slot_date = f"2026-{month:02d}-19T11:00"

                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return fixed_now.astimezone(tz)

                with patch.object(monitor, "TIMEZONE", "Pacific/Honolulu"), \
                     patch.object(monitor, "get_json", return_value={
                         "name": "Chrome Hearts - Honolulu", "timeZone": None}):
                    services, tz, name = monitor.load_location(None)
                self.assertEqual(tz.key, "Pacific/Honolulu")
                self.assertEqual(fixed_now.astimezone(tz).strftime("%H:%M %Z"), "09:00 HST")
                slots = [{"date": slot_date, "numAvailableSpots": 1}]
                with patch.object(monitor, "datetime", Clock), \
                     patch.object(monitor, "SERVICE_FILTER", []):
                    current = monitor.open_slots(slots, services, tz)
                    self.assertIn(slot_date, current)
                    self.assertEqual(monitor.open_slots(
                        slots, services, ZoneInfo("America/New_York")), {})
                alert = monitor.build_alert(current, name, tz)
                self.assertIn("Chrome Hearts - Honolulu", alert)
                self.assertIn("11:00 AM HST", alert)


if __name__ == "__main__":
    unittest.main()
