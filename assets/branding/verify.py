#!/usr/bin/env python3
"""Validate public PNG dimensions, CRCs, alpha and metadata without dependencies."""
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]

def inspect_png(path, expected):
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset, chunks, compressed = 8, [], b''
    while offset < len(data):
        length = struct.unpack('!I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        checksum = struct.unpack('!I', data[offset + 8 + length:offset + 12 + length])[0]
        assert zlib.crc32(kind + payload) == checksum
        chunks.append(kind.decode('ascii'))
        if kind == b'IHDR':
            width, height, depth, color, compression, filtering, interlace = struct.unpack('!IIBBBBB', payload)
            assert (width, height) == expected
            assert (depth, color, compression, filtering, interlace) == (8, 6, 0, 0, 0)
        if kind == b'IDAT':
            compressed += payload
        offset += 12 + length
    assert offset == len(data) and chunks[-1] == 'IEND'
    assert set(chunks) <= {'IHDR', 'bKGD', 'IDAT', 'IEND'}  # no EXIF/text/time/profile
    raw = zlib.decompress(compressed)
    stride, prior, alpha = width * 4, bytearray(width * 4), []
    assert len(raw) == height * (stride + 1)
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        row = bytearray(raw[start + 1:start + 1 + stride])
        assert filter_type in range(5)
        for x in range(stride):
            left = row[x - 4] if x >= 4 else 0
            above = prior[x]
            upper_left = prior[x - 4] if x >= 4 else 0
            prediction = left + above - upper_left
            nearest = min((left, above, upper_left), key=lambda v: abs(prediction - v))
            row[x] = (row[x] + (0, left, above, (left + above) // 2, nearest)[filter_type]) % 256
        alpha.extend(row[3::4])
        prior = row
    assert min(alpha) == 0 and max(alpha) == 255
    assert all(alpha[i] == 0 for i in (0, width - 1, width * (height - 1), width * height - 1))
    assert any(0 < a < 255 for a in alpha)  # antialiased alpha edges
    return {'path': str(path.relative_to(ROOT)), 'width': width, 'height': height,
            'format': 'PNG RGBA 8-bit', 'transparent_corners': True,
            'antialiased_alpha': True, 'chunks': chunks, 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}

if __name__ == '__main__':
    print(json.dumps([inspect_png(ROOT / 'danfoss_link/icon.png', (128, 128)),
                      inspect_png(ROOT / 'danfoss_link/logo.png', (250, 100))], indent=2))
