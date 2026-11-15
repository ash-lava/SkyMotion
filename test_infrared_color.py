"""Color channels must remain traceable, aligned, measured pixels."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

import infrared_color
import server
from test_comparison import exposure


class ColorTests(unittest.TestCase):
    def setUp(self):
        base=np.arange(100,dtype=float).reshape(10,10)
        self.entries=[exposure(base,0),exposure(99-base,1),exposure(np.full_like(base,5),2)]
        for i,entry in enumerate(self.entries):
            entry[1]['mjd']=60805+i*.1
            entry[1]['url']=f'https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/test{i}.fits'

    def test_rgb_assignment_north_up_and_constant_channel(self):
        raw,info=infrared_color.prepare(self.entries,[0,1,2])
        pixels=np.asarray(Image.open(io.BytesIO(raw)))
        self.assertGreater(int(pixels[0,5,0]),int(pixels[-1,5,0]))
        self.assertLess(int(pixels[0,5,1]),int(pixels[-1,5,1]))
        self.assertTrue((pixels[:,:,2]==0).all())
        self.assertTrue((pixels[:,:,3]==255).all())
        self.assertTrue(info['false_color'])
        self.assertAlmostEqual(info['time_span_days'],.2)

    def test_missing_any_channel_is_transparent_and_never_filled(self):
        self.entries[0][0][0,0]=np.nan
        self.entries[1][0][1,1]=np.inf
        self.entries[2][0][2,2]=np.nan
        raw,info=infrared_color.prepare(self.entries,[0,1,2])
        pixels=np.asarray(Image.open(io.BytesIO(raw)))
        self.assertEqual(info['coverage'],.97)
        self.assertEqual(np.count_nonzero(pixels[:,:,3]==0),3)
        self.assertTrue((pixels[pixels[:,:,3]==0,:3]==0).all())

    def test_mixed_dates_need_explicit_choice_and_are_recorded(self):
        self.entries[2][1]['mjd']+=30
        with self.assertRaisesRegex(ValueError,'explicitly allow mixed dates'):
            infrared_color.prepare(self.entries,[0,1,2])
        raw,info=infrared_color.prepare(self.entries,[0,1,2],allow_mixed_dates=True)
        self.assertTrue(raw.startswith(b'\x89PNG'))
        self.assertTrue(info['mixed_dates_allowed'])
        self.assertGreater(info['time_span_days'],30)
        self.assertTrue(any('not one moment' in warning for warning in info['warnings']))

    def test_provenance_retains_each_product_date_wavelength_and_index(self):
        _,info=infrared_color.prepare(self.entries,[7,3,9])
        for label,index,entry in zip(('red','green','blue'),(7,3,9),self.entries):
            channel=info['channels'][label]
            self.assertEqual(channel['source_index'],index)
            self.assertEqual(channel['id'],entry[1]['id'])
            self.assertEqual(channel['date'],entry[1]['date'])
            self.assertEqual(channel['archive_url'],entry[1]['url'])
            self.assertEqual(channel['wavelength_um'],entry[3]['wavelength_um'])
        self.assertNotIn('_wavelength_map',info['channels']['red'])

    def test_no_common_area_or_unknown_time_is_rejected(self):
        self.entries[0][0][:5]=np.nan
        self.entries[1][0][5:]=np.nan
        with self.assertRaisesRegex(ValueError,'common coverage'):
            infrared_color.prepare(self.entries,[0,1,2])
        self.entries[2][1]['mjd']=None
        with self.assertRaisesRegex(ValueError,'times must be known'):
            infrared_color.prepare(self.entries,[0,1,2])


class ColorAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cache=patch.object(server,'CACHE',Path(self.tmp.name));self.cache.start()
        self.client=TestClient(server.app);self.keys=['a'*24,'b'*24,'c'*24]
        for key in self.keys:
            server.write_cache(key,{'ra':1,'dec':2,'fov_arcmin':3,'observations':[{'mjd':60805.}]})
        self.params={'red_key':self.keys[0],'green_key':self.keys[1],'blue_key':self.keys[2],
                     'red_index':0,'green_index':0,'blue_index':0}
        self.entries=[exposure(np.arange(100).reshape(10,10),0) for _ in range(3)]

    def tearDown(self):
        self.client.close();self.cache.stop();self.tmp.cleanup()

    def test_other_sky_patch_cannot_be_used_to_fill_a_channel(self):
        server.write_cache(self.keys[1],{'ra':200,'dec':2,'fov_arcmin':3,'observations':[]})
        with patch.object(server,'get_image') as fetch:
            response=self.client.get('/api/color',params=self.params)
            self.assertEqual(response.status_code,400);fetch.assert_not_called()

    def test_real_renderer_returns_png_and_separate_channel_provenance(self):
        with patch.object(server,'get_image',side_effect=self.entries):
            response=self.client.get('/api/color/image.png',params=self.params)
        self.assertEqual(response.status_code,200)
        self.assertEqual(Image.open(io.BytesIO(response.content)).mode,'RGBA')
        with patch.object(server,'get_image',side_effect=self.entries):
            response=self.client.get('/api/color',params=self.params)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['channels']['red']['key'],self.keys[0])
        self.assertTrue(response.json()['false_color'])

    def test_negative_index_and_invalid_snapshot_are_not_images(self):
        self.assertEqual(self.client.get('/api/color',params={**self.params,'red_index':-1}).status_code,422)
        self.assertEqual(self.client.get('/api/color/image.png',params={**self.params,'red_key':'bad'}).status_code,400)

    def test_mixed_date_gate_runs_before_any_science_download(self):
        server.write_cache(self.keys[2],{'ra':1,'dec':2,'fov_arcmin':3,'observations':[{'mjd':60900.}]})
        with patch.object(server,'get_image') as fetch:
            response=self.client.get('/api/color',params=self.params)
            self.assertEqual(response.status_code,422);fetch.assert_not_called()


if __name__=='__main__':
    unittest.main()
