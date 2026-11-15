"""Date boundaries, upstream constraints, and immutable multi-window sequences."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import archive_client as archive
import server
from test_server import row, URL


class DateSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = patch.object(server, 'CACHE', Path(self.tmp.name))
        self.cache.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        self.client.close()
        self.cache.stop()
        self.tmp.cleanup()

    def test_inclusive_utc_day_and_distinct_cache(self):
        anchor = date(1858, 11, 17).toordinal()
        lower = date(2025, 11, 1).toordinal() - anchor
        sample = [dict(row(i), t_min=lower + offset) for i, offset in enumerate((-.01, 0, .99, 1))]
        with patch.object(archive, 'get_table', return_value=(sample, False)) as query:
            first = self.client.get('/api/observations?ra=1&dec=0&start=2025-11-01&end=2025-11-01').json()
            self.client.get('/api/observations?ra=1&dec=0&start=2025-11-01&end=2025-11-01')
            second = self.client.get('/api/observations?ra=1&dec=0').json()
        self.assertEqual([r['id'] for r in first['observations']], ['1','2'])
        self.assertEqual(first['date_range']['end'], '2025-11-01')
        self.assertAlmostEqual(first['time_span_days'], .99)
        self.assertNotEqual(first['key'], second['key'])
        self.assertEqual(query.call_count, 2 * len(archive.COLLECTIONS))
        self.assertEqual(query.call_args_list[0].kwargs['time_range'], (lower, lower + 1))

    def test_invalid_dates_do_not_query_archive(self):
        with patch.object(archive, 'search') as query:
            for extra in ('start=2025-02-30', 'end=garbage', 'start=2025-11-02&end=2025-11-01'):
                self.assertIn(self.client.get('/api/observations?ra=1&dec=0&' + extra).status_code, (400,422))
            query.assert_not_called()

    def test_one_sided_range_uses_vo_infinity(self):
        self.assertEqual(archive.time_constraints((None,61000)), {'TIME':'-Inf 61000'})
        self.assertEqual(archive.time_constraints((61000,None)), {'TIME':'61000 +Inf'})
        self.assertEqual(archive.time_constraints(None), {})
        for limits in ((float('nan'),None),(4,3),(3,3)):
            with self.assertRaises(archive.ArchiveError):
                archive.time_constraints(limits)

    def test_sia_receives_time_before_cap(self):
        raw = b'access_url,energy_bandpassname,t_min\n'
        with patch.object(archive,'fetch_bytes',return_value=raw) as fetch:
            archive.get_table(1,0,.01,'spherex_dr1',detector='D2',time_range=(61000,61100))
        params = parse_qs(urlparse(fetch.call_args.args[0]).query)
        self.assertEqual(params['TIME'], ['61000 61100'])
        self.assertEqual(params['MAXREC'], ['16'])

    def test_tap_receives_and_enforces_same_date_range(self):
        raw = f'uri,time_bounds_lower,energy_bandpassname\n{URL},60999,SPHEREx-D2\n{URL},61001,SPHEREx-D2\n'.encode()
        with patch.object(archive,'fetch_bytes',return_value=raw) as fetch:
            rows, _ = archive.tap_rows(1,0,'D2',time_range=(61000,61100))
        query = fetch.call_args.args[1]['QUERY']
        self.assertIn('p.time_bounds_lower >= 61000',query)
        self.assertIn('p.time_bounds_lower < 61100',query)
        self.assertEqual([r['mjd'] for r in rows],[61001.])

    def test_combined_windows_deduplicate_sort_and_keep_original_snapshot(self):
        with patch.object(archive,'get_table',return_value=([row(5),row(6)],False)):
            base = self.client.get('/api/observations?ra=1&dec=0').json()
        with patch.object(archive,'get_table',return_value=([row(2),row(5)],False)):
            extra = self.client.get('/api/observations',params={'ra':1,'dec':0,'start':'2025-01-01','append':base['key']}).json()
        self.assertEqual([r['id'] for r in extra['observations']],['2','5','6'])
        self.assertEqual(extra['time_span_days'],4)
        self.assertEqual(len(extra['search_windows']),2)
        self.assertNotEqual(extra['key'],base['key'])
        self.assertEqual([r['id'] for r in server.read_search(base['key'])['observations']],['5','6'])
        self.assertNotIn('url',extra['observations'][0])

    def test_append_cached_result_still_preserves_both_windows(self):
        with patch.object(archive,'get_table',return_value=([row(0)],False)) as query:
            base = self.client.get('/api/observations?ra=1&dec=0').json()
            merged = self.client.get('/api/observations',params={'ra':1,'dec':0,'append':base['key']}).json()
        self.assertEqual(query.call_count,len(archive.COLLECTIONS))
        self.assertEqual(merged['total'],1)
        self.assertEqual(len(merged['search_windows']),2)

    def test_cannot_append_other_coordinates_or_detector(self):
        with patch.object(archive,'get_table',return_value=([row(0)],False)):
            base = self.client.get('/api/observations?ra=1&dec=0').json()
        with patch.object(archive,'search') as query:
            for extra in ({'ra':2,'dec':0},{'ra':1,'dec':0,'detector':'D6'},{'ra':1,'dec':0,'fov':6}):
                self.assertEqual(self.client.get('/api/observations',params={**extra,'append':base['key']}).status_code,400)
            query.assert_not_called()

    def test_combined_cap_retains_first_and_last_and_reports_sampling(self):
        rows = [{'id':str(i),'mjd':float(i),'band':'SPHEREx-D2','url':URL.replace('example',str(i))} for i in range(90)]
        base = {'key':'a'*24,'observations':rows[:45],'warnings':[],'collections':['spherex_dr1'],'search_method':'SIA2'}
        extra = {**base,'key':'b'*24,'observations':rows[45:]}
        merged = server.combined_search(base,extra)
        self.assertEqual(len(merged['observations']),64)
        self.assertEqual((merged['observations'][0]['id'],merged['observations'][-1]['id']),('0','89'))
        self.assertTrue(merged['sampling_limited'])
        self.assertTrue(merged['total_lower_bound'])

    def test_original_download_redirect_has_fixed_irsa_origin(self):
        with patch.object(archive,'get_table',return_value=([row(0)],False)):
            data = self.client.get('/api/observations?ra=1&dec=0').json()
        response = self.client.get(f"/api/cutout/{data['key']}/0",follow_redirects=False)
        self.assertEqual(response.status_code,307)
        url = urlparse(response.headers['location'])
        self.assertEqual(url.netloc,'irsa.ipac.caltech.edu')
        self.assertEqual(parse_qs(url.query)['center'],['1.00000000,0.00000000d'])
        self.assertEqual(self.client.get(f"/api/cutout/{data['key']}/-1").status_code,404)


if __name__ == '__main__':
    unittest.main()
