from __future__ import annotations

from datetime import time

from flask import has_request_context, request


def _format_hour_label(hour_value: int) -> str:
    suffix = "AM" if hour_value < 12 else "PM"
    display_hour = hour_value % 12 or 12
    return f"{display_hour} {suffix}"


HOUR_CHOICES = [("", "Hour"), *[(str(hour_value), _format_hour_label(hour_value)) for hour_value in range(24)]]
MINUTE_CHOICES = [("", "Minute"), *[(str(minute_value), f"{minute_value:02d}") for minute_value in range(0, 60, 5)]]


class TimeSelectMixin:
    TIME_FIELD_CONFIG: dict[str, dict[str, object]] = {}

    def _initialize_time_selects(self, *, source: object | None = None) -> None:
        preserve_submitted_values = has_request_context() and request.method in {"POST", "PUT", "PATCH"}
        for field_name in self.TIME_FIELD_CONFIG:
            hour_field = getattr(self, f"{field_name}_hour")
            minute_field = getattr(self, f"{field_name}_minute")
            hour_field.choices = HOUR_CHOICES
            minute_field.choices = MINUTE_CHOICES
            if not preserve_submitted_values and source is not None:
                self._set_time_field_data(field_name, getattr(source, field_name, None))

    def _set_time_field_data(self, field_name: str, value: time | None) -> None:
        hour_field = getattr(self, f"{field_name}_hour")
        minute_field = getattr(self, f"{field_name}_minute")
        if value is None:
            hour_field.data = ""
            minute_field.data = ""
            return

        hour_field.data = str(value.hour)
        minute_field.data = str(value.minute)

    def time_value(self, field_name: str) -> time | None:
        hour_value = getattr(self, f"{field_name}_hour").data
        minute_value = getattr(self, f"{field_name}_minute").data

        if hour_value in (None, "") and minute_value in (None, ""):
            return None

        if hour_value in (None, "") or minute_value in (None, ""):
            raise ValueError(field_name)

        return time(hour=int(hour_value), minute=int(minute_value))

    def validate_time_selects(self) -> bool:
        is_valid = True
        for field_name, config in self.TIME_FIELD_CONFIG.items():
            label = str(config.get("label", field_name.replace("_", " ")))
            required = bool(config.get("required", False))
            hour_field = getattr(self, f"{field_name}_hour")
            minute_field = getattr(self, f"{field_name}_minute")
            hour_value = hour_field.data
            minute_value = minute_field.data

            if hour_value in (None, "") and minute_value in (None, ""):
                if required:
                    hour_field.errors.append(f"Choose a {label}.")
                    is_valid = False
                continue

            if hour_value in (None, "") or minute_value in (None, ""):
                hour_field.errors.append(f"Choose both the hour and minutes for {label}.")
                is_valid = False
                continue

            try:
                hour_number = int(hour_value)
                minute_number = int(minute_value)
            except (TypeError, ValueError):
                hour_field.errors.append(f"Choose a valid {label}.")
                is_valid = False
                continue

            if hour_number < 0 or hour_number > 23 or minute_number not in range(0, 60, 5):
                hour_field.errors.append(f"Choose a valid {label}.")
                is_valid = False

        return is_valid
