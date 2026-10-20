import struct, sys, os

def parse(buf, base=0, depth=0, out=None, prefix=""):
    if buf[:4] != b"PWAD":
        return False
    n, ofs = struct.unpack_from("<II", buf, 4)
    if ofs + n * 16 > len(buf) or n > 10000:
        return False
    for i in range(n):
        pos, size, name = struct.unpack_from("<II8s", buf, ofs + i * 16)
        name = name.split(b"\0")[0].decode("latin1")
        sub = buf[pos:pos + size]
        print("  " * depth + f"{name:10s} off=0x{base+pos:08X} size={size:9d} magic={sub[:8]!r}")
        path = prefix + name
        if out:
            if not parse(sub, base + pos, depth + 1, out, path + "_"):
                with open(os.path.join(out, path + ".bin"), "wb") as f:
                    f.write(sub)
        else:
            parse(sub, base + pos, depth + 1, None, path + "_")
    return True

data = open(sys.argv[1], "rb").read()
print("header:", data[:16].hex())
out = sys.argv[2] if len(sys.argv) > 2 else None
if out:
    os.makedirs(out, exist_ok=True)
if not parse(data, out=out):
    print("not PWAD")
