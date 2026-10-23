#!/usr/bin/env python3
"""
Leica M8 firmware 2.014 -- in-camera 14-bit DNG, staged builds (docs/DNG_PLAN.md §8 step 5).

Every build starts from the stock file, applies the persistent-RAW patch (P1-P3 from
m8_rawpatch.py; the result must be the flashed build f6589c41...), then the pieces of one
stage. Stages are not cumulative: each is a complete build, one flash per stage.

  Stage  Pieces                          Proves                                Status
  1      canary                          we control file contents              camera-tested 2026-10-20
  2      canary, ldimg                   idle test: nothing else runs ldimg    emulator-tested
  3      canary, ldimg (dump), hook      metadata offsets, from the camera     emulator-tested
  4      tiff, ldimg, hook               first in-camera 14-bit DNG (.RAW)     emulator-tested
  5      tiff, ldimg, hook, ext          files named .DNG                      emulator-tested
  6      stage 4 + info, info key        INFO opens Body Debug Data            camera-tested 2026-10-23
  7      stage 4 + screens, screens key  INFO screens: histogram, stats        camera-tested 2026-10-23:
                                         histogram stayed on the first shot; replaced by stage 8
  8      stage 4 + stats, stats key      INFO shows Camera stats               camera-tested 2026-10-23
  10     stats, stats key (no DNG)       Option 1 + INFO Camera stats          in progress

Pieces (each in one declared region, REGIONS):
  canary  0x3CEA0 mov r0,#7 -> #0xA5: RAW header u16[3] = 0xA5
  tiff    0x3CE48-0x3CEFC header block rewritten (tools/asm/m8_header.s): u16[0..3] = TIFF header
  ldimg   0x28AB0-0x29104 dng_hook code (tools/asm/m8_dnghook.s) + mode/black/slot tables + IFD template
          (m8_wrapdng.build_template), rest filled with undefined instructions; entry = stub
          returning 0. "ldimg (dump)" = same bytes with mode 1 instead of 2.
  hook    0x3C6A8 b 0x3C5EC -> bl 0x28AB8 (RAW producer, last block)
  ext     0x3CFF8 store routine's "RAW" literal 0xD6590 -> "DNG" 0xD6570 (only reader: 0x3CCE0)
  info    0x2ABD0-0x2AF90 bf_memtest1 debug command -> stub returning 0 + info_open
          (tools/asm/m8_info.s), rest undefined fill
  info key 0x44F68 bne 0x44F8C -> bne 0x2ABD8 (INFO in shooting mode, not in service mode)
  screens 0x2ABD0-0x2B6E8 bf_memtest1/2/3 + bf_checktrans (+ 2 helpers only bf_memtest2 calls) ->
          stubs at the four entries + INFO screens (tools/asm/m8_infoscreens.s), rest undefined fill
  screens key  as info key, to the screens' info_open (also 0x2ABD8)
  stats   0x2ABD0-0x2B338 bf_memtest1 + the 2 helpers only bf_memtest2 calls + bf_memtest2 ->
          stubs at both entries + Camera stats screen (tools/asm/m8_infostats.s), rest undefined fill
  stats key    as info key, to the stats screen's info_open (also 0x2ABD8)

Assembled bytes are frozen here with their SHA-256; m8_savetest.py reassembles the sources and
fails if they no longer match.

Safety checks run on every build (the build is refused if one fails):
  - input is the stock 2.014 file (SHA-256), base equals the flashed build;
  - each piece finds the expected original bytes (or their SHA-256 for long regions);
  - the output differs from the flashed build only inside the PXA lump, and there only in
    the regions the stage's pieces declare; every other lump is byte-identical;
  - every changed instruction is printed as Capstone disassembly at its real address.

Test before flashing: work/venv/bin/python tools/m8_savetest.py --stage N
Copy the output to the card as M8-2_014.UPD (the updater looks for M8.UPD / M8-x_yyy.UPD).

Usage: python3 m8_dngpatch.py firmware/stock/m8-2_014.upd firmware/patched/m8-2_014-stageN.upd --stage N
Needs: capstone (work/venv)
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m8_rawpatch import PATCHES as RAW_PATCHES, PXA_BASE, find_lump
import m8_wrapdng

STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
FLASHED_SHA = 'f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396'

# Regions a stage may change (vaddr ranges, end exclusive). FINDINGS "Image save path",
# "Reclaimable space", "Staged DNG builds".
REGIONS = {
    'header': (0x3CE48, 0x3CF20),   # RAW header block in the store routine 0x3CA58
    'hook':   (0x3C6A8, 0x3C6AC),   # last-block branch of the RAW producer (b 0x3C5EC)
    'ldimg':  (0x28AB0, 0x29104),   # reclaimed debug command, incl. literal pool
    'ext':    (0x3CFF8, 0x3CFFC),   # store routine's literal -> "RAW" (0xD6590)
    'memtest': (0x2ABD0, 0x2AF90),  # reclaimed debug command bf_memtest1, incl. literal pool
    'infokey': (0x44F68, 0x44F6C),  # application key handler, INFO outside service mode (bne 0x44F8C)
    'bfmem':  (0x2ABD0, 0x2B6E8),   # bf_memtest1/2/3, bf_checktrans + 2 helpers only bf_memtest2 calls
    'memtest12': (0x2ABD0, 0x2B338),  # bf_memtest1, the 2 helpers only bf_memtest2 calls, bf_memtest2
}

# tools/asm/m8_header.s at 0x3CE48 (46 instructions, replaces the stock block of the same size)
HEADER_TIFF = bytes.fromhex(
    '64301be5061097e7092097e7030097e770601be51032d1e51142d1e51252d1e520e4a0e1ff0000e222c4a0e1ff2002e2'
    '1fc00ce21fe00ee2bc01c6e1b421c6e1b6c1c6e1bee1c6e1b032c6e1b242c6e1b452c6e1490ca0e3490080e3b000c6e1'
    '2a20a0e3b220c6e10f3ca0e3cc3083e3b430c6e1050da0e3010080e3b600c6e1b8a0c6e1baa0c6e1bca0c6e1bea0c6e1'
    'b0a1c6e1b2a1c6e1b8a1c6e1baa1c6e1b6a2c6e1b8a2c6e1baa2c6e1e81081e24020a0e32c0086e2')
HEADER_TIFF_SHA = '4b8eda09af11190f7a0f65ba6830ee2f5ef2b07e31a62adf5a7b3d06d9b7ea23'
HEADER_STOCK_SHA = '93399af36122e9a734c63f84f258ba8933d85fd43a607d443c8f2e41f8bb4def'

# tools/asm/m8_dnghook.s at 0x28AB0 (stub, dng_hook, .Lcopy, literal pool; `tables` follows)
HOOK_CODE = bytes.fromhex(
    '0000a0e31eff2fe1f04f2de9858f8fe246cc84e234509ce51a12d5e5000051e36400001a42cc84e228109ce52c209ce5'
    '20a09ce5d0319fe5030051e1cc319f05030052015b00001ac4619fe501001ae3c0319f1503608610076086e0016046e0'
    'ac319fe5030056e15200003aa8319fe5030056e14f00008a009098e5020059e31f00000a010059e34a00001a0600a0e1'
    '5b1f8fe20820a0e30fe0a0e1470000ea080086e2421c84e2101081e23020a0e30fe0a0e1410000ead0042de9380086e2'
    '0d10a0e11020a0e30fe0a0e13b0000ea10d08de2800086e20510a0e10a2da0e30fe0a0e1350000ea30119fe5001091e5'
    '030c86e2022ca0e30fe0a0e12f0000ea230000ea042098e508b098e51c9088e28b1189e00600a0e10fe0a0e1270000ea'
    '01b05be20700004ab200d9e0b210d9e0b420d9e0000086e0011085e00fe0a0e11e0000eaf5ffffea0c0098e5000050e3'
    '0f00000a109088e2b616d5e1b820d9e10430a0e3b2c0d9e00c0051e18220a081013053e2faffff1a04202de5000086e0'
    '0d10a0e10220a0e30fe0a0e10b0000ea04d08de21f00c6e3021b86e23a0f07ee360f07ee200080e2010050e1faffff3a'
    '0000a0e39a0f07eef04fbde8c0f04ee2060050e11eff2f3102c080e000005ce11eff2f3130309fe5033086e003005ce1'
    '1eff2f8138309fe503005ce11eff2f81012052e20130d1540130c054fbffff5a1eff2fe14d3844554d503031101f0000'
    '570a0000e0446f0280e00300e0bd760230420d00e0c57602')
HOOK_CODE_SHA = 'f59560fd933c6510f5e85b96efd601d0f07742a45de1e03b31ae010f98e3902d'
HOOK_ENTRY = 0x28AB8                       # dng_hook
TABLES = 0x28AB0 + len(HOOK_CODE)          # `adr r8, tables` in dng_hook points here
LDIMG_STOCK_SHA = 'c28db4ffa67195ca427394eb3e21a6c2ff6e9a3a89a37ac0150f3e802019f6f5'
TEMPLATE_SHA = '5cb22fb2582678f4abacd6d0e85378179c3485f515d8251a3b0b683d1e564052'   # 902 bytes
UDF = bytes.fromhex('f000f0e7')            # permanently undefined: fills the unused rest of ldimg
MODE_DUMP, MODE_DNG = 1, 2

# tools/asm/m8_info.s at 0x2ABD0 (stub, info_open, literal pool)
INFO_CODE = bytes.fromhex(
    '0000a0e31eff2fe16f0c84e26c0080e20110a0e30fe0a0e12cf09fe5953b84e20120a0e38f20c3e56f0c84e26c0080e2'
    '0030a0e39930c0e54e0f80e20110a0e30fe0a0e104f09fe504f09fe5e88f0500600304008c4f0400')
INFO_CODE_SHA = 'cf764d835d8d5b43ac1bff1fbff14a2e9acdce8587203c76fcb4a7a30440adc3'
INFO_ENTRY = 0x2ABD8                       # info_open
MEMTEST_STOCK_SHA = 'f98abdafa6f9e473a2ba1c827600420fd762d0d266a94a92b3f96380a075a5b3'

# tools/asm/m8_infoscreens.s at 0x2ABD0 (stubs at the four command entries, screens, tables, strings)
SCREENS_CODE = bytes.fromhex(
    '0000a0e31eff2fe16f0c84e26c0080e20110a0e30fe0a0e1acf99fe5953b84e20120a0e38f20c3e56f0c84e26c0080e2'
    '0030a0e39930c0e54e0f80e28c199fe5001080e50110a0e30fe0a0e180f99fe580f99fe5ff1001e2690051e30500000a'
    '730051e31eff2f116c299fe5002080e57310a0e364f99fe5002090e560399fe5030052e1f7ffff1a58399fe5003080e5'
    '1cf093e504e02de504d04de200c08de50fe0a0e140f99fe504d08de204f09de404e02de504d04de200c0a0e300c08de5'
    '0fe0a0e124f99fe504d08de204f09de410402de910d04de200208de52348a0e108408de50338a0e12338a0e104308de5'
    '052d60e21e30a0e30fe0a0e1f0f89fe510d08de21080bde8f0402de90040a0e10150a0e10260a0e10370a0e10200a0e1'
    '2318a0e10fe0a0e1c8f89fe5000044e00510a0e10620a0e10730a0e10fe0a0e1e2ffffeaf080bde810402de9004090e5'
    '0000a0e30010a0e3052da0e31930a0e394c89fe50fe0a0e1c9ffffea8c089fe5000054e188289f0588289f150800a0e3'
    '0410a0e380389fe50fe0a0e1cfffffea78089fe5000054e174c89f0574c89f15120ea0e30fe0a0e1100000ea68089fe5'
    '000054e158c89f1558c89f054b0fa0e30fe0a0e1090000ea50089fe5000054e14c289f054c289f150800a0e3da10a0e3'
    '44389fe50fe0a0e1b8ffffea1080bde80a10a0e30620a0e30630a0e3a4ffffeaf04f2de901db4de220089fe5000090e5'
    '250a80e2a84190e5000054e38700000a034a84e2c04084e20d00a0e10010a0e3012ba0e30fe0a0e1f4f79fe5f4079fe5'
    '000090e5001090e50fe0a0e114f091e51e5b80e2185085e20da0a0e16b60a0e3a070a0e30480a0e10590a0e10000d8e5'
    '0110d8e50220d8e50000c9e50110c9e50220c9e54dc0a0e3900c0be096c0a0e391bc2be01dc0a0e392bc2be02bb4a0e1'
    '0130cbe30a3083e0b0c0d3e101c08ce2b0c0c3e10130c0e30a3083e0013c83e2b0c0d3e101c08ce2b0c0c3e10130c1e3'
    '0a3083e0023c83e2b0c0d3e101c08ce2b0c0c3e10130c2e30a3083e0033c83e2b0c0d3e101c08ce2b0c0c3e1068088e2'
    '039089e2017057e2d7ffff1a1e4d84e20f5d85e2016056e2d0ffff1a01b0a0e30060a0e37f0006e2000050e37f005013'
    '0300000a8600a0e1b0009ae10b0050e100b0a081016086e2020c56e3f4ffff3a0060a0e38670a0e1b7009ae14610a0e3'
    '910000e00b10a0e10fe0a0e1c8f69fe5460050e34600a083b7008ae1016086e2020c56e3f2ffff3a1f00a0e39110a0e3'
    '012ca0e3022082e24830a0e39cc69fe50fe0a0e13affffea2000a0e39210a0e3012ca0e34630a0e300c0a0e30fe0a0e1'
    '33ffffea0060a0e38670a0e1b7209ae1d81062e2200087e238369fe50fe0a0e132ffffea8670a0e1b7209ae1d81062e2'
    '210087e21c369fe50fe0a0e12bffffea016086e2800056e3eeffff3a018ca0e32c969fe50fe0a0e1100000ea028ca0e3'
    '20969fe50fe0a0e10c0000ea038ca0e314969fe50fe0a0e1080000ea050000ea0800a0e36410a0e300269fe500369fe5'
    '0fe0a0e11dffffea01db8de2f08fbde804e02de50060a0e3b8509ae1860088e0b0409ae1050054e10410a0210520a021'
    '0510a0310420a031022041e0012082e2d81061e2d80051e3d710a0230120a02306002de9060086e0200080e20930a0e1'
    '0fe0a0e1fdfeffea0600bde8060086e0210080e20930a0e10fe0a0e1f7feffea0450a0e1016086e2800056e3e2ffff3a'
    '04f09de40000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '0000a0e31eff2fe170402de930d04de20040a0e12c059fe5000090e5050a80e2c00080e2b01084e20fe0a0e118f59fe5'
    '000050e30600000a0800a0e36410a0e308259fe5f8349fe50fe0a0e1dbfeffea310000eac8608fe22850a0e3002096e5'
    '022086e00c00a0e30510a0e1e0349fe50fe0a0e1d1feffea083096e50328a0e12228a0e1022084e0010813e300209205'
    '0020d215020813e30400000a040052e30520a083ac149fe5022191e7022081e0041096e5011086e00d00a0e10fe0a0e1'
    '94f49fe54d0fa0e3021045e20d20a0e16c349fe50fe0a0e1c6feffea0c6086e2225085e2b00055e3dbffff3a0c00a0e3'
    '0510a0e164249fe554349fe50fe0a0e1aefeffea4d0fa0e3021045e250249fe52c349fe50fe0a0e1b6feffea30d08de2'
    '7080bde81a0300005a030000e40000001a03000051030000c80002001603000048030000c40000001603000036030000'
    'dd000100370300003d0300004a0300004f0300005b030000600300004cd30c0054d30c005cd30c0064d30c00d0a80900'
    '6c1e0d00b41e0d007ca409006cd30c00ac050600f0a8090024ac0200d8ac090068ad09006cad09006003040070d30c00'
    '74d30c0018ad0200d0ad020000000000000000004cd30c0054d30c005cd30c0064d30c00d0a809006c1e0d00b41e0d00'
    '7ca409006cd30c00ac050600f0a8090024ac0200d8ac090068ad09006cad09006003040070d30c0074d30c0018ad0200'
    'e8b002000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000a0e31eff2fe100000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000a0e31eff2fe14c6173742073686f740043616d6572612073746174730049'
    '4e464f3a207374617473202020205345543a20636c6f736500494e464f202f205345543a20636c6f7365004e6f20696d'
    '6167652079657400426f6479206461746120756e617661696c61626c650053686f74732074616b656e00426174746572'
    '790054656d7065726174757265004c656e7320636f6465004669726d7761726500322e303134202b20494e464f002564'
    '00257300256420c2b04300456d70747900416c6d6f737420656d7074790048616c6600416c6d6f73742066756c6c0046'
    '756c6c00556e6b6e6f776e00e88f05004cb20200600304008c4f0400b8d10e00681806004cb20200a4b20200408a0900'
    '348c0900ec9609000c9c0900452900004cb20200b8b40200c2b40200ffff03004cb20200ffff0000eb5a00004cb20200'
    '4cb20200cfb40200e9b402006d6b030020420d0034400b0088f9170028ab0c0065290000e7e10000473e0000df530000'
    'fbb40200ffff04001c420d0038e2030008b50200b294030034b20200ec940b0048b5020051b50200')
SCREENS_CODE_SHA = 'cc1e4c67e203f12b2ba60bafa37b2bda408adc847a5a0052c1ee081627442ca0'
SCREENS_ENTRY = 0x2ABD8                    # info_open
BFMEM_STOCK_SHA = '9fb0b6f7bcd3930a3bd1032ee66cd8c8ec9e9ad05ab807a50cc3936c3581582e'

# tools/asm/m8_infostats.s at 0x2ABD0 (stubs at bf_memtest1 / bf_memtest2 entries, Camera stats screen)
STATS_CODE = bytes.fromhex(
    '0000a0e31eff2fe16f0c84e26c0080e20110a0e30fe0a0e19cf39fe5953b84e20120a0e38f20c3e56f0c84e26c0080e2'
    '0030a0e39930c0e54e0f80e29b1f8fe2001080e50110a0e30fe0a0e16cf39fe56cf39fe5ff1001e2690051e373005113'
    '1eff2f115c239fe5002080e57310a0e354f39fe510402de910d04de200208de52348a0e108408de50338a0e12338a0e1'
    '04308de5052d60e21e30a0e30fe0a0e128f39fe510d08de21080bde8f0402de90040a0e10150a0e10260a0e10370a0e1'
    '0200a0e12318a0e10fe0a0e100f39fe5000044e00510a0e10620a0e10730a0e10fe0a0e1e2ffffeaf080bde804e02de5'
    '04d04de2dcc29fe500c08de50000a0e30010a0e3052da0e31930a0e30fe0a0e1c4f29fe504d08de20800a0e30410a0e3'
    '1e2e8fe2b4329fe50fe0a0e1d0ffffea0800a0e3da10a0e3a4229fe5a4329fe50fe0a0e1caffffea04f09de470402de9'
    '30d04de20040a0e18c029fe5000090e5050a80e2c00080e2b01084e20fe0a0e178f29fe5000050e30600000a0800a0e3'
    '6410a0e368229fe568329fe50fe0a0e1b7ffffea310000eac8608fe22850a0e3002096e5022086e00c00a0e30510a0e1'
    '44329fe50fe0a0e1adffffea083096e50328a0e12228a0e1022084e0010813e3002092050020d215020813e30400000a'
    '040052e30520a083a8108fe2022191e7022081e0041096e5011086e00d00a0e10fe0a0e1f4f19fe54d0fa0e3021045e2'
    '0d20a0e1dc319fe50fe0a0e1a2ffffea0c6086e2225085e2b00055e3dbffff3a0c00a0e30510a0e1c4219fe5b8319fe5'
    '0fe0a0e18affffea4d0fa0e3021045e2462f8fe29c319fe50fe0a0e192ffffea30d08de27080bde8d500000015010000'
    'e4000000d50000000c010000c8000200d100000003010000c4000000d1000000f1000000dd000100f2000000f8000000'
    '050100000a010000160100001b0100004cd30c0054d30c005cd30c0064d30c00d0a809006c1e0d00b41e0d007ca40900'
    '6cd30c00ac050600f0a8090024ac0200d8ac090068ad09006cad09006003040070d30c0074d30c00bcac02001cad0200'
    '000000000000000043616d65726120737461747300494e464f202f205345543a20636c6f736500426f64792064617461'
    '20756e617661696c61626c650053686f74732074616b656e00426174746572790054656d7065726174757265004c656e'
    '7320636f6465004669726d7761726500322e303134202b20494e464f00256400257300256420c2b04300456d70747900'
    '416c6d6f737420656d7074790048616c6600416c6d6f73742066756c6c0046756c6c00556e6b6e6f776e0000e88f0500'
    '600304008c4f0400b8d10e0068180600ec9609000c9c090045290000408a0900ffff0300e5ae02006d6b03001c420d00'
    '38e20300f7ae0200ffff0400b2940300ec940b0037af0200000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
    '0000a0e31eff2fe1')
STATS_CODE_SHA = '34a2ad9e6b0bca186aa853663f2816afd67b9fdea79f13e6970d9f1bfbb660fa'
STATS_ENTRY = 0x2ABD8                      # info_open
MEMTEST2_STOCK_SHA = 'c878ef6084a0127cd4c6277b0e87b71c7def6a19d480cd8389a667dede319907'


def template():
    t, slots = m8_wrapdng.build_template(m8_wrapdng.BLACK)
    if hashlib.sha256(t).hexdigest() != TEMPLATE_SHA:
        raise SystemExit('IFD template changed (m8_wrapdng.build_template); re-test and update TEMPLATE_SHA')
    return t, slots


def slot_table():
    """[(name, template offset, job offset, length)] for the per-shot slots held in S (job+4)."""
    _, slots = template()
    out = []
    for _, name, _, _, where in m8_wrapdng.SHOT_FIELDS:
        if where.startswith('S+'):          # AsShotNeutral (WB table) stays the template default
            off, n, _ = slots[name]
            out.append((name, off, 4 + int(where[2:], 16), n))
    return out


def black_table():
    """(template offset of the BlackLevel value, ISO thresholds, base black) -- same rule as
    m8_wrapdng.black_for_iso (FINDINGS "Black level per ISO")."""
    _, slots = template()
    off, n, typ = slots['BlackLevel']
    assert (n, typ) == (2, 3) and len(m8_wrapdng.BLACK_ISO_STEPS) == 4
    return off, m8_wrapdng.BLACK_ISO_STEPS, m8_wrapdng.BLACK


def tables(mode):
    t, _ = template()
    slots = slot_table()
    boff, steps, base = black_table()
    b = struct.pack('<4I', mode, len(t), len(slots), boff) + struct.pack('<6H', *steps, base, 0)
    b += b''.join(struct.pack('<4H', off, src, n, 0) for _, off, src, n in slots)
    return b + t


def ldimg_blob(mode):
    if hashlib.sha256(HOOK_CODE).hexdigest() != HOOK_CODE_SHA:
        raise SystemExit('HOOK_CODE does not match its SHA-256')
    lo, hi = REGIONS['ldimg']
    b = HOOK_CODE + tables(mode)
    b += b'\0' * (-len(b) % 4)
    if len(b) > hi - lo:
        raise SystemExit(f'ldimg overflow: {len(b)} > {hi - lo} bytes')
    return b + UDF * ((hi - lo - len(b)) // 4)


def memtest_blob():
    if hashlib.sha256(INFO_CODE).hexdigest() != INFO_CODE_SHA:
        raise SystemExit('INFO_CODE does not match its SHA-256')
    lo, hi = REGIONS['memtest']
    return INFO_CODE + UDF * ((hi - lo - len(INFO_CODE)) // 4)


def bfmem_blob():
    if hashlib.sha256(SCREENS_CODE).hexdigest() != SCREENS_CODE_SHA:
        raise SystemExit('SCREENS_CODE does not match its SHA-256')
    lo, hi = REGIONS['bfmem']
    if len(SCREENS_CODE) > hi - lo:
        raise SystemExit(f'bfmem overflow: {len(SCREENS_CODE)} > {hi - lo} bytes')
    return SCREENS_CODE + UDF * ((hi - lo - len(SCREENS_CODE)) // 4)


def memtest12_blob():
    if hashlib.sha256(STATS_CODE).hexdigest() != STATS_CODE_SHA:
        raise SystemExit('STATS_CODE does not match its SHA-256')
    lo, hi = REGIONS['memtest12']
    if len(STATS_CODE) > hi - lo:
        raise SystemExit(f'memtest12 overflow: {len(STATS_CODE)} > {hi - lo} bytes')
    return STATS_CODE + UDF * ((hi - lo - len(STATS_CODE)) // 4)


def bl(src, dst):
    return struct.pack('<I', 0xEB000000 | (((dst - src - 8) >> 2) & 0xFFFFFF))


def bne(src, dst):
    return struct.pack('<I', 0x1A000000 | (((dst - src - 8) >> 2) & 0xFFFFFF))


def pieces():
    """name -> (region, vaddr, old bytes or SHA-256 of them, new bytes)"""
    if hashlib.sha256(HEADER_TIFF).hexdigest() != HEADER_TIFF_SHA:
        raise SystemExit('HEADER_TIFF does not match its SHA-256')
    lo, hi = REGIONS['ldimg']
    return {
        'canary': ('header', 0x3CEA0, bytes.fromhex('0700a0e3'), bytes.fromhex('a500a0e3')),
        'tiff': ('header', 0x3CE48, HEADER_STOCK_SHA, HEADER_TIFF),
        'ldimg': ('ldimg', lo, LDIMG_STOCK_SHA, ldimg_blob(MODE_DNG)),
        'ldimg (dump)': ('ldimg', lo, LDIMG_STOCK_SHA, ldimg_blob(MODE_DUMP)),
        'hook': ('hook', 0x3C6A8, bytes.fromhex('cfffffea'), bl(0x3C6A8, HOOK_ENTRY)),
        'ext': ('ext', 0x3CFF8, struct.pack('<I', 0xD6590), struct.pack('<I', 0xD6570)),
        'info': ('memtest', REGIONS['memtest'][0], MEMTEST_STOCK_SHA, memtest_blob()),
        'info key': ('infokey', 0x44F68, bytes.fromhex('0700001a'), bne(0x44F68, INFO_ENTRY)),
        'screens': ('bfmem', REGIONS['bfmem'][0], BFMEM_STOCK_SHA, bfmem_blob()),
        'screens key': ('infokey', 0x44F68, bytes.fromhex('0700001a'), bne(0x44F68, SCREENS_ENTRY)),
        'stats': ('memtest12', REGIONS['memtest12'][0], MEMTEST2_STOCK_SHA, memtest12_blob()),
        'stats key': ('infokey', 0x44F68, bytes.fromhex('0700001a'), bne(0x44F68, STATS_ENTRY)),
    }


# stage -> (title, pieces)
STAGES = {
    1: ('canary: RAW header u16[3] 7 -> 0xA5', ['canary']),
    2: ('dng_hook + template in ldimg, hook off (idle test); canary kept', ['canary', 'ldimg']),
    3: ('hook on, job metadata dump into the trailing row; canary kept', ['canary', 'ldimg (dump)', 'hook']),
    4: ('hook on, TIFF header + IFD template: 14-bit DNG content, still named .RAW', ['tiff', 'ldimg', 'hook']),
    5: ('as stage 4, files named .DNG', ['tiff', 'ldimg', 'hook', 'ext']),
    6: ('as stage 4, plus INFO in shooting mode opens Body Debug Data', ['tiff', 'ldimg', 'hook', 'info', 'info key']),
    7: ('as stage 4, plus INFO screens: Last shot (histogram), Camera stats',
        ['tiff', 'ldimg', 'hook', 'screens', 'screens key']),
    8: ('as stage 4, plus INFO shows Camera stats', ['tiff', 'ldimg', 'hook', 'stats', 'stats key']),
    10: ('Option 1 (RAW patch only, no DNG) plus INFO shows Camera stats', ['stats', 'stats key']),
}
KNOWN_OUTPUTS = {  # stage builds whose emulator run passed (see FINDINGS)
    '3f84b34a225aeebe3f5f18cb658d4b14028d49d98e1fd1d1366ccf25a5830e66':
        'stage 1, m8_savetest 32/0; flashed and camera-tested 2026-10-20',
    '3b451b4d7da62621179995ba11fa5962f347c7aa9d82e99a9e156e7801ee6e25':
        'stage 4, first version (date slot S+0x20, wrong); flashed 2026-10-20, Lightroom opens its files',
    '59aff4a35f5c8fea4ca1fc8ab962ac3e0ac171131bd82410cf67c9231665273c':
        'stage 4, BlackLevel 92 at all ISOs; flashed and camera-tested 2026-10-20 (superseded)',
    'd9a94feb9fba2681f46ba0f1e78ad75ed1e9383c088b0b0e3cba0f3b40333e66':
        'stage 5, BlackLevel 92; flashed 2026-10-20, rolled back: in-camera review cannot show the JPG',
    'ff6b3f63a0f2a8c7a6231cc98e53c6b977c63734a2ef16ea4a8e30a56d8d45e9': 'stage 2, m8_savetest 150/0 (2026-10-21); not flashed',
    '77e35e778e5b945bc5f119ab399803b40eb5628a6b27f352717ea07059e4d2ca': 'stage 3, m8_savetest 150/0 (2026-10-21); not flashed',
    '55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c': 'stage 4, BlackLevel per ISO, m8_savetest 150/0; flashed and camera-tested 2026-10-21 (current)',
    '00ed8542ed2949d873d5c084024c5e5fe4a522a01a3d878462763c6f30fc53ce': 'stage 5, BlackLevel per ISO, m8_savetest 150/0 (2026-10-21); not flashed',
    'f8e8138d9b05cc546d76f7d1a2f5a7c6c7d223e9f798032155bb4c2fb656b07c':
        'stage 6, INFO -> Body Debug Data; m8_infotest 14/0, m8_savetest 49/0; flashed and camera-tested 2026-10-23',
    'c88e77c0fc57d98f022c81fdad8e73d23430b591d344c223b84ac6364d61dae4':
        'stage 7, INFO screens; m8_infotest 26/0, m8_inforender 13/0, m8_savetest 49/0; flashed 2026-10-23: '
        'histogram showed the first shot after later shots (review buffer); replaced by stage 8',
    '32e6854ec0bc451667ef4f8f6b40dfb4c8af406a43db84e94b90abeb380408f8':
        'stage 8, INFO -> Camera stats; m8_infotest 38/0, m8_inforender 7/0, m8_savetest 49/0; flashed and camera-tested 2026-10-23',
    'fa4ae63a22e2df9749e989ccc570808ac24dabe1a3992593c4c37d27ad6c1c43':
        'stage 10, Option 1 + INFO Camera stats; m8_infotest 50/0, m8_inforender 7/0, m8_savetest 39/0 (2026-10-23); not flashed',
}


def stage_regions(stage):
    p = pieces()
    return {p[name][0] for name in STAGES[stage][1]}


def _apply(buf, pos, changes):
    for name, va, old, new in changes:
        off = pos + va - PXA_BASE
        cur = bytes(buf[off:off + len(new)])
        ok = hashlib.sha256(cur).hexdigest() == old if isinstance(old, str) else cur == old
        if not ok:
            raise SystemExit(f'{name}: unexpected original bytes at 0x{va:X}')
        buf[off:off + len(new)] = new


def flashed_file(stock):
    """Stock .upd bytes -> the flashed persistent-RAW build (P1-P3), verified by hash."""
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA:
        raise SystemExit('input is not the stock m8-2_014.upd (SHA-256 mismatch)')
    buf = bytearray(stock)
    pos, _ = find_lump(buf, b'PXA')
    _apply(buf, pos, RAW_PATCHES)
    if hashlib.sha256(buf).hexdigest() != FLASHED_SHA:
        raise SystemExit('RAW-patched base does not match the flashed build f6589c41')
    return bytes(buf)


def stage_file(stock, stage):
    """Stock .upd bytes -> (flashed build, stage build), region check passed."""
    if stage not in STAGES:
        raise SystemExit(f'no stage {stage}')
    p = pieces()
    names = STAGES[stage][1]
    regions = [p[n][0] for n in names]
    if len(set(regions)) != len(regions):
        raise SystemExit(f'stage {stage}: two pieces in one region')
    base = flashed_file(stock)
    buf = bytearray(base)
    pos, size = find_lump(buf, b'PXA')
    _apply(buf, pos, [(n, *p[n][1:]) for n in names])
    bad = region_violations(base, bytes(buf), pos, size, set(regions))
    if bad:
        raise SystemExit('changes outside the declared regions: ' + ', '.join(bad))
    return base, bytes(buf)


def changed_ranges(a, b):
    """[(start, end)] of differing bytes between two equal-length buffers."""
    assert len(a) == len(b), 'size changed'
    out, i, n = [], 0, len(a)
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def region_violations(base, new, pos, size, regions):
    """File-level diff vs the flashed build; every changed byte must lie in a declared region."""
    allowed = [REGIONS[r] for r in regions]
    bad = []
    for s, e in changed_ranges(base, new):
        if not (pos <= s and e <= pos + size):
            bad.append(f'file 0x{s:X}-0x{e:X} (outside PXA lump)')
            continue
        va, vb = PXA_BASE + s - pos, PXA_BASE + e - pos
        if not any(lo <= va and vb <= hi for lo, hi in allowed):
            bad.append(f'0x{va:X}-0x{vb:X}')
    return bad


def pxa_of(upd):
    pos, size = find_lump(upd, b'PXA')
    return upd[pos:pos + size]


def show(base, new):
    """Disassemble every changed instruction word, old and new, at its real address; the data
    part of ldimg (tables, template, fill) is summarised."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    pa, pb = pxa_of(base), pxa_of(new)
    words = sorted({(s & ~3) + k for s, e in changed_ranges(pa, pb) for k in range(0, e - (s & ~3), 4)})
    lo, hi = REGIONS['ldimg']
    data = [o for o in words if TABLES <= PXA_BASE + o < hi]
    fill = [o for o in words if pb[o:o + 4] == UDF and not TABLES <= PXA_BASE + o < hi]
    for o in words:
        va = PXA_BASE + o
        if TABLES <= va < hi or o in fill:
            continue
        old = next(md.disasm(pa[o:o + 4], va), None)
        neu = next(md.disasm(pb[o:o + 4], va), None)
        fmt = lambda i, raw: f'{raw.hex()}  {i.mnemonic} {i.op_str}' if i else f'{raw.hex()}  (data)'
        print(f'  0x{va:X}: {fmt(old, pa[o:o + 4])}  ->  {fmt(neu, pb[o:o + 4])}')
    if data:
        b = pb[TABLES - PXA_BASE:hi - PXA_BASE]
        mode, tlen, nslots, boff = struct.unpack_from('<4I', b)
        used = 28 + 8 * nslots + tlen
        print(f'  0x{TABLES:X}-0x{hi:X}: data -- mode {mode}, {nslots} slots, template {tlen} bytes '
              f'(sha {hashlib.sha256(b[28 + 8 * nslots:used]).hexdigest()[:8]}), '
              f'BlackLevel at template+{boff}, ISO steps {struct.unpack_from("<4H", b, 16)}, '
              f'{hi - TABLES - used} bytes padding/undefined fill')
    if fill:
        print(f'  {len(fill)} more word(s) set to undefined fill (udf) outside the ldimg tables, '
              f'0x{PXA_BASE + fill[0]:X}-0x{PXA_BASE + fill[-1] + 4:X}')


def main():
    args = [a for a in sys.argv[1:]]
    if '--stage' not in args or len(args) != 4:
        raise SystemExit(__doc__)
    i = args.index('--stage')
    stage = int(args[i + 1])
    del args[i:i + 2]
    src, dst = args
    if stage not in STAGES:
        raise SystemExit(f'no stage {stage}')
    print(f'stage {stage}: {STAGES[stage][0]}')
    base, new = stage_file(open(src, 'rb').read(), stage)
    print('base: flashed persistent-RAW build', FLASHED_SHA[:8], '; pieces:', ', '.join(STAGES[stage][1]))
    show(base, new)
    n = sum(e - s for s, e in changed_ranges(base, new))
    print(f'differs from the flashed build in {n} byte(s), all inside declared regions '
          f'{sorted(stage_regions(stage))}; other lumps identical')
    open(dst, 'wb').write(new)
    sha = hashlib.sha256(new).hexdigest()
    print('wrote', dst, 'sha256', sha)
    print('known build:', KNOWN_OUTPUTS.get(sha, 'no (run m8_savetest.py before flashing)'))


if __name__ == '__main__':
    main()
