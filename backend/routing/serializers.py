from datetime import datetime, timedelta, timezone

from rest_framework import serializers

from .services.weather_service import forecast_horizon

PAST_DEPARTURE_GRACE = timedelta(hours=1)


class RouteRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=255)
    destination = serializers.CharField(max_length=255)
    departure_time = serializers.DateTimeField()
    load_weight = serializers.FloatField(min_value=0, max_value=200000)
    checkpoint_interval = serializers.ChoiceField(
        choices=['auto', '10', '25', '50'], required=False, default='auto',
    )
    simulate_weather = serializers.BooleanField(required=False, default=False)

    def validate_departure_time(self, value):
        now = datetime.now(timezone.utc)
        if value < now - PAST_DEPARTURE_GRACE:
            raise serializers.ValidationError('Departure time is in the past.')
        horizon = forecast_horizon(now).replace(tzinfo=timezone.utc)
        if value > horizon:
            raise serializers.ValidationError(
                f'Weather forecasts are only available until {horizon:%b %d, %H:00} UTC. '
                'Choose an earlier departure.'
            )
        return value
