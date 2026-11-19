import os
import struct


def build_headless_dtb(in_dtb: str, out_dtb: str) -> None:
    """Strip old LCD/VDMA nodes under amba_pl from vendor SYSTEM.DTB."""
    with open(in_dtb, 'rb') as f:
        dtb = f.read()

    (
        magic,
        _totalsize,
        off_dt_struct,
        off_dt_strings,
        off_mem_rsvmap,
        version,
        last_comp_version,
        boot_cpuid_phys,
        size_dt_strings,
        size_dt_struct,
    ) = struct.unpack('>10I', dtb[:40])
    assert magic == 0xD00DFEED

    rsv_bytes = dtb[off_mem_rsvmap:off_dt_struct]
    strings_bytes = dtb[off_dt_strings:off_dt_strings + size_dt_strings]
    drop_nodes = {
        'axi_dynclk@43c00000',
        'dma@43000000',
        'v_tc@43c10000',
        'misc_clk_0',
        'xlnx_vdma_lcd',
    }

    new_struct = bytearray()
    pos = off_dt_struct
    stack = []
    skip_depth = None

    while pos < off_dt_struct + size_dt_struct:
        tok_pos = pos
        tok = struct.unpack_from('>I', dtb, pos)[0]
        pos += 4
        if tok == 1:  # FDT_BEGIN_NODE
            end = dtb.index(b'\x00', pos)
            name = dtb[pos:end].decode('ascii', errors='replace')
            pos = (end + 4) & ~3
            stack.append(name or '/')
            if skip_depth is None and len(stack) >= 2 and stack[-2] == 'amba_pl' and name in drop_nodes:
                skip_depth = len(stack)
            if skip_depth is None:
                new_struct.extend(dtb[tok_pos:pos])
        elif tok == 2:  # FDT_END_NODE
            if skip_depth is None:
                new_struct.extend(dtb[tok_pos:pos])
            elif len(stack) == skip_depth:
                skip_depth = None
            stack.pop()
        elif tok == 3:  # FDT_PROP
            plen, _pnameoff = struct.unpack_from('>II', dtb, pos)
            pos += 8 + ((plen + 3) & ~3)
            if skip_depth is None:
                new_struct.extend(dtb[tok_pos:pos])
        elif tok == 4:  # FDT_NOP
            if skip_depth is None:
                new_struct.extend(dtb[tok_pos:pos])
        elif tok == 9:  # FDT_END
            new_struct.extend(dtb[tok_pos:pos])
            break

    off_rsv = 40
    off_struct_new = off_rsv + len(rsv_bytes)
    off_strings_new = off_struct_new + len(new_struct)
    total_new = off_strings_new + len(strings_bytes)

    hdr = struct.pack(
        '>10I',
        magic,
        total_new,
        off_struct_new,
        off_strings_new,
        off_rsv,
        version,
        last_comp_version,
        boot_cpuid_phys,
        len(strings_bytes),
        len(new_struct),
    )
    with open(out_dtb, 'wb') as f:
        f.write(hdr + rsv_bytes + new_struct + strings_bytes)


if __name__ == '__main__':
    base = os.path.dirname(os.path.abspath(__file__))
    build_headless_dtb(
        os.path.join(base, 'vendor_ubuntu_boot', 'SYSTEM.DTB'),
        os.path.join(base, 'system_cam.dtb'),
    )
