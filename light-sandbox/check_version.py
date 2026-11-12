import pefile
p = r'C:\Windows\System32\termsrv.dll'
pe = pefile.PE(p)
# 读取 VS_FIXEDFILEINFO
if hasattr(pe, 'VS_FIXEDFILEINFO'):
    for ffi in pe.VS_FIXEDFILEINFO:
        ms = ffi.FileVersionMS
        ls = ffi.FileVersionLS
        major = (ms >> 16) & 0xffff
        minor = ms & 0xffff
        build = (ls >> 16) & 0xffff
        patch = ls & 0xffff
        print('PE内嵌真实文件版本: %d.%d.%d.%d' % (major, minor, build, patch))
        ms2 = ffi.ProductVersionMS
        ls2 = ffi.ProductVersionLS
        print('PE内嵌产品版本: %d.%d.%d.%d' % ((ms2>>16)&0xffff, ms2&0xffff, (ls2>>16)&0xffff, ls2&0xffff))
# 字符串版本信息
if hasattr(pe, 'FileInfo'):
    for finfo in pe.FileInfo:
        for entry in finfo:
            if hasattr(entry, 'StringTable'):
                for st in entry.StringTable:
                    for k, v in st.entries.items():
                        print('  %s = %s' % (k.decode(), v.decode()))
