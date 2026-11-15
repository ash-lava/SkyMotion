"""Independent numeric checks for image comparison, masks, and exported science."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
from astropy.io import fits

import comparison
import server


def exposure(array, index, *, wavelength=1.3, width=.032, unit='MJy/sr', band='SPHEREx-D2'):
    array = np.asarray(array,dtype=np.float32)
    row = {'id':str(index),'date':f'2025-05-{10+index:02d}T00:00:00Z','mjd':60805.+index,'band':band,'collection':'spherex_dr1'}
    info = {'wavelength_um':wavelength,'bandwidth_um':width,'unit':unit,'version':'v1','flagged_fraction':0.,
            '_wavelength_map':np.full(array.shape,wavelength,dtype=float),'_bandwidth_map':np.full(array.shape,width,dtype=float)}
    return (array,row,server.target_wcs(15,30,3),info)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.base = np.arange(100,dtype=float).reshape(10,10)

    def test_signed_difference_and_mean_use_science_values(self):
        a = exposure(self.base,0)
        changed = self.base.copy();changed[7,3] += 8;changed[1,4] -= 6
        result = comparison.prepare(a,exposure(changed,1),0,1,background=False)
        self.assertEqual(result['difference'][7,3],8)
        self.assertEqual(result['difference'][1,4],-6)
        self.assertEqual(result['mean'][7,3],self.base[7,3]+4)
        self.assertTrue(result['metadata']['arithmetic_available'])

    def test_median_sky_removal_is_explicit_and_optional(self):
        a,b = exposure(self.base,0),exposure(self.base+25,1)
        removed = comparison.prepare(a,b,0,1,background=True)
        native = comparison.prepare(a,b,0,1,background=False)
        np.testing.assert_array_equal(removed['difference'],0)
        np.testing.assert_array_equal(native['difference'],25)
        self.assertEqual(removed['metadata']['background_b']-removed['metadata']['background_a'],25)

    def test_gaps_intersect_without_becoming_zeros_or_other_exposures(self):
        a,b=self.base.copy(),self.base.copy()+5
        a[0,0]=np.nan;b[-1,-1]=np.nan
        result=comparison.prepare(exposure(a,0),exposure(b,1),0,1,background=False)
        self.assertTrue(np.isnan(result['difference'][0,0]))
        self.assertTrue(np.isnan(result['mean'][-1,-1]))
        self.assertEqual(result['metadata']['displayed_coverage'],.98)
        pixels=np.asarray(Image.open(io.BytesIO(comparison.png(result,'difference'))))
        self.assertEqual(pixels[-1,0,3],0);self.assertEqual(pixels[0,-1,3],0)
        self.assertEqual(pixels[0,0,3],255)

    def test_difference_color_sign_and_north_up_orientation(self):
        base=np.zeros((10,10));b=base.copy();b[8,3]=10;b[1,4]=-10
        result=comparison.prepare(exposure(base,0),exposure(b,1),0,1,background=False)
        pixels=np.asarray(Image.open(io.BytesIO(comparison.png(result,'difference'))))
        self.assertGreater(pixels[1,3,0],pixels[1,3,2])
        self.assertGreater(pixels[8,4,2],pixels[8,4,0])
        np.testing.assert_array_equal(pixels[5,5,:3],[32,32,32])

    def test_locked_stretch_preserves_identical_pixel_brightness(self):
        b=self.base.copy();b[0,0]=1000
        result=comparison.prepare(exposure(self.base,0),exposure(b,1),0,1,background=False)
        aa=np.asarray(Image.open(io.BytesIO(comparison.png(result,'a'))))
        bb=np.asarray(Image.open(io.BytesIO(comparison.png(result,'b'))))
        np.testing.assert_array_equal(aa[1:,1:,:],bb[1:,1:,:])

    def test_center_wavelength_gate_uses_narrower_channel(self):
        first=exposure(self.base,0,width=.04)
        matched=exposure(self.base,1,wavelength=1.309,width=.02)
        different=exposure(self.base,1,wavelength=1.311,width=.02)
        self.assertTrue(comparison.prepare(first,matched,0,1)['metadata']['arithmetic_available'])
        blocked=comparison.prepare(first,different,0,1)
        self.assertFalse(blocked['metadata']['arithmetic_available'])
        with self.assertRaises(ValueError):comparison.png(blocked,'difference')
        with self.assertRaises(ValueError):comparison.png(blocked,'mean')
        self.assertTrue(comparison.png(blocked,'a').startswith(b'\x89PNG'))

    def test_per_pixel_wavelength_gate_masks_unmatched_regions(self):
        a,b=exposure(self.base,0),exposure(self.base+1,1)
        b[3]['_wavelength_map'][:,:4]=1.5
        result=comparison.prepare(a,b,0,1)
        self.assertTrue(result['metadata']['arithmetic_available'])
        self.assertEqual(result['metadata']['wavelength_matched_coverage'],.6)
        self.assertTrue(np.isnan(result['difference'][:,:4]).all())
        self.assertTrue(np.isfinite(result['difference'][:,4:]).all())

    def test_unknown_wavelength_units_or_other_detector_disable_arithmetic(self):
        first=exposure(self.base,0)
        for option in ({'wavelength':None},{'width':None},{'unit':None},{'band':'SPHEREx-D6'}):
            second=exposure(self.base,1,**option)
            result=comparison.prepare(first,second,0,1)
            self.assertFalse(result['metadata']['arithmetic_available'])
            self.assertTrue(result['metadata']['reasons'])

    def test_missing_spectral_maps_are_not_invented(self):
        a,b=exposure(self.base,0),exposure(self.base,1)
        del b[3]['_wavelength_map']
        self.assertFalse(comparison.prepare(a,b,0,1)['metadata']['arithmetic_available'])

    def test_flags_retained_and_reported_instead_of_silent_rejection(self):
        a,b=exposure(self.base,0),exposure(self.base+1,1)
        a[3]['flagged_fraction']=1.
        result=comparison.prepare(a,b,0,1)
        self.assertTrue(result['mask'].all())
        self.assertEqual(result['metadata']['a']['flagged_fraction'],1.)
        self.assertTrue(any('retained' in warning for warning in result['metadata']['warnings']))

    def test_no_mutation_and_no_nonoverlapping_arithmetic(self):
        a,b=exposure(self.base,0),exposure(self.base+10,1)
        comparison.prepare(a,b,0,1)
        np.testing.assert_array_equal(a[0],self.base)
        with self.assertRaises(ValueError):comparison.prepare(a,b,0,0)
        aa,bb=self.base.copy(),self.base.copy()
        aa[:5]=np.nan;bb[5:]=np.nan
        with self.assertRaises(ValueError):comparison.prepare(exposure(aa,0),exposure(bb,1),0,1)


class ComparisonAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cache=patch.object(server,'CACHE',Path(self.tmp.name));self.cache.start()
        self.client=TestClient(server.app);self.key='a'*24
        self.a=exposure(np.arange(100).reshape(10,10),0)
        self.b=exposure(np.arange(100).reshape(10,10)+4,1)
        server.write_cache(self.key,{'ra':15,'dec':30,'fov_arcmin':3,'observations':[]})

    def tearDown(self):
        self.client.close();self.cache.stop();self.tmp.cleanup()

    def test_fits_contains_signed_science_values_wcs_mask_and_provenance(self):
        with patch.object(server,'get_image',side_effect=[self.a,self.b]):
            response=self.client.get(f'/api/comparison/{self.key}/data.fits?a=0&b=1&background=false')
        self.assertEqual(response.status_code,200)
        with fits.open(io.BytesIO(response.content)) as hdus:
            np.testing.assert_array_equal(hdus[0].data,4.)
            np.testing.assert_array_equal(hdus['VALID'].data,1)
            self.assertEqual(hdus[0].header['BUNIT'],'MJy/sr')
            self.assertEqual(hdus[0].header['SRC_A'],'0')
            self.assertEqual(hdus[0].header['SRC_B'],'1')
            self.assertEqual(hdus[0].header['CTYPE1'],'RA---TAN')
            self.assertFalse(hdus[0].header['BGSUB'])

    def test_blocked_pair_cannot_download_arithmetic_by_editing_url(self):
        self.b[3]['wavelength_um']=1.6
        for suffix in ('image.png?a=0&b=1&view=difference','data.fits?a=0&b=1'):
            with patch.object(server,'get_image',side_effect=[self.a,self.b]):
                response=self.client.get(f'/api/comparison/{self.key}/'+suffix)
            self.assertEqual(response.status_code,422)

    def test_metadata_excludes_private_arrays_and_reports_provenance(self):
        with patch.object(server,'get_image',side_effect=[self.a,self.b]):
            response=self.client.get(f'/api/comparison/{self.key}?a=0&b=1')
        self.assertEqual(response.status_code,200)
        info=response.json();self.assertTrue(info['arithmetic_available'])
        self.assertEqual(info['a']['source_index'],0)
        self.assertEqual(info['b']['id'],'1')
        self.assertEqual(info['time_separation_days'],1.)
        self.assertNotIn('_wavelength_map',response.text)

    def test_bad_view_is_rejected_before_fits_download(self):
        with patch.object(server,'get_image') as fetch:
            self.assertEqual(self.client.get(f'/api/comparison/{self.key}/image.png?a=0&b=1&view=madeup').status_code,400)
            self.assertEqual(self.client.get(f'/api/comparison/{self.key}?a=-1&b=1').status_code,422)
            fetch.assert_not_called()


if __name__=='__main__':
    unittest.main()
