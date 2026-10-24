# zstd

The decoder of [zstd](https://github.com/facebook/zstd) 1.5.6 (`lib/common/`, `lib/decompress/`,
`lib/zstd.h`, `lib/zstd_errors.h`), byte for byte as tagged `v1.5.6`, under its BSD licence
(`LICENSE`). The radio firmware builds it as an ESP-IDF component (`firmware/esp32/CMakeLists.txt`)
and `tests/test_esp32_gift.py` compiles the same files.
