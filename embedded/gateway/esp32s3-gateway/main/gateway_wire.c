#include "gateway_wire.h"
#include <string.h>

static const uint8_t magic[4]={'H','V','U','1'};
static uint32_t u32(const uint8_t *p)
{ return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3]; }
static void put32(uint8_t *p, uint32_t v)
{ p[0]=v>>24; p[1]=v>>16; p[2]=v>>8; p[3]=v; }
uint64_t gw_u64(const uint8_t *p) { return (uint64_t)u32(p)<<32 | u32(p+4); }
static uint32_t crc_update(uint32_t crc, const uint8_t *data, size_t size)
{
    for (size_t i=0; i<size; ++i) {
        crc ^= data[i];
        for (int bit=0; bit<8; ++bit) crc=(crc>>1) ^ (0xedb88320u & (0u-(crc&1)));
    }
    return crc;
}
static uint32_t checksum(const uint8_t *header, const uint8_t *data, size_t size)
{ return crc_update(crc_update(0xffffffffu,header,12),data,size)^0xffffffffu; }
size_t gw_encode(uint8_t *out, const gw_frame_t *frame)
{
    if (frame->size > GW_PAYLOAD_MAX) return 0;
    memcpy(out,magic,4); out[4]=frame->type; out[5]=0;
    out[6]=frame->size>>8; out[7]=frame->size;
    put32(out+8,frame->stream);
    memcpy(out+16,frame->data,frame->size);
    put32(out+12,checksum(out,frame->data,frame->size));
    return 16+frame->size;
}
void gw_feed(gw_parser_t *p, const void *data, size_t size, gw_receive_fn receive, void *ctx)
{
    const uint8_t *bytes=data;
    for (size_t i=0; i<size; ++i) {
        p->data[p->used++]=bytes[i];
        for (;;) {
            if (p->used<4) break;
            if (memcmp(p->data,magic,4)) goto discard;
            if (p->used<16) break;
            size_t length=(size_t)p->data[6]<<8 | p->data[7];
            if (p->data[5] || length>GW_PAYLOAD_MAX) goto discard;
            if (p->used<16+length) break;
            if (u32(p->data+12)!=checksum(p->data,p->data+16,length)) goto discard;
            gw_frame_t frame={.stream=u32(p->data+8),.type=p->data[4],.size=length};
            memcpy(frame.data,p->data+16,length);
            p->used=0;
            receive(&frame,ctx);
            break;
discard:
            memmove(p->data,p->data+1,--p->used);
        }
    }
}
static void ntp_time(uint8_t *out, int64_t us)
{
    put32(out,(uint32_t)(us/1000000+INT64_C(2208988800)));
    put32(out+4,(uint32_t)(((uint64_t)(us%1000000)<<32)/1000000));
}
bool gw_ntp_reply(const uint8_t *request, size_t size, int64_t unix_us, uint8_t out[48])
{
    if (size<48 || (request[0]&7)!=3 || ((request[0]>>3)&7)<3 ||
        ((request[0]>>3)&7)>4 || unix_us<INT64_C(1704067200000000)) return false;
    memset(out,0,48);
    out[0]=(request[0]&0x38)|4; out[1]=2; out[2]=6; out[3]=(uint8_t)-10;
    out[10]=1; /* Small nonzero dispersion, 1/256 second. */
    memcpy(out+12,"LOCL",4);
    ntp_time(out+16,unix_us);
    memcpy(out+24,request+40,8);
    ntp_time(out+32,unix_us);
    ntp_time(out+40,unix_us);
    return true;
}
