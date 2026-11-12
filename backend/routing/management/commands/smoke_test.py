"""Live end-to-end check against the real routing and weather APIs.

    python manage.py smoke_test
    python manage.py smoke_test --origin "Dallas, TX" --destination "Houston, TX" --weight 45000 --simulate

Not part of the unit test suite because it needs network access and API quota.
"""
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand, CommandError
from rest_framework.test import APIClient


class Command(BaseCommand):
    help = 'Run one live POST /api/routes/ request and print a summary.'

    def add_arguments(self, parser):
        parser.add_argument('--origin', default='Chicago, IL')
        parser.add_argument('--destination', default='Denver, CO')
        parser.add_argument('--weight', type=float, default=38000)
        parser.add_argument('--interval', default='auto', choices=['auto', '10', '25', '50'])
        parser.add_argument('--simulate', action='store_true')

    def handle(self, *args, **opts):
        departure = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        started = datetime.now()
        resp = APIClient().post('/api/routes/', {
            'origin': opts['origin'],
            'destination': opts['destination'],
            'departure_time': departure.isoformat(),
            'load_weight': opts['weight'],
            'checkpoint_interval': opts['interval'],
            'simulate_weather': opts['simulate'],
        }, format='json', SERVER_NAME='localhost')
        elapsed = (datetime.now() - started).total_seconds()

        if resp.status_code != 200:
            raise CommandError(f'HTTP {resp.status_code}: {resp.data}')

        data = resp.data
        meta = data['meta']
        self.stdout.write(f"{len(data['routes'])} routes via {meta['provider']} in {elapsed:.1f}s, "
                          f"interval {meta['checkpoint_interval_miles']} mi")
        for r in data['routes']:
            s = r['risk_summary']
            miles = {k: v for k, v in s['risk_miles'].items() if v}
            flag = '  [RECOMMENDED]' if r['recommended'] else ''
            self.stdout.write(f"  #{r['rank']} {r['name']}: {r['distance_miles']} mi, {r['duration_display']}, "
                              f"{len(r['checkpoints'])} checkpoints, avg risk {s['avg_risk_score']}, {miles}{flag}")
        hm = data['heatmap']
        available = sum(1 for h in hm['hours'] if h['available'])
        self.stdout.write(f"Heatmap: {len(hm['points'])} grid points, {available}/{len(hm['hours'])} hourly frames available")
        for notice in meta['notices']:
            self.stdout.write(self.style.WARNING(f'Notice: {notice}'))
        self.stdout.write(self.style.SUCCESS('Smoke test passed.'))
