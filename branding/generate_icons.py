"""Convert the supplied logo into app assets without changing its design.

Requires Pillow only when regenerating icons; the app uses the generated files.
"""
from pathlib import Path
from PIL import Image


def main():
    root = Path(__file__).resolve().parents[1]
    with Image.open(root / 'branding' / 'logo-source.png') as source:
        image = source.convert('RGBA')
        if image.width != image.height:
            raise SystemExit('Use a square logo; automatic cropping is disabled.')
        assets = root / 'assets'
        assets.mkdir(exist_ok=True)
        image.resize((256, 256), Image.Resampling.LANCZOS).save(assets / 'graild-logo.png', optimize=True)
        image.save(assets / 'graild.ico', format='ICO', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
        image.resize((1024, 1024), Image.Resampling.LANCZOS).save(assets / 'graild.icns', format='ICNS')
    print('Generated header PNG, multi-size Windows ICO, and macOS ICNS.')


if __name__ == '__main__':
    main()
