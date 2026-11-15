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
        with patch.object(archive,'get_table',side_effect=table),patch.object(archive,'COLLECTIONS',('spherex_dr1','spherex_qr3')):
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4)
        self.assertEqual(total,1);self.assertEqual(live,['spherex_dr1']);self.assertIn('spherex_qr3',failed);self.assertTrue(warnings)
    def test_all_failed_is_not_empty_success(self):
        with patch.object(archive,'get_table',side_effect=archive.ArchiveError('502')),self.assertRaises(archive.ArchiveError):archive.search(12,3,.1,'D2',4)
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
            self.assertEqual(self.client.get('/api/health').json()['version'],'2.0.0');self.assertEqual(self.client.get('/api/archive').json()['status'],'unchecked');probe.assert_not_called()
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
if __name__=='__main__':unittest.main()
