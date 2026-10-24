/* zstd's decoder for the gift host (vendor/zstd): a console compresses most of its Pia datagrams.
   One context, taken once: it needs 38,464 contiguous bytes, which a fragmented heap may lack later. */
#include <stdint.h>
#include <stdlib.h>

#define ZSTD_STATIC_LINKING_ONLY
#include "zstd.h"

#include "gift.h"

static ZSTD_DCtx *s_context;

bool gift_zstd_ready(void)
{
    if (!s_context) s_context = ZSTD_createDCtx();
    return s_context != NULL;
}

size_t gift_zstd_decompress(const uint8_t *in, size_t length, uint8_t *out, size_t capacity)
{
    if (!gift_zstd_ready()) return SIZE_MAX;
    /* Pia pads after the frame: decode the frame only. */
    const size_t frame = ZSTD_findFrameCompressedSize(in, length);
    if (ZSTD_isError(frame)) return SIZE_MAX;
    const size_t written = ZSTD_decompressDCtx(s_context, out, capacity, in, frame);
    return ZSTD_isError(written) ? SIZE_MAX : written;
}
