#include "induction_model.h"
#include "ws2812_spi.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void test_leds(void)
{
    induction_state_t s; induction_init(&s); s.mode=ST_ON;
    uint8_t pixels[36],previous[36]={0};
    for (unsigned level=0;level<=9;level++) {
        s.level=level; induction_pixels(&s,96,pixels);
        unsigned count=0;
        for (unsigned i=0;i<12;i++) {
            count+=pixels[i*3+1]>0;
            assert(pixels[i*3+1]>=previous[i*3+1]);
            assert(pixels[i*3+1]<=96);
            assert(pixels[i*3]==pixels[i*3+1]/8);
            assert(pixels[i*3+2]==0);
        }
        unsigned expected=level==0 ? 0:level<=2 ? 3:level<=4 ? 6:level<=6 ? 9:12;
        assert(count==expected);
        if (level==1) for (unsigned i=0;i<12;i++) assert((pixels[3*i+1]>0)==(i%4==0));
        if (level==3) for (unsigned i=0;i<12;i++) assert((pixels[3*i+1]>0)==(i%2==0));
        if (level==5) for (unsigned i=0;i<12;i++) assert((pixels[3*i+1]>0)==(i%4!=3));
        memcpy(previous,pixels,36);
    }
    for (unsigned mode=ST_OFF;mode<=ST_OVERHEATED;mode++) if(mode!=ST_ON) {
        s.mode=mode; induction_pixels(&s,255,pixels);
        for(unsigned i=0;i<36;i++) assert(pixels[i]==0);
    }
}
static void test_spi_waveform(void)
{
    uint8_t pixels[INDUCTION_LEDS*3],frame[WS2812_SPI_FRAME_BYTES];
    for (unsigned value=0;value<256;value++) {
        memset(pixels,value,sizeof(pixels));
        ws2812_spi_encode(pixels,frame);
        for (unsigned i=0;i<WS2812_SPI_RESET_BYTES;i++) {
            assert(frame[i]==0);
            assert(frame[WS2812_SPI_RESET_BYTES+WS2812_SPI_DATA_BYTES+i]==0);
        }
        for (unsigned led_byte=0;led_byte<sizeof(pixels);led_byte++) {
            unsigned decoded=0;
            for (unsigned bit=0;bit<8;bit++) {
                uint8_t byte=frame[WS2812_SPI_RESET_BYTES+led_byte*4+bit/2];
                unsigned symbol=(bit%2==0 ? byte >> 4 : byte) & 15;
                assert(symbol==0x8 || symbol==0xe);
                decoded=(decoded << 1) | (symbol==0xe);
            }
            assert(decoded==value);
        }
    }
    /* A mixed frame checks GRB byte order and prevents cross-pixel mixing. */
    for (unsigned i=0;i<sizeof(pixels);i++) pixels[i]=(uint8_t)(i*7);
    ws2812_spi_encode(pixels,frame);
    for (unsigned i=0;i<sizeof(pixels);i++) {
        unsigned decoded=0;
        for (unsigned bit=0;bit<8;bit++) {
            uint8_t byte=frame[WS2812_SPI_RESET_BYTES+i*4+bit/2];
            unsigned symbol=(bit%2==0 ? byte >> 4 : byte) & 15;
            decoded=(decoded << 1) | (symbol==0xe);
        }
        assert(decoded==pixels[i]);
    }
    assert(WS2812_SPI_FRAME_BYTES==400);
}
static void test_control(void)
{
    induction_state_t s; induction_init(&s);
    assert(!strcmp(s.publisher,"user") && s.command_id[0]==0);
    induction_command_t cmd={.type=CMD_ON,.id="test-1"};
    assert(induction_apply(&s,&cmd,false,5,1000000));
    assert(s.mode==ST_ON && s.level==5 && !strcmp(s.publisher,"api"));
    memset(cmd.id,'x',100);
    strcpy(cmd.id+100,"/한글:명령.1");
    assert(induction_apply(&s,&cmd,false,5,1000000));
    assert(!strcmp(s.command_id,cmd.id));
    induction_tick(&s,4000000); assert(s.active_sec==3);
    cmd.type=CMD_LEVEL;cmd.level=0;
    induction_state_t before=s;
    assert(!induction_apply(&s,&cmd,false,5,4000000));
    assert(!memcmp(&s,&before,sizeof(s)));
    assert(induction_apply(&s,&cmd,true,5,4000000)); assert(s.mode==ST_ON && s.level==0);
    cmd.level=10;assert(!induction_apply(&s,&cmd,true,5,4000000));
    induction_temperature(&s,151,true,150,60,5000000);
    assert(s.mode==ST_OVERHEATED && s.alarm && s.level==0);
    cmd.type=CMD_ON;cmd.level=5;assert(!induction_apply(&s,&cmd,false,5,6000000));
    cmd.type=CMD_OFF;assert(induction_apply(&s,&cmd,false,5,6000000));
    assert(s.mode==ST_OVERHEATED && s.alarm);
    induction_temperature(&s,NAN,true,150,60,7000000);
    assert(s.mode==ST_OVERHEATED && !s.temperature_valid);
    induction_temperature(&s,60,true,150,60,8000000);
    assert(s.mode==ST_OFF && !s.alarm);
    cmd.type=CMD_LEVEL;cmd.level=7;
    assert(induction_apply(&s,&cmd,false,5,9000000)); assert(s.mode==ST_ON && s.level==7);
    induction_temperature(&s,50,true,150,60,9000000);
    cmd.type=CMD_OFF;assert(induction_apply(&s,&cmd,true,5,10000000));
    assert(s.mode==ST_COOLING && s.level==0);
    induction_temperature(&s,26,true,150,60,11000000);assert(s.mode==ST_OFF);
    induction_tick(&s,14000000);assert(!s.temperature_valid);
    induction_init(&s);cmd.type=CMD_ON;cmd.level=9;
    assert(induction_apply(&s,&cmd,true,5,0));
    /* Level and elapsed time cannot manufacture a sensor reading. */
    float initial_temperature=s.temperature;
    induction_tick(&s,30000000);
    assert(s.mode==ST_ON && !s.temperature_valid);
    assert(s.temperature==initial_temperature && s.active_sec==30);
}
int main(void) { test_leds(); test_spi_waveform(); test_control(); puts("PASS: LED masks/brightness, SPI waveform, commands, overheat latch, sensor validity"); }
