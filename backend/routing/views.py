import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services.corridor_service import build_corridor_grid, fetch_corridor_heatmap
from .services.errors import RoutingInputError, UpstreamServiceError
from .services.recommend_service import recommend_routes
from .services.risk_service import calculate_risk_for_route
from .services.route_service import get_routes_with_checkpoints
from .services.simulation_service import (
    StormField,
    simulate_corridor_heatmap,
    simulate_weather_for_routes,
)
from .services.weather_service import fetch_weather_for_routes, forecast_horizon, to_utc_naive

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """Lightweight liveness endpoint for deployment health checks."""

    def get(self, request):
        return Response({'status': 'ok'})


class CalculateRoutesView(APIView):
    """POST /api/routes/ -> ranked routes with checkpoint risk, plus the 0-48 h corridor heatmap."""

    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            return Response(self._calculate(serializer.validated_data))
        except RoutingInputError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except UpstreamServiceError as exc:
            logger.error('Upstream service failure: %s', exc)
            return Response(
                {'error': 'A routing or weather service is unavailable right now. Please try again shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    def _calculate(self, data):
        departure = data['departure_time']
        load_weight = data['load_weight']
        simulate = data['simulate_weather']

        routes, meta = get_routes_with_checkpoints(
            origin=data['origin'],
            destination=data['destination'],
            departure_time=departure,
            interval=data['checkpoint_interval'],
        )

        if not simulate:
            arrival = max(to_utc_naive(r['checkpoints'][-1]['eta']) for r in routes)
            horizon = forecast_horizon()
            if arrival > horizon:
                raise RoutingInputError(
                    f'This trip would arrive around {arrival:%b %d, %H:%M} UTC, after the forecast '
                    f'ends ({horizon:%b %d, %H:00} UTC). Choose an earlier departure.'
                )

        grid, spacing = build_corridor_grid(routes)

        if simulate:
            field = StormField.for_routes(routes, departure)
            simulate_weather_for_routes(routes, field)
            heatmap = simulate_corridor_heatmap(grid, spacing, departure, load_weight, field)
        else:
            # Checkpoint weather and the 0-48 h heatmap window are independent lookups: run them together
            with ThreadPoolExecutor(max_workers=2) as pool:
                checkpoint_job = pool.submit(fetch_weather_for_routes, routes)
                heatmap_job = pool.submit(fetch_corridor_heatmap, grid, spacing, departure, load_weight)
                checkpoint_job.result()
                heatmap = heatmap_job.result()

        for route in routes:
            route['checkpoints'], route['risk_summary'] = calculate_risk_for_route(
                route['checkpoints'], load_weight,
            )
        routes = recommend_routes(routes)

        notices = list(meta['notices'])
        unknown = [r['name'] for r in routes if r['risk_summary']['has_unknown']]
        if unknown:
            notices.append(
                'Weather data could not be retrieved for some checkpoints on '
                + ', '.join(unknown)
                + '. Those stretches are shown as Unknown, and the route is ranked below routes with complete data.'
            )
        if simulate:
            notices.append('Simulated storm scenario: the weather shown is synthetic, for demonstration only.')

        return {
            'routes': routes,
            'heatmap': heatmap,
            'meta': {
                **meta,
                'notices': notices,
                'simulated': simulate,
                'departure_time': departure.astimezone(timezone.utc).isoformat(),
                'load_weight': load_weight,
            },
        }
