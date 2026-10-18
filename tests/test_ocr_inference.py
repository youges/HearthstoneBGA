"""Actual local neural inference on our synthetic text, never a game screenshot."""
import numpy as np
import os
from PIL import Image,ImageDraw,ImageFont

from bga.vision import Ocr,parse_number


def test_ocr_models_recognize_synthetic_rating_and_chinese():
    image=Image.new('RGB',(700,180),'white')
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(os.environ.get('BGA_TEST_FONT',r'C:\Windows\Fonts\msyh.ttc'),46)
    draw.text((25,15),'当前积分 6000',fill='black',font=font)
    draw.text((25,90),'第8名',fill='black',font=font)
    result=Ocr().tokens(np.asarray(image)[:,:,::-1].copy())
    texts=[t.text for t in result if t.score>=.85]
    assert any('6000' in t for t in texts),texts
    assert any(parse_number(t,'placement')==8 for t in texts),texts
