import base64
import binascii
import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
MAX_REFERENCE_EDGE = 1024

def prepare_reference(encoded):
    """Keep upload bytes for encrypted retention; bound and orient model input."""
    if not isinstance(encoded, str) or not encoded:
        raise ValueError('参考图片格式不正确。')
    if encoded.startswith('data:'):
        header, separator, encoded = encoded.partition(',')
        if not separator or header.lower() not in (
            'data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'
        ):
            raise ValueError('请上传 PNG、JPEG 或 WebP 静态图片。')
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise ValueError('参考图片不能超过 8 MB。')
    try:
        original = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('参考图片编码不正确。') from None
    if not original or len(original) > MAX_IMAGE_BYTES:
        raise ValueError('参考图片不能超过 8 MB。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(original)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('请上传 PNG、JPEG 或 WebP 静态图片。')
                width, height = source.size
                if width < 32 or height < 32 or width * height > MAX_IMAGE_PIXELS or max(width, height) > 8192:
                    raise ValueError('原图边长至少 32 像素、最多 8192 像素，总像素不超过 1600 万。')
                image_format = source.format.lower()
                source.load()
                oriented = ImageOps.exif_transpose(source)
                mode = 'RGBA' if 'A' in oriented.getbands() or 'transparency' in oriented.info else 'RGB'
                prepared = oriented.convert(mode)
                prepared.thumbnail((MAX_REFERENCE_EDGE, MAX_REFERENCE_EDGE), Image.Resampling.LANCZOS)
                # VAE dimensions must remain multiples of 32; pad instead of
                # stretching the uploaded composition for arbitrary aspect ratios.
                aligned_size = tuple(max(32, ((edge + 31) // 32) * 32) for edge in prepared.size)
                if prepared.size != aligned_size:
                    canvas = Image.new(mode, aligned_size, (255,255,255,0) if mode=='RGBA' else (255,255,255))
                    canvas.paste(prepared, ((canvas.width-prepared.width)//2,(canvas.height-prepared.height)//2))
                    prepared = canvas
                buffer = io.BytesIO()
                prepared.save(buffer, format='PNG')
                model_bytes = buffer.getvalue()
                descriptor = {
                    'index': 0, 'format': image_format, 'bytes': len(original),
                    'width': width, 'height': height, 'sha256': hashlib.sha256(original).hexdigest(),
                    'model_width': prepared.width, 'model_height': prepared.height,
                    'model_sha256': hashlib.sha256(model_bytes).hexdigest(),
                }
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('无法读取参考图片，请选择有效的 PNG、JPEG 或 WebP 文件。') from None
    return original, descriptor, 'data:image/png;base64,' + base64.b64encode(model_bytes).decode('ascii')
