#include "sdkconfig.h"
#include "app.h"
#include "induction_hw.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

QueueHandle_t app_commands, app_acks;
EventGroupHandle_t app_network;
static SemaphoreHandle_t s_mutex;
static QueueHandle_t s_temperature, s_sounds;
static induction_state_t s_shared;
static const char *TAG = "induction";
typedef struct { float value; bool valid; } temperature_sample_t;
typedef struct { bool on, alarm; } sound_request_t;
typedef struct { int raw, stable; int64_t changed; } button_t;
#define ACK_CACHE_COUNT 64
static command_ack_t *s_cache;
static unsigned s_cache_used, s_cache_next;
induction_state_t app_snapshot(void)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    induction_state_t copy = s_shared;
    xSemaphoreGive(s_mutex);
    return copy;
}
static void share_state(const induction_state_t *state)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_shared = *state;
    xSemaphoreGive(s_mutex);
}
static bool pressed(button_t *b, int raw, int active, int64_t now)
{
    if (raw != b->raw) { b->raw=raw; b->changed=now; }
    if (raw != b->stable && now-b->changed >= 40000) {
        b->stable=raw;
        return raw == active;
    }
    return false;
}
static void control_task(void *arg)
{
    induction_input_init();
    static induction_state_t s;
    induction_init(&s);
    button_t touch = {.raw=gpio_get_level(CONFIG_INDUCTION_TOUCH_GPIO)};
    button_t sw = {.raw=gpio_get_level(CONFIG_INDUCTION_ENCODER_SW_GPIO)};
    touch.stable=touch.raw; sw.stable=sw.raw;
    int previous_a=gpio_get_level(CONFIG_INDUCTION_ENCODER_A_GPIO);
    int64_t tick_at=esp_timer_get_time(), local_at=0;
    share_state(&s);
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        int64_t now=esp_timer_get_time();
        device_state_t old_mode=s.mode;
        bool old_alarm=s.alarm, was_valid=s.temperature_valid;
        bool local=false;
        static induction_command_t cmd;
        memset(&cmd,0,sizeof(cmd));
        bool touch_event=pressed(&touch,gpio_get_level(CONFIG_INDUCTION_TOUCH_GPIO),1,now);
        bool sw_event=pressed(&sw,gpio_get_level(CONFIG_INDUCTION_ENCODER_SW_GPIO),0,now);
        int a=gpio_get_level(CONFIG_INDUCTION_ENCODER_A_GPIO);
        if (touch_event) {
            cmd.type=s.mode == ST_ON ? CMD_OFF : CMD_ON;
            local=true;
        } else if (s.mode == ST_ON && sw_event) {
            cmd.type=CMD_LEVEL; cmd.level=0; local=true;
        } else if (s.mode == ST_ON && a && !previous_a) {
            int next=(int)s.level + (gpio_get_level(CONFIG_INDUCTION_ENCODER_B_GPIO) ? -1 : 1);
            if (next>=0 && next<=9 && next!=(int)s.level) {
                cmd.type=CMD_LEVEL; cmd.level=next; local=true;
            }
        }
        previous_a=a;
        if (local) {
            induction_apply(&s,&cmd,true,CONFIG_INDUCTION_DEFAULT_LEVEL,now);
            local_at=now; /* Reject older queued remote increases after local input. */
        }
        temperature_sample_t sample;
        if (xQueueReceive(s_temperature,&sample,0)==pdTRUE)
            induction_temperature(&s,sample.value,sample.valid,
                CONFIG_INDUCTION_OVERHEAT_ENTER,CONFIG_INDUCTION_OVERHEAT_EXIT,now);
        if (now-tick_at>=100000) {
            induction_tick(&s,now);
            tick_at=now;
        }
        /* No remote command may block controls waiting for the network/ACK queue. */
        static command_request_t request;
        if (!local && uxQueueSpacesAvailable(app_acks)>0 &&
            xQueueReceive(app_commands,&request,0)==pdTRUE) {
            static command_ack_t ack;
            memset(&ack,0,sizeof(ack));
            ack.command=request.command;
            bool duplicate=false;
            for (unsigned i=0;i<s_cache_used;i++) {
                if (!strcmp(s_cache[i].command.id,request.command.id)) {
                    ack=s_cache[i]; duplicate=true; break;
                }
            }
            if (!duplicate) {
                bool stale_local=request.received_us<=local_at && request.command.type!=CMD_OFF;
                ack.result=!stale_local && induction_apply(&s,&request.command,false,
                    CONFIG_INDUCTION_DEFAULT_LEVEL,now) ? ACK_APPLIED : ACK_REJECTED;
                ack.state=s;
                ack.applied_at=time(NULL);
                s_cache[s_cache_next]=ack;
                s_cache_next=(s_cache_next+1)%ACK_CACHE_COUNT;
                if (s_cache_used<ACK_CACHE_COUNT) s_cache_used++;
            }
            configASSERT(xQueueSend(app_acks,&ack,0)==pdTRUE);
        }
        if (was_valid != s.temperature_valid) s.revision++;
        if ((old_mode==ST_ON)!=(s.mode==ST_ON) || old_alarm!=s.alarm) {
            sound_request_t sound={.on=s.mode==ST_ON,.alarm=s.alarm};
            xQueueOverwrite(s_sounds,&sound);
        }
        share_state(&s);
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(5));
    }
}
static void led_task(void *arg)
{
    induction_led_init(); /* Allocate RMT interrupt on Core 1, away from Wi-Fi. */
    uint8_t previous[INDUCTION_LEDS*3]={0}, pixels[INDUCTION_LEDS*3];
    TickType_t wake=xTaskGetTickCount();
    for (;;) {
        induction_state_t s=app_snapshot();
        induction_pixels(&s,CONFIG_INDUCTION_LED_MAX_BRIGHTNESS,pixels);
        if (memcmp(previous,pixels,sizeof(pixels))) {
            esp_err_t err=induction_led_write(pixels);
            if (err==ESP_OK) memcpy(previous,pixels,sizeof(pixels));
            else ESP_LOGW(TAG,"LED output: %s",esp_err_to_name(err));
        }
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(10));
    }
}
static void peripheral_task(void *arg)
{
    induction_io_init();
    int64_t sample_at=0,screen_at=0,draw_at=0;
    static induction_state_t previous;
    bool previous_online=false,first=true;
    for (;;) {
        int64_t now=esp_timer_get_time();
        if (now>=sample_at) {
            temperature_sample_t sample={0};
            sample.valid=induction_read_temperature(&sample.value)==ESP_OK && isfinite(sample.value);
            xQueueOverwrite(s_temperature,&sample);
            sample_at=now+500000;
        }
        if (now>=screen_at) {
            induction_state_t s=app_snapshot();
            bool online=(xEventGroupGetBits(app_network)&NET_ONLINE)!=0;
            if (first || now>=draw_at || s.revision!=previous.revision || s.level!=previous.level ||
                s.temperature_valid!=previous.temperature_valid ||
                (int)s.temperature!=(int)previous.temperature || previous_online!=online) {
                induction_io_update(&s,online);
                previous=s; previous_online=online; first=false; draw_at=now+3000000;
            }
            screen_at=now+100000;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
static void sound_task(void *arg)
{
    induction_sound_init();
    sound_request_t request;
    for (;;) if (xQueueReceive(s_sounds,&request,portMAX_DELAY)==pdTRUE)
        induction_sound(request.on,request.alarm);
}
static void validate_pins(void)
{
    int pins[]={CONFIG_INDUCTION_LED_GPIO,CONFIG_INDUCTION_TOUCH_GPIO,
        CONFIG_INDUCTION_ENCODER_A_GPIO,CONFIG_INDUCTION_ENCODER_B_GPIO,
        CONFIG_INDUCTION_ENCODER_SW_GPIO,CONFIG_INDUCTION_BUZZER_GPIO,
        CONFIG_INDUCTION_SDA_GPIO,CONFIG_INDUCTION_SCL_GPIO};
    for (unsigned i=0;i<sizeof(pins)/sizeof(pins[0]);i++) {
        /* Flash/PSRAM and USB pins must remain reserved on N16R8. */
        configASSERT(GPIO_IS_VALID_OUTPUT_GPIO(pins[i]));
        configASSERT(!(pins[i]>=26 && pins[i]<=37));
        configASSERT(pins[i]!=19 && pins[i]!=20);
        configASSERT(pins[i]!=0 && pins[i]!=3 && pins[i]!=45 && pins[i]!=46);
        for (unsigned j=0;j<i;j++) configASSERT(pins[i]!=pins[j]);
    }
    configASSERT(CONFIG_INDUCTION_OVERHEAT_EXIT < CONFIG_INDUCTION_OVERHEAT_ENTER);
}
void app_main(void)
{
    validate_pins();
    s_mutex=xSemaphoreCreateMutex();
    app_commands=xQueueCreate(COMMAND_DEPTH,sizeof(command_request_t));
    app_acks=xQueueCreate(ACK_DEPTH,sizeof(command_ack_t));
    app_network=xEventGroupCreate();
    s_temperature=xQueueCreate(1,sizeof(temperature_sample_t));
    s_sounds=xQueueCreate(1,sizeof(sound_request_t));
    /* Replay history is cold data: prefer PSRAM; control/queues/DMA stay internal. */
    s_cache=heap_caps_calloc(ACK_CACHE_COUNT,sizeof(*s_cache),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if (!s_cache) s_cache=heap_caps_calloc(ACK_CACHE_COUNT,sizeof(*s_cache),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    configASSERT(s_mutex && app_commands && app_acks && app_network && s_temperature && s_sounds && s_cache);
    induction_init(&s_shared);
    ESP_LOGI(TAG,"12 LEDs; groups 1-2:3, 3-4:6, 5-6:9, 7-9:12; PSRAM free=%u",
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    configASSERT(xTaskCreatePinnedToCore(control_task,"control",4096,NULL,8,NULL,1)==pdPASS);
    configASSERT(xTaskCreatePinnedToCore(led_task,"led",4096,NULL,6,NULL,1)==pdPASS);
    configASSERT(xTaskCreatePinnedToCore(peripheral_task,"peripheral",4096,NULL,4,NULL,1)==pdPASS);
    configASSERT(xTaskCreatePinnedToCore(sound_task,"sound",2048,NULL,3,NULL,1)==pdPASS);
#ifdef CONFIG_INDUCTION_NETWORK_ENABLE
    configASSERT(xTaskCreatePinnedToCore(network_task,"network",8192,NULL,4,NULL,0)==pdPASS);
#endif
}
