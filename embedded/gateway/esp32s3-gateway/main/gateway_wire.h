#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define GW_PAYLOAD_MAX 1024
#define GW_HEADER_SIZE 16
#define GW_FRAME_MAX (GW_HEADER_SIZE + GW_PAYLOAD_MAX)
enum { GW_HELLO=1, GW_READY, GW_TIME, GW_PONG, GW_OPEN, GW_OPEN_OK,
       GW_CLOSE, GW_DATA, GW_ACK };
typedef struct {
    uint32_t stream;
    uint16_t size;
    uint8_t type;
    uint8_t data[GW_PAYLOAD_MAX];
} gw_frame_t;
typedef struct { uint8_t data[GW_FRAME_MAX]; size_t used; } gw_parser_t;
typedef void (*gw_receive_fn)(const gw_frame_t *frame, void *ctx);
size_t gw_encode(uint8_t *out, const gw_frame_t *frame);
void gw_feed(gw_parser_t *parser, const void *data, size_t size, gw_receive_fn receive, void *ctx);
uint64_t gw_u64(const uint8_t *p);
/* Pure NTP reply builder: unix time in microseconds; no invented time. */
bool gw_ntp_reply(const uint8_t *request, size_t size, int64_t unix_us, uint8_t out[48]);
