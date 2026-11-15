"""Offline regression tests: python -m unittest -v test_server.py"""
import importlib.util
import io
from urllib.parse import urlparse, parse_qs
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
        def table(ra,dec,radius,collection,**kwargs):
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
            self.assertEqual(self.client.get('/api/health').json()['version'],'2.0.7');self.assertEqual(self.client.get('/api/archive').json()['status'],'unchecked');probe.assert_not_called()
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
    def test_limited_live_sample_is_cached_but_refresh_bypasses_it(self):
        table,limited=archive.read_sia_csv((Path(__file__).parent/'tests/fixtures/sia-m101-four.csv').read_bytes(),4)
        with patch.object(archive,'COLLECTIONS',('spherex_dr1',)),patch.object(archive,'get_table',return_value=(table,limited)) as query:
            first=self.client.get('/api/observations?ra=210.8&dec=54.3&detector=D3').json()
            second=self.client.get('/api/observations?ra=210.8&dec=54.3&detector=D3').json()
            self.assertEqual(query.call_count,1);self.assertEqual(first,second)
            self.client.get('/api/observations?ra=210.8&dec=54.3&detector=D3&refresh=true')
        self.assertEqual(query.call_count,2);self.assertTrue(first['sampling_limited']);self.assertTrue(first['total_lower_bound'])
        self.assertEqual(first['query_limits'],{'spherex_dr1':4});self.assertIsInstance(first['queried_at'],float)
    def test_invalid_and_expired_key(self):
        self.assertEqual(self.client.get('/api/frame/bad/0.png').status_code,400);self.assertEqual(self.client.get('/api/frame/'+'a'*24+'/0.png').status_code,404)
        self.assertEqual(self.client.get('/api/photometry/bad').status_code,400)
    def test_failed_image_not_fake(self):
        with patch.object(server,'image_data',side_effect=archive.ArchiveError('Image unavailable')):result=self.client.get('/api/frame/'+'a'*24+'/0.png')
        self.assertEqual(result.status_code,502);self.assertIn('Image unavailable',result.json()['detail'])
    def test_png_orientation_and_cache_headers(self):
        array=np.tile(np.arange(20,dtype=float)[:,None],(1,20))
        with patch.object(server,'get_image',return_value=(array,{},None,{})):result=self.client.get('/api/frame/'+'a'*24+'/0.png')
        pixels=np.asarray(Image.open(io.BytesIO(result.content)));self.assertGreater(int(pixels[0,10,0]),int(pixels[-1,10,0]));self.assertEqual(result.headers['cache-control'],'no-store')
    def test_missing_pixels_are_transparent_but_valid_zero_is_opaque(self):
        array=np.zeros((8,8),dtype=float);array[0,0]=np.nan;array[1,1]=np.inf;array[2,2]=-np.inf
        with patch.object(server,'get_image',return_value=(array,{},None,{})):
            response=self.client.get('/api/frame/'+'a'*24+'/0.png')
            info=self.client.get('/api/frame-info/'+'a'*24+'/0').json()
        pixels=np.asarray(Image.open(io.BytesIO(response.content)))
        self.assertEqual(pixels.shape,(8,8,4))
        np.testing.assert_array_equal(pixels[:,:,3],np.flipud(np.isfinite(array).astype(np.uint8)*255))
        self.assertTrue(np.all(pixels[:,:,:3]==0));self.assertEqual(pixels[0,0,3],255)
        self.assertEqual(info['missing_pixels'],3);self.assertEqual(info['valid_pixels'],61)
        self.assertEqual(info['total_pixels'],64);self.assertEqual(info['coverage'],61/64)
    def test_valid_science_values_retain_the_existing_display_stretch(self):
        array=np.arange(100,dtype=float).reshape(10,10);array[0,0]=np.nan
        low,high=np.percentile(array[np.isfinite(array)],[5,99.5])
        expected=np.flipud(np.uint8(np.sqrt(np.clip((np.nan_to_num(array,nan=low)-low)/(high-low),0,1))*255))
        with patch.object(server,'get_image',return_value=(array,{},None,{})):
            response=self.client.get('/api/frame/'+'a'*24+'/0.png')
        pixels=np.asarray(Image.open(io.BytesIO(response.content)))
        np.testing.assert_array_equal(pixels[:,:,0],expected)
        np.testing.assert_array_equal(pixels[:,:,0],pixels[:,:,1]);np.testing.assert_array_equal(pixels[:,:,1],pixels[:,:,2])
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
        with patch.object(self.sky.hips_survey,'render_survey',return_value=self.jpeg) as render:
            first=self.client.get('/api/sky.jpg?ra=83.8&dec=-5.3&width=64&height=64')
            second=self.client.get('/api/sky.jpg?ra=83.8&dec=-5.3&width=64&height=64')
        self.assertEqual(first.status_code,200);self.assertEqual(first.headers['content-type'],'image/jpeg')
        self.assertEqual(first.content,second.content);self.assertEqual(render.call_count,1)
        self.assertEqual(first.headers['x-sky-source'],'CDS/P/DSS2/color')
        self.assertIn('IRSA',first.headers['x-sky-provider'])
    def test_tile_failure_is_actionable_and_not_cached(self):
        with patch.object(self.sky.hips_survey,'render_survey',side_effect=archive.ArchiveError('HTTP 502')):
            result=self.client.get('/api/sky.jpg?ra=1&dec=0&width=64&height=64')
        self.assertEqual(result.status_code,503);self.assertEqual(result.json()['detail']['code'],'SKY_SURVEY_UNAVAILABLE')
        self.assertEqual(result.headers['retry-after'],'30');self.assertIn('IRSA',result.json()['detail']['message'])
        self.assertEqual(result.json()['detail']['upstream'],['HTTP 502']);self.assertFalse(self.sky.CACHE)
    def test_changed_survey_and_field_have_separate_cache_entries(self):
        with patch.object(self.sky.hips_survey,'render_survey',return_value=self.jpeg) as render:
            for suffix in ('survey=dss','survey=wise','survey=dss&fov=3'):
                self.assertEqual(self.client.get('/api/sky.jpg?ra=1&dec=0&width=64&height=64&'+suffix).status_code,200)
        self.assertEqual(render.call_count,3)
    def test_bad_parameters_do_not_contact_upstream(self):
        with patch.object(self.sky.hips_survey,'render_survey') as render:
            for suffix in ('ra=360&dec=0','ra=1&dec=99','ra=1&dec=0&width=10000','ra=1&dec=0&fov=361'):
                self.assertEqual(self.client.get('/api/sky.jpg?'+suffix).status_code,422)
            self.assertEqual(self.client.get('/api/sky.jpg?ra=1&dec=0&survey=https://example.com').status_code,400)
            render.assert_not_called()
    def test_wcs_center_scale_and_orientation(self):
        import math
        wcs=self.sky.image_wcs(359.9,89,10,1000,500)
        self.assertEqual(wcs['CRPIX1'],500.5);self.assertEqual(wcs['CRPIX2'],250.5)
        self.assertEqual(wcs['CRVAL1'],359.9);self.assertLess(wcs['CDELT1'],0);self.assertGreater(wcs['CDELT2'],0)
        self.assertAlmostEqual(math.degrees(2*math.atan(math.radians(wcs['CDELT2'])*1000/2)),10)
        from astropy.wcs import WCS
        north=WCS(self.sky.image_wcs(0,90,3,900,500))
        lon,lat=north.pixel_to_world_values(500,249.5)
        self.assertAlmostEqual(float(lon),270);self.assertAlmostEqual(float(lat),89.83162868,places=7)
    def test_local_atlas_script_is_served(self):
        result=self.client.get('/static/sky-atlas.js');self.assertEqual(result.status_code,200)
        self.assertIn('pixelToSky',result.text)
    def test_full_sky_endpoint_accepts_arbitrary_center_and_uses_aitoff(self):
        with patch.object(self.sky.hips_survey,'render_survey',return_value=self.jpeg) as render:
            response=self.client.get('/api/sky.jpg?ra=12.345&dec=-90&fov=360&width=64&height=64')
        self.assertEqual(response.status_code,200);self.assertIn('AIT',response.headers['x-sky-projection'])
        spec=render.call_args.args[0]
        self.assertEqual(spec['CRVAL1'],12.345);self.assertEqual(spec['CRVAL2'],-90)
        self.assertEqual(spec['CTYPE1'],'RA---AIT')

class HiPSSurveyTests(unittest.TestCase):
    def setUp(self):
        import hips_survey
        self.hips=hips_survey;self.hips.TILES.clear()
        buffer=io.BytesIO();Image.new('RGB',(512,512),(20,30,40)).save(buffer,format='JPEG');self.jpeg=buffer.getvalue()
    def tearDown(self):self.hips.TILES.clear()
    def test_allowed_live_tile_address_and_cache(self):
        with patch.object(archive,'fetch_bytes',return_value=self.jpeg) as fetch:
            first=self.hips.get_tile('dss',8,182953);second=self.hips.get_tile('dss',8,182953)
        self.assertIs(first,second);self.assertFalse(first.flags.writeable);self.assertEqual(first.shape,(512,512,3))
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(fetch.call_args.args[0],'https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color/Norder8/Dir180000/Npix182953.jpg')
        self.assertLessEqual(fetch.call_args.kwargs['max_bytes'],1500000)
    def test_invalid_tile_indices_never_fetch(self):
        with patch.object(archive,'fetch_bytes') as fetch:
            for order,index in ((-1,0),(10,0),(0,-1),(0,12)):
                with self.subTest(order=order,index=index),self.assertRaises(archive.ArchiveError):self.hips.get_tile('dss',order,index)
        fetch.assert_not_called()
    def test_html_png_and_wrong_dimensions_are_not_tiles(self):
        png=io.BytesIO();Image.new('RGB',(512,512)).save(png,format='PNG')
        small=io.BytesIO();Image.new('RGB',(64,64)).save(small,format='JPEG')
        for raw in (b'<html>Proxy error</html>',png.getvalue(),small.getvalue()):
            with self.subTest(length=len(raw)),patch.object(archive,'fetch_bytes',return_value=raw),self.assertRaises(archive.ArchiveError):
                self.hips.get_tile('dss',0,4)
            self.assertFalse(self.hips.TILES)
    def test_tile_failure_does_not_poison_retry(self):
        with patch.object(archive,'fetch_bytes',side_effect=[archive.ArchiveError('502'),self.jpeg]) as fetch:
            with self.assertRaises(archive.ArchiveError):self.hips.get_tile('dss',0,4)
            self.assertEqual(self.hips.get_tile('dss',0,4).shape,(512,512,3))
        self.assertEqual(fetch.call_count,2)
    def test_tile_cache_is_bounded_and_evicts_oldest(self):
        with patch.object(archive,'fetch_bytes',return_value=self.jpeg) as fetch,patch.object(self.hips,'MAX_TILE_CACHE_BYTES',800000):
            for index in (4,5,4):self.hips.get_tile('dss',0,index)
        self.assertEqual(fetch.call_count,3);self.assertEqual(len(self.hips.TILES),1)
    def test_expired_tile_is_fetched_again(self):
        with patch.object(archive,'fetch_bytes',return_value=self.jpeg) as fetch:
            self.hips.get_tile('dss',0,4)
            self.hips.TILES[('dss',0,4)]=(-4000,self.hips.TILES[('dss',0,4)][1])
            self.hips.get_tile('dss',0,4)
        self.assertEqual(fetch.call_count,2)
    def test_hips_jpeg_quadrants_follow_the_ivoa_orientation(self):
        # Four known HEALPix face-4 quarter centers: south, east, west, north.
        lat=np.degrees(np.arcsin(1/3))
        ids=self.hips.pixel_addresses(np.array([0.,22.5,337.5,0.]),np.array([-lat,0.,0.,lat]),0)
        self.assertTrue(np.all((ids>>18)==4))
        row,col=self.hips.jpeg_positions(ids)
        self.assertEqual(list(row>=256),[False,True,False,True])
        self.assertEqual(list(col>=256),[False,False,True,True])
    def test_rendered_image_is_north_up_and_east_left_across_ra_wrap(self):
        from sky_service import image_wcs
        tile=np.empty((512,512,3),dtype=np.uint8)
        tile[:256,:256]=[255,0,0]      # South, per HiPS face-4 geometry.
        tile[256:,:256]=[0,255,0]      # East.
        tile[:256,256:]=[0,0,255]      # West.
        tile[256:,256:]=[255,255,255]  # North.
        with patch.dict(self.hips.SOURCES,{'dss':('https://irsa.ipac.caltech.edu/test',0)}),patch.object(self.hips,'get_tile',return_value=tile):
            raw=self.hips.render_survey(image_wcs(359.99,0,60,64,64),'dss')
        image=np.asarray(Image.open(io.BytesIO(raw)))
        self.assertEqual(image.shape,(64,64,3))
        self.assertTrue(np.all(image[8,32]>220));self.assertGreater(image[56,32,0],220)
        self.assertGreater(image[32,8,1],220);self.assertGreater(image[32,56,2],220)
    def test_many_tiles_reduce_order_before_network_work(self):
        from sky_service import image_wcs
        grid=np.arange(64*64,dtype=np.int64).reshape(64,64)%(self.hips.MAX_TILES+1)<<18
        tile=np.zeros((512,512,3),dtype=np.uint8)
        with patch.object(self.hips,'address_grid',side_effect=[grid,np.zeros((64,64),dtype=np.int64)]) as address,patch.object(self.hips,'get_tile',return_value=tile) as fetch:
            raw=self.hips.render_survey(image_wcs(0,0,.01,64,64),'dss')
        self.assertEqual(len(address.call_args_list),2)
        self.assertEqual(address.call_args_list[0].args[3]-address.call_args_list[1].args[3],1)
        self.assertEqual(fetch.call_count,1);self.assertTrue(raw.startswith(b'\xff\xd8'))
    def test_all_sky_coordinates_match_independent_astropy_wcs(self):
        from astropy.wcs import WCS
        from sky_service import image_wcs
        xx=np.array([450.,520.,300.,600.]);yy=np.array([250.,290.,200.,300.])
        for dec in (-89.99,-30,0,54,89.99):
            w=WCS(image_wcs(359.99,dec,360,900,500))
            lon,lat=self.hips.aitoff_world(xx,yy,900,500,w)
            expected_ra,expected_dec=w.pixel_to_world_values(xx,499-yy)
            np.testing.assert_allclose((lon-expected_ra+180)%360-180,0,atol=1e-7)
            np.testing.assert_allclose(lat,expected_dec,atol=1e-7)
    def test_full_sky_masks_outside_ellipse_and_accepts_exact_poles(self):
        from astropy.wcs import WCS
        from sky_service import image_wcs
        for dec in (-90,90):
            w=WCS(image_wcs(123,dec,360,101,51))
            lon,lat=self.hips.aitoff_world(np.array([0,50]),np.array([0,25]),101,51,w)
            self.assertTrue(np.isnan(lon[0]));self.assertTrue(np.isnan(lat[0]))
            self.assertAlmostEqual(lat[1],dec)
            grid=self.hips.address_grid(w,101,51,0)
            self.assertEqual(grid[0,0],-1);self.assertGreaterEqual(grid[25,50],0)
    def test_full_sky_background_is_blank_outside_the_projection(self):
        from sky_service import image_wcs
        tile=np.full((512,512,3),200,dtype=np.uint8)
        with patch.object(self.hips,'get_tile',return_value=tile):
            raw=self.hips.render_survey(image_wcs(0,0,360,100,60),'dss')
        image=np.asarray(Image.open(io.BytesIO(raw)))
        self.assertTrue(np.all(image[0,0]<10));self.assertTrue(np.all(image[30,50]>180))

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
        def table(ra,dec,radius,collection,**kwargs):
            if collection=='spherex_qr3':raise archive.ArchiveError('502')
            return [row()],False
        diagnostics={}
        with patch.object(archive,'COLLECTIONS',('spherex_dr1','spherex_qr3')),patch.object(archive,'get_table',side_effect=table),patch.object(archive,'tap_rows',return_value=([fallback],True)):
            rows,total,warnings,live,failed=archive.search(12,3,.1,'D2',4,diagnostics=diagnostics)
        self.assertEqual(total,1);self.assertEqual(diagnostics['method'],'SIA2 + TAP')
        self.assertTrue(any('limited live sample' in w for w in warnings))
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
        self.assertIn('SELECT TOP 16',fetch.call_args.args[1]['QUERY'])
        self.assertIn("a.uri LIKE '%/spherex/dr1/level2/%'",fetch.call_args.args[1]['QUERY'])
        self.assertEqual(fetch.call_args.args[1]['MAXREC'],16);self.assertEqual(fetch.call_args.args[1]['FORMAT'],'csv')
    def test_tap_accepts_a_bounded_csv_result(self):
        raw=f'uri,time_bounds_lower,energy_bandpassname\n{URL},61000.0,SPHEREx-D2\n'.encode()
        with patch.object(archive,'COLLECTIONS',('spherex_dr1',)),patch.object(archive,'fetch_bytes',return_value=raw):
            rows,limited=archive.tap_rows(1,2,'D2')
        self.assertEqual(rows[0]['url'],URL);self.assertFalse(limited)
    def test_missing_required_columns_are_not_a_healthy_empty_result(self):
        from astropy.table import Table
        buffer=io.BytesIO();Table({'unexpected':[1]}).write(buffer,format='votable')
        with self.assertRaises(archive.ArchiveError):archive.read_table(buffer.getvalue(),('access_url',))


class LiveSIARequestTests(unittest.TestCase):
    def setUp(self):
        self.csv=(Path(__file__).parent/'tests/fixtures/sia-m101-four.csv').read_bytes()
    def test_user_csv_is_live_metadata_not_an_error_page(self):
        table,limited=archive.read_sia_csv(self.csv,4)
        self.assertEqual(len(table),4);self.assertTrue(limited)
        self.assertEqual(set(table['energy_bandpassname']),{'SPHEREx-D3','SPHEREx-D6'})
        self.assertTrue(all(archive.safe_image_url(url) for url in table['access_url']))
        import json
        self.assertEqual(json.loads(table['cloud_access'][0])['aws']['region'],'us-east-1')
        self.assertEqual(set(table['upload_row_id']),{'1'})
    def test_retry_smaller_live_query_after_proxy_error(self):
        def remote(url,**options):
            parsed=urlparse(url);params={k:v[0] for k,v in parse_qs(parsed.query).items()}
            self.assertEqual(parsed.scheme+'://'+parsed.netloc+parsed.path,archive.SIA_URL)
            self.assertEqual(params['RESPONSEFORMAT'],'CSV')
            self.assertEqual(params['POS'],'CIRCLE 210.80227 54.34895 0.00001')
            self.assertIn('BAND',params)
            self.assertGreater(options['timeout'],21)
            if int(params['MAXREC'])>4:raise archive.ArchiveError('Proxy Error')
            return self.csv
        with patch.object(archive,'fetch_bytes',side_effect=remote) as fetch:
            table,limited=archive.get_table(210.80227,54.34895,.07,'spherex_dr1',detector='D3')
        self.assertEqual(len(table),4);self.assertTrue(limited)
        limits=[int(parse_qs(urlparse(c.args[0]).query)['MAXREC'][0]) for c in fetch.call_args_list]
        self.assertGreater(limits[0],limits[-1]);self.assertEqual(table.meta['query_maxrec'],4)
    def test_detector_is_forwarded_to_sia_before_row_limit(self):
        with patch.object(archive,'get_table',return_value=([row()],False)) as query:
            archive.search(12,3,.1,'D2',4)
        self.assertTrue(all(call.kwargs['detector']=='D2' for call in query.call_args_list))
    def test_empty_csv_with_schema_is_a_valid_empty_response(self):
        header=self.csv.splitlines()[0]+b'\n'
        table,limited=archive.read_sia_csv(header,4)
        self.assertEqual(len(table),0);self.assertFalse(limited)
    def test_bad_csv_html_and_incomplete_rows_are_errors(self):
        for raw in [b'<html>Proxy error</html>',b'wrong,columns\n1,2\n',b'access_url,energy_bandpassname,t_min\nhttps://example.org/a.fits,SPHEREx-D2\n']:
            with self.subTest(raw=raw),self.assertRaises(archive.ArchiveError):archive.read_sia_csv(raw,4)
    def test_sample_limit_is_retained_in_diagnostics(self):
        table,limited=archive.read_sia_csv(self.csv,4);diagnostics={}
        with patch.object(archive,'get_table',return_value=(table,limited)):
            rows,total,warnings,live,failed=archive.search(210.8,54.3,.05,'D3',24,diagnostics=diagnostics)
        self.assertEqual(total,2);self.assertTrue(diagnostics['sampling_limited'])
        self.assertTrue(diagnostics['complete_search']);self.assertTrue(warnings);self.assertFalse(failed)

if __name__=='__main__':unittest.main()
