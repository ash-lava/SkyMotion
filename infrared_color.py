"""False-color RGB rendering of three real, aligned infrared exposures."""
import io
import math

import numpy as np
from PIL import Image

from comparison import exposure_metadata


def prepare(channels, indices, *, allow_mixed_dates=False):
    arrays=[entry[0] for entry in channels]
    if len(arrays)!=3 or any(array.shape!=arrays[0].shape for array in arrays):
        raise ValueError('Choose three images on the same sky grid.')
    times=[entry[1].get('mjd') for entry in channels]
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in times):
        raise ValueError('Observation times must be known for all three channels.')
    span=max(times)-min(times)
    if span>1 and not allow_mixed_dates:
        raise ValueError(f'These channels are {span:.2f} days apart. Choose closer dates or explicitly allow mixed dates.')
    mask=np.logical_and.reduce([np.isfinite(array) for array in arrays])
    if mask.sum()<20:
        raise ValueError('These three images have too little common coverage. Try other exposures or a smaller cutout.')
    metadata={'false_color':True,'source':'NASA/IPAC IRSA SPHEREx',
              'time_span_days':span,'mixed_dates_allowed':allow_mixed_dates,'coverage':float(mask.mean()),
              'channels':{},'stretch':'Each channel: 5–99.5 percentile square-root stretch, measured in the common valid area.',
              'missing_pixels':'Only pixels finite in all three exposures are displayed. No gap filling.',
              'warnings':['Visible red, green and blue are assigned to measured infrared bands; they are not visible-eye colors.',
                          'Channel wavelengths vary across the patch. Dates, PSF, noise, flags and independent channel stretches affect the colors.',
                          'Quality-flagged pixels are retained. Inspect the original FITS files for scientific use.']}
    if span>1:
        metadata['warnings'].append('The channels were observed on different dates. This composite is not one moment in time; motion or variability can create colored features.')
    rgb=[]
    for label,entry,index in zip(('red','green','blue'),channels,indices):
        array,row,_,info=entry
        low,high=np.percentile(array[mask],[5,99.5]);high=max(float(high),float(low)+1e-8)
        intensity=np.sqrt(np.clip((np.where(mask,array,low)-low)/(high-low),0,1))
        rgb.append((intensity*255).astype(np.uint8))
        metadata['channels'][label]={**exposure_metadata(row,info,index),'limits':[float(low),high]}
    rgba=np.stack((*rgb,mask.astype(np.uint8)*255),axis=-1)
    buffer=io.BytesIO();Image.fromarray(np.flipud(rgba)).save(buffer,format='PNG')
    return buffer.getvalue(),metadata
