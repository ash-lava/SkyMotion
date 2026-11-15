"""Offline regression tests: python -m unittest -v test_server.py"""
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
import archive_client as archive
import server
URL='https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/example.fits'
def row(i=0,band='SPHEREx-D2'):
    return {'obs_id':str(i),'energy_bandpassname':band,'access_url':URL.replace('example',str(i)),
            't_min':61000.+i,'em_min':1.1e-6,'em_max':1.6e-6,'t_exptime':112.}
class ArchiveTests(unittest.TestCase):
    def test_http_200_can_be_vo_error(self):
        with self.assertRaises(archive.ArchiveError):
            archive.validate_votable(b'<VOTABLE><RESOURCE><INFO name="QUERY_STATUS" value="ERROR">Bad collection</INFO><TABLE/></RESOURCE></VOTABLE>')
    def test_valid_empty_and_overflow(self):
        self.assertFalse(archive.validate_votable(b'<VOTABLE><RESOURCE><TABLE/></RESOURCE></VOTABLE>'))
        self.assertTrue(archive.validate_votable(b'<VOTABLE><RESOURCE><TABLE/><INFO name="QUERY_STATUS" value="OVERFLOW"/></RESOURCE></VOTABLE>'))
    def test_html_or_missing_table_is_failure(self):
        for body in (b'not XML',b'<html><body>Proxy Error</body></html>'):
            with self.subTest(body=body),self.assertRaises(archive.ArchiveError):archive.validate_votable(body)
    def test_url_allowlist(self):
        self.assertTrue(archive.safe_image_url(URL))
        for url in ('http://irsa.ipac.caltech.edu/ibe/data/spherex/x','https://example.org/x','https://irsa.ipac.caltech.edu.evil.test/ibe/data/spherex/x','https://irsa.ipac.caltech.edu/private','https://user@irsa.ipac.caltech.edu/ibe/data/spherex/x'):
            self.assertFalse(archive.safe_image_url(url))
    def test_filter_sort_deduplicate_and_sample(self):
        table=[row(i) for i in reversed(range(10))]+[row(4),row(12,'SPHEREx-D4')]
        with patch.object(archive,'get_table',return_value=(table,False)),patch.object(archive,'COLLECTIONS',('spherex_dr1',)):
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4)
        self.assertEqual(total,10);self.assertEqual([r['id'] for r in rows],['0','3','6','9']);self.assertEqual(live,['spherex_dr1']);self.assertEqual(warnings,[])
    def test_partial_outage_keeps_working_collection(self):
        def table(ra,dec,radius,collection):
            if collection=='spherex_qr3':raise archive.ArchiveError('HTTP 502')
            return [row()],False
        with patch.object(archive,'get_table',side_effect=table),patch.object(archive,'COLLECTIONS',('spherex_dr1','spherex_qr3')),patch.object(archive,'tap_rows',side_effect=archive.ArchiveError('TAP unavailable')):
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4)
        self.assertEqual(total,1);self.assertEqual(live,['spherex_dr1']);self.assertIn('spherex_qr3',failed);self.assertTrue(warnings)
    def test_all_failed_is_not_empty_success(self):
        with patch.object(archive,'get_table',side_effect=archive.ArchiveError('502')),patch.object(archive,'tap_rows',side_effect=archive.ArchiveError('502')),self.assertRaises(archive.ArchiveError):archive.search(12,3,.1,'D2',4)
    def test_empty_is_valid_success(self):
        with patch.object(archive,'get_table',return_value=([],False)):rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4)
        self.assertEqual(rows,[]);self.assertTrue(live)
    def test_retry_502_then_succeed(self):
        calls=[]
        def handler(request):
            calls.append(request);return httpx.Response(502 if len(calls)==1 else 200,content=b'ok',request=request)
        real=httpx.Client
        with patch.object(archive.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)),patch.object(archive.time,'sleep'):
            self.assertEqual(archive.fetch_bytes('https://irsa.ipac.caltech.edu/SIA'),b'ok')
        self.assertEqual(len(calls),2)
    def test_404_not_retried(self):
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(404,request=request)
        real=httpx.Client
        with patch.object(archive.httpx,'Client',side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)),self.assertRaises(archive.ArchiveError):archive.fetch_bytes('https://irsa.ipac.caltech.edu/SIA')
        self.assertEqual(len(calls),1)
    def test_download_size_bounded(self):
        real=httpx.Client
        transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'123456789',request=request))
        with patch.object(archive.httpx,'Client',side_effect=lambda **kw:real(transport=transport,**kw)),self.assertRaises(archive.ArchiveError):archive.fetch_bytes(URL,max_bytes=4)
class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cache=patch.object(server,'CACHE',Path(self.tmp.name));self.cache.start();self.client=TestClient(server.app)
        self.status=patch.dict(server.STATUS,{'checked':None,'live':[],'unavailable':{}},clear=True);self.status.start()
    def tearDown(self):self.client.close();self.status.stop();self.cache.stop();self.tmp.cleanup()
    def test_health_and_archive_do_not_probe(self):
        with patch.object(archive,'get_table') as probe:
            self.assertEqual(self.client.get('/api/health').json()['version'],'2.0.2');self.assertEqual(self.client.get('/api/archive').json()['status'],'unchecked');probe.assert_not_called()
    def test_coordinate_validation_and_resolution(self):
        for query in ('ra=360&dec=0','ra=0&dec=91','ra=nan&dec=0','ra=0&dec=0&fov=90'):self.assertEqual(self.client.get('/api/observations?'+query).status_code,422)
        self.assertEqual(self.client.get('/api/resolve',params={'q':'133.79513, -7.24515'}).json()['ra'],133.79513)
        self.assertEqual(self.client.get('/api/resolve',params={'q':'400, -7'}).status_code,400)
        self.assertEqual(self.client.get('/api/observations?ra=1&dec=0&detector=D9').status_code,400)
    def test_cache_and_private_urls(self):
        with patch.object(archive,'get_table',return_value=([row()],False)) as query:
            first=self.client.get('/api/observations?ra=1&dec=0').json();second=self.client.get('/api/observations?ra=1&dec=0').json()
        self.assertEqual(query.call_count,len(archive.COLLECTIONS));self.assertEqual(first,second)
        self.assertNotIn('url',first['observations'][0]);self.assertIn('url',server.read_search(first['key'])['observations'][0])
    def test_failure_status_and_not_cached(self):
        with patch.object(archive,'search',side_effect=archive.ArchiveError('temporarily unreachable')):result=self.client.get('/api/observations?ra=1&dec=0')
        self.assertEqual(result.status_code,503);self.assertEqual(result.headers['retry-after'],'30');self.assertEqual(list(server.CACHE.glob('*.json')),[])
        self.assertEqual(self.client.get('/api/archive').json()['status'],'unavailable')
    def test_empty_success_cached(self):
        with patch.object(archive,'get_table',return_value=([],False)):result=self.client.get('/api/observations?ra=1&dec=0')
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['total'],0);self.assertTrue(list(server.CACHE.glob('*.json')))
    def test_refresh_queries_again(self):
        with patch.object(archive,'get_table',return_value=([row()],False)) as query:
            self.client.get('/api/observations?ra=1&dec=0');self.client.get('/api/observations?ra=1&dec=0&refresh=true')
        self.assertEqual(query.call_count,2*len(archive.COLLECTIONS))
    def test_partial_response_retried(self):
        with patch.object(archive,'search',return_value=([{'url':URL,'id':'1'}],1,['partial'],['spherex_dr1'],{'spherex_qr3':'502'})) as query:
            self.client.get('/api/observations?ra=1&dec=0');self.client.get('/api/observations?ra=1&dec=0')
        self.assertEqual(query.call_count,2)
    def test_invalid_and_expired_key(self):
        self.assertEqual(self.client.get('/api/frame/bad/0.png').status_code,400);self.assertEqual(self.client.get('/api/frame/'+'a'*24+'/0.png').status_code,404)
        self.assertEqual(self.client.get('/api/photometry/bad').status_code,400)
    def test_failed_image_not_fake(self):
        with patch.object(server,'image_data',side_effect=archive.ArchiveError('Image unavailable')):result=self.client.get('/api/frame/'+'a'*24+'/0.png')
        self.assertEqual(result.status_code,502);self.assertIn('Image unavailable',result.json()['detail'])
    def test_png_orientation_and_cache_headers(self):
        array=np.tile(np.arange(20,dtype=float)[:,None],(1,20))
        with patch.object(server,'get_image',return_value=(array,{},None,{})):result=self.client.get('/api/frame/'+'a'*24+'/0.png')
        pixels=np.asarray(Image.open(io.BytesIO(result.content)));self.assertGreater(pixels[0,10],pixels[-1,10]);self.assertEqual(result.headers['cache-control'],'no-store')
    def test_only_frontend_assets_public(self):
        for path in ('/','/static/app.js','/static/style.css','/static/vendor/htm.js'):self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.client.get('/static/server.py').status_code,404);self.assertEqual(self.client.get('/static/archive_client.py').status_code,404)
class SkyServiceTests(unittest.TestCase):
    def setUp(self):
        import sky_service
        self.sky=sky_service;self.sky.CACHE.clear();self.client=TestClient(server.app)
        image=Image.new('RGB',(64,64),(20,30,40));buffer=io.BytesIO();image.save(buffer,format='JPEG');self.jpeg=buffer.getvalue()
    def tearDown(self):self.client.close();self.sky.CACHE.clear()
    def test_valid_survey_image_and_cache(self):
        with patch.object(archive,'fetch_bytes',return_value=self.jpeg) as fetch:
            first=self.client.get('/api/sky.jpg?ra=83.8&dec=-5.3&width=64&height=64')
            second=self.client.get('/api/sky.jpg?ra=83.8&dec=-5.3&width=64&height=64')
        self.assertEqual(first.status_code,200);self.assertEqual(first.headers['content-type'],'image/jpeg')
        self.assertEqual(first.content,second.content);self.assertEqual(fetch.call_count,1)
        self.assertEqual(first.headers['x-sky-source'],'CDS/P/DSS2/color')
    def test_automatic_second_endpoint(self):
        with patch.object(archive,'fetch_bytes',side_effect=[archive.ArchiveError('HTTP 502'),self.jpeg]) as fetch:
            result=self.client.get('/api/sky.jpg?ra=1&dec=0&width=64&height=64')
        self.assertEqual(result.status_code,200);self.assertEqual(fetch.call_count,2)
        self.assertIn('alaskybis',fetch.call_args_list[1].args[0])
    def test_both_endpoints_fail_with_useful_error(self):
        with patch.object(archive,'fetch_bytes',side_effect=archive.ArchiveError('HTTP 502')):
            result=self.client.get('/api/sky.jpg?ra=1&dec=0&width=64&height=64')
        self.assertEqual(result.status_code,503);self.assertEqual(result.json()['detail']['code'],'SKY_SURVEY_UNAVAILABLE')
        self.assertEqual(len(result.json()['detail']['upstream']),2);self.assertFalse(self.sky.CACHE)
    def test_html_is_not_cached_as_an_image(self):
        with patch.object(archive,'fetch_bytes',return_value=b'<html>Proxy error</html>'):
            result=self.client.get('/api/sky.jpg?ra=1&dec=0&width=64&height=64')
        self.assertEqual(result.status_code,503);self.assertFalse(self.sky.CACHE)
    def test_bad_parameters_do_not_contact_upstream(self):
        with patch.object(archive,'fetch_bytes') as fetch:
            for suffix in ('ra=360&dec=0','ra=1&dec=99','ra=1&dec=0&width=10000','ra=1&dec=0&fov=180'):
                self.assertEqual(self.client.get('/api/sky.jpg?'+suffix).status_code,422)
            self.assertEqual(self.client.get('/api/sky.jpg?ra=1&dec=0&survey=https://example.com').status_code,400)
            fetch.assert_not_called()
    def test_wcs_center_scale_and_orientation(self):
        import math
        wcs=self.sky.image_wcs(359.9,89,10,1000,500)
        self.assertEqual(wcs['CRPIX1'],500.5);self.assertEqual(wcs['CRPIX2'],250.5)
        self.assertEqual(wcs['CRVAL1'],359.9);self.assertLess(wcs['CDELT1'],0);self.assertGreater(wcs['CDELT2'],0)
        self.assertAlmostEqual(math.degrees(2*math.atan(math.radians(wcs['CDELT2'])*1000/2)),10)
    def test_local_fallback_script_is_served(self):
        result=self.client.get('/static/sky-atlas.js');self.assertEqual(result.status_code,200)
        self.assertIn('pixelToSky',result.text)
    def test_size_mismatch_is_rejected(self):
        with patch.object(archive,'fetch_bytes',return_value=self.jpeg):
            result=self.client.get('/api/sky.jpg?ra=1&dec=0&width=128&height=128')
        self.assertEqual(result.status_code,503)

@unittest.skipUnless(importlib.util.find_spec('astropy'),'Astropy is not installed in this test environment')
class AstronomyTests(unittest.TestCase):
    def test_wcs_rotation_alignment(self):
        destination=server.target_wcs(359.99,22,3);source=destination.deepcopy();angle=np.deg2rad(37)
        source.wcs.pc=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        sky=destination.pixel_to_world(91,110);x,y=source.world_to_pixel(sky);yy,xx=np.indices((server.SIZE,server.SIZE));raw=np.exp(-((xx-x)**2+(yy-y)**2)/6)
        aligned=server.align_array(raw,source,destination);actual=np.unravel_index(np.nanargmax(aligned),aligned.shape)
        self.assertLessEqual(abs(actual[0]-110),1);self.assertLessEqual(abs(actual[1]-91),1)
    def test_sexagesimal_challenge_position(self):
        result=server.resolve('08h55m10.831s -07d14m42.53s');self.assertAlmostEqual(result['ra'],133.7951292,places=6);self.assertAlmostEqual(result['dec'],-7.2451472,places=6)
    def test_actual_votable_parse(self):
        from astropy.table import Table
        table=Table(rows=[row()]);buffer=io.BytesIO();table.write(buffer,format='votable')
        with patch.object(archive,'fetch_bytes',return_value=buffer.getvalue()):result,overflow=archive.get_table(1,0,.01,'spherex_dr1')
        self.assertEqual(len(result),1);self.assertFalse(overflow)

class SearchRecoveryTests(unittest.TestCase):
    def test_tap_recovers_all_failed_sia_collections(self):
        diagnostics={}
        fallback={'url':URL,'id':'recovered','band':'SPHEREx-D2','mjd':61000,'collection':'spherex_dr1'}
        with patch.object(archive,'get_table',side_effect=archive.ArchiveError('502')),patch.object(archive,'tap_rows',return_value=([fallback],False)) as tap:
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4,diagnostics=diagnostics)
        self.assertEqual(total,1);self.assertEqual(rows,[fallback]);self.assertEqual(live,[])
        self.assertTrue(failed);self.assertTrue(diagnostics['tap']['ok']);self.assertEqual(diagnostics['method'],'TAP')
        self.assertTrue(any('wide/deep' in w for w in warnings));tap.assert_called_once_with(12,3,'D2')
    def test_working_sia_does_not_need_fallback(self):
        with patch.object(archive,'get_table',return_value=([],False)),patch.object(archive,'tap_rows') as tap:
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4)
        self.assertEqual(rows,[]);self.assertTrue(live);tap.assert_not_called()
    def test_valid_empty_tap_is_distinct_from_an_outage(self):
        diagnostics={}
        with patch.object(archive,'get_table',side_effect=archive.ArchiveError('502')),patch.object(archive,'tap_rows',return_value=([],False)):
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4,diagnostics=diagnostics)
        self.assertEqual(rows,[]);self.assertEqual(total,0);self.assertTrue(diagnostics['tap']['ok'])
    def test_partial_sia_and_tap_artifacts_are_deduplicated(self):
        fallback={'url':URL.replace('example','0'),'id':'0','band':'SPHEREx-D2','mjd':61000,'collection':'spherex_dr1'}
        def table(ra,dec,radius,collection):
            if collection=='spherex_qr3':raise archive.ArchiveError('502')
            return [row()],False
        diagnostics={}
        with patch.object(archive,'COLLECTIONS',('spherex_dr1','spherex_qr3')),patch.object(archive,'get_table',side_effect=table),patch.object(archive,'tap_rows',return_value=([fallback],True)):
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4,diagnostics=diagnostics)
        self.assertEqual(total,1);self.assertEqual(diagnostics['method'],'SIA2 + TAP')
        self.assertTrue(any('10,000' in w for w in warnings))
    def test_url_validation_rejects_traversal_queries_and_bad_ports(self):
        for url in ['https://[broken-address',URL+'?url=https://example.com',URL+'#fragment',URL.replace('/level2/','/level2/../'),URL.replace('example.fits','%2e%2e/secret.fits'),URL.replace('.edu/','.edu:bad/')]:
            with self.subTest(url=url):self.assertFalse(archive.safe_image_url(url))

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cache=patch.object(server,'CACHE',Path(self.tmp.name));self.cache.start();self.client=TestClient(server.app)
        self.status=patch.dict(server.STATUS,{'checked':None,'live':[],'unavailable':{},'tap':None},clear=True);self.status.start()
    def tearDown(self):self.client.close();self.status.stop();self.cache.stop();self.tmp.cleanup()
    def test_refresh_preserves_old_search_frame_mapping(self):
        with patch.object(archive,'get_table',return_value=([row(0)],False)):
            first=self.client.get('/api/observations?ra=1&dec=0').json()
        with patch.object(archive,'get_table',return_value=([row(1)],False)):
            second=self.client.get('/api/observations?ra=1&dec=0&refresh=true').json()
        self.assertNotEqual(first['key'],second['key'])
        self.assertEqual(server.read_search(first['key'])['observations'][0]['id'],'0')
        self.assertEqual(server.read_search(second['key'])['observations'][0]['id'],'1')
        cached=self.client.get('/api/observations?ra=1&dec=0').json();self.assertEqual(cached,second)
    def test_tap_recovery_does_not_claim_sia_is_live(self):
        fallback={'url':URL,'id':'recovered','band':'SPHEREx-D2','mjd':61000,'collection':'spherex_dr1'}
        with patch.object(archive,'get_table',side_effect=archive.ArchiveError('502')),patch.object(archive,'tap_rows',return_value=([fallback],False)):
            response=self.client.get('/api/observations?ra=1&dec=0')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['search_method'],'TAP')
        status=self.client.get('/api/archive').json()
        self.assertEqual(status['status'],'ready');self.assertEqual(status['live'],[]);self.assertTrue(status['tap']['ok'])
    def test_both_search_services_fail_with_structured_error(self):
        with patch.object(archive,'get_table',side_effect=archive.ArchiveError('SIA 502')),patch.object(archive,'tap_rows',side_effect=archive.ArchiveError('TAP 502')):
            response=self.client.get('/api/observations?ra=1&dec=0')
        self.assertEqual(response.status_code,503);self.assertEqual(response.json()['detail']['code'],'SPHEREX_UNAVAILABLE')
        status=self.client.get('/api/archive').json();self.assertFalse(status['tap']['ok']);self.assertFalse(list(server.CACHE.glob('*.json')))
    def test_incomplete_refresh_removes_previous_complete_lookup(self):
        with patch.object(archive,'get_table',return_value=([row(0)],False)):
            self.client.get('/api/observations?ra=1&dec=0')
        with patch.object(archive,'search',return_value=([{'url':URL,'id':'new'}],1,['partial'],[],{})) as search:
            self.client.get('/api/observations?ra=1&dec=0&refresh=true')
            self.client.get('/api/observations?ra=1&dec=0')
        self.assertEqual(search.call_count,2);self.assertFalse(list(server.CACHE.glob('*.ref')))

@unittest.skipUnless(importlib.util.find_spec('astropy'),'Astropy is not installed in this test environment')
class TAPParsingTests(unittest.TestCase):
    def test_tap_normalizes_current_release_and_enforces_family_and_detector(self):
        from astropy.table import Table
        urls=[URL,URL.replace('/dr1/','/qr3/'),URL.replace('example','d4'),'https://example.org/not-a-science-file']
        table=Table({'uri':[u.removeprefix('https://irsa.ipac.caltech.edu/') for u in urls],
                     'time_bounds_lower':[61000.,61001.,61002.,61003.],
                     'energy_bandpassname':['SPHEREx-D2','SPHEREx-D2','SPHEREx-D4','SPHEREx-D2']})
        buffer=io.BytesIO();table.write(buffer,format='votable')
        with patch.object(archive,'COLLECTIONS',('spherex_dr1',)),patch.object(archive,'fetch_bytes',return_value=buffer.getvalue()) as fetch:
            rows,overflow=archive.tap_rows(1,2,'D2')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['url'],URL);self.assertIsNone(rows[0]['exptime']);self.assertFalse(overflow)
        self.assertIn('spherex.artifact',fetch.call_args.args[1]['QUERY'])
        self.assertIn("p.energy_bandpassname = 'SPHEREx-D2'",fetch.call_args.args[1]['QUERY'])
    def test_missing_required_columns_are_not_a_healthy_empty_result(self):
        from astropy.table import Table
        buffer=io.BytesIO();Table({'unexpected':[1]}).write(buffer,format='votable')
        with self.assertRaises(archive.ArchiveError):archive.read_table(buffer.getvalue(),('access_url',))

if __name__=='__main__':unittest.main()
