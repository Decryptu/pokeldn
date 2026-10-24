# zstd 1.5.6's decoder, unmodified (facebook/zstd v1.5.6, lib/): the board decodes a console's
# compressed Pia datagrams (docs/hardware_esp32.md, Portable beacon). Re-vendor, never edit.
idf_component_register(
    SRCS "lib/common/debug.c" "lib/common/entropy_common.c" "lib/common/error_private.c"
         "lib/common/fse_decompress.c" "lib/common/xxhash.c" "lib/common/zstd_common.c"
         "lib/decompress/huf_decompress.c" "lib/decompress/zstd_ddict.c"
         "lib/decompress/zstd_decompress.c" "lib/decompress/zstd_decompress_block.c"
    INCLUDE_DIRS "lib"
    PRIV_INCLUDE_DIRS "lib/common" "lib/decompress")
# A 1 KB literal buffer keeps the decoder context at 38,464 bytes; the default 64 KB one would not
# fit beside Wi-Fi. No assembly, no threads.
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    ZSTD_DISABLE_ASM=1 ZSTD_MULTITHREAD=0 ZSTD_DECODER_INTERNAL_BUFFER=1024)
target_compile_options(${COMPONENT_LIB} PRIVATE -O2)
