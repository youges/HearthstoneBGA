"""Convert the approved PNG artwork to a multi-resolution Windows ICO."""
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
SIZES=(16,20,24,32,40,48,64,96,128,256)


def main():
    source=ROOT/'assets/ui/app-icon.png'
    destination=source.with_suffix('.ico')
    with Image.open(source) as original:
        image=original.convert('RGBA')
        if image.width!=image.height:
            raise ValueError('Application icon artwork must be square')
        image.save(destination,format='ICO',sizes=[(n,n) for n in SIZES])
    with Image.open(destination) as icon:
        assert icon.ico.sizes()=={(n,n) for n in SIZES}
    print(destination)


if __name__=='__main__':main()
