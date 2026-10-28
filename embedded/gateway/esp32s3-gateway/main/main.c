#include "gateway_wire.h"
#include "sdkconfig.h"
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/time.h>
#include "driver/usb_serial_jtag.h"
#include "driver/uart.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "nvs_flash.h"

#define USB_FAULT BIT0
#define USB_RX_RESET BIT1
#define LINK_TIMEOUT_US INT64_C(6000000)
#define FLOW_TIMEOUT_US INT64_C(10000000)
#define QUEUE_FRAMES 24
_Static_assert(CONFIG_FREERTOS_NUMBER_OF_CORES == 2, "Gateway requires both S3 cores");
_Static_assert(CONFIG_LWIP_MAX_SOCKETS >= CONFIG_GW_MAX_CLIENTS + 2, "Need MQTT streams plus listener and NTP sockets");
#if defined(CONFIG_GW_TRANSPORT_UART0) && !defined(CONFIG_ESP_CONSOLE_NONE)
#error "UART0 gateway data requires ESP_CONSOLE_NONE to keep logs out of binary frames"
#endif

typedef struct {
    int fd;
    uint32_t id;
    bool opened, awaiting_ack;
    int64_t deadline, rx_deadline;
    size_t rx_size, rx_sent;
    uint8_t rx[GW_PAYLOAD_MAX];
} stream_t;
static const char *TAG="homevis_gateway";
static QueueHandle_t s_usb_rx, s_usb_tx;
static EventGroupHandle_t s_usb_events;
/* Only network_task accesses these fields. USB task communicates by value. */
static stream_t s_streams[CONFIG_GW_MAX_CLIENTS];
static bool s_link, s_clock_valid;
static int64_t s_heartbeat;
static uint32_t s_next_id;

static bool emit(uint8_t type, uint32_t stream, const void *data, size_t size)
{
    gw_frame_t frame={.type=type,.stream=stream,.size=size};
    if (size) memcpy(frame.data,data,size);
    if (xQueueSend(s_usb_tx,&frame,0)==pdTRUE) return true;
    xEventGroupSetBits(s_usb_events,USB_FAULT);
    return false;
}
static void from_usb(const gw_frame_t *frame, void *ctx)
{
    (void)ctx;
    if (xQueueSend(s_usb_rx,frame,0)!=pdTRUE)
        xEventGroupSetBits(s_usb_events,USB_FAULT);
}
static void transport_init(void)
{
#ifdef CONFIG_GW_TRANSPORT_UART0
    const uart_config_t config={.baud_rate=CONFIG_GW_SERIAL_BAUD,.data_bits=UART_DATA_8_BITS,
        .parity=UART_PARITY_DISABLE,.stop_bits=UART_STOP_BITS_1,
        .flow_ctrl=UART_HW_FLOWCTRL_DISABLE,.source_clk=UART_SCLK_DEFAULT};
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0,&config));
    ESP_ERROR_CHECK(uart_set_pin(UART_NUM_0,43,44,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0,16384,4096,0,NULL,0));
    ESP_ERROR_CHECK(uart_flush_input(UART_NUM_0));
#else
    usb_serial_jtag_driver_config_t config={.rx_buffer_size=8192,.tx_buffer_size=8192};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&config));
#endif
}
static int transport_read(void *data, size_t size)
{
#ifdef CONFIG_GW_TRANSPORT_UART0
    return uart_read_bytes(UART_NUM_0,data,size,pdMS_TO_TICKS(1));
#else
    return usb_serial_jtag_read_bytes(data,size,pdMS_TO_TICKS(1));
#endif
}
static int transport_write(const void *data, size_t size)
{
#ifdef CONFIG_GW_TRANSPORT_UART0
    return uart_write_bytes(UART_NUM_0,data,size);
#else
    return usb_serial_jtag_write_bytes(data,size,pdMS_TO_TICKS(10));
#endif
}
/* Core 1 owns the selected serial driver/ISR, byte parser and CRC. */
static void serial_task(void *arg)
{
    (void)arg;
    transport_init();
    static gw_parser_t parser;
    static gw_frame_t frame;
    static uint8_t input[2048], output[GW_FRAME_MAX];
    ESP_LOGI(TAG,"Serial transport on core %d",xPortGetCoreID());
    for (;;) {
        if (xEventGroupGetBits(s_usb_events)&USB_RX_RESET) {
            parser.used=0;
            xEventGroupClearBits(s_usb_events,USB_RX_RESET);
        }
        int got=transport_read(input,sizeof(input));
        if (got>0) gw_feed(&parser,input,got,from_usb,NULL);
        for (int batch=0; batch<4 && xQueueReceive(s_usb_tx,&frame,0)==pdTRUE; ++batch) {
            size_t length=gw_encode(output,&frame), sent=0;
            int64_t deadline=esp_timer_get_time()+200000;
            while (sent<length && esp_timer_get_time()<deadline) {
                int n=transport_write(output+sent,length-sent);
                if (n>0) sent+=n;
            }
            if (sent<length) {
                xQueueReset(s_usb_tx);
                parser.used=0;
                xEventGroupSetBits(s_usb_events,USB_FAULT);
                break;
            }
        }
    }
}
static stream_t *find_stream(uint32_t id)
{
    for (int i=0; i<CONFIG_GW_MAX_CLIENTS; ++i)
        if (s_streams[i].fd>=0 && s_streams[i].id==id) return &s_streams[i];
    return NULL;
}
static void close_stream(stream_t *s, bool notify)
{
    if (s->fd<0) return;
    if (notify && s_link) emit(GW_CLOSE,s->id,NULL,0);
    shutdown(s->fd,SHUT_RDWR);
    close(s->fd);
    ESP_LOGI(TAG,"MQTT stream %lu closed",(unsigned long)s->id);
    *s=(stream_t){.fd=-1};
}
static void reset_link(void)
{
    s_link=false; s_clock_valid=false;
    for (int i=0; i<CONFIG_GW_MAX_CLIENTS; ++i) close_stream(&s_streams[i],false);
}
static void dispatch(const gw_frame_t *f)
{
    if (f->type==GW_HELLO && !f->stream && f->size==8) {
        reset_link();
        /* Retire all frames from the previous host session. */
        xQueueReset(s_usb_tx);
        s_link=true; s_heartbeat=esp_timer_get_time();
        emit(GW_READY,0,f->data,8);
        ESP_LOGI(TAG,"USB host session ready");
        return;
    }
    if (!s_link) return;
    if (f->type==GW_TIME && !f->stream && f->size==8) {
        uint64_t ms=gw_u64(f->data);
        /* Reject bogus laptop clocks; do not allow boot-time NTP from epoch 1970. */
        if (ms<UINT64_C(1704067200000) || ms>UINT64_C(4102444800000)) return;
        struct timeval now={.tv_sec=ms/1000,.tv_usec=(ms%1000)*1000};
        if (settimeofday(&now,NULL)==0) {
            if (!s_clock_valid) ESP_LOGI(TAG,"Laptop time received; local NTP ready");
            s_clock_valid=true; s_heartbeat=esp_timer_get_time();
            emit(GW_PONG,0,f->data,8);
        }
        return;
    }
    stream_t *s=find_stream(f->stream);
    if (!s) return;
    if (f->type==GW_OPEN_OK && !f->size && !s->opened) {
        s->opened=true;
    } else if (f->type==GW_CLOSE && !f->size) {
        close_stream(s,false);
    } else if (f->type==GW_ACK && !f->size && s->awaiting_ack) {
        s->awaiting_ack=false;
    } else if (f->type==GW_DATA && f->size && s->opened && !s->rx_size) {
        memcpy(s->rx,f->data,f->size);
        s->rx_size=f->size; s->rx_sent=0;
        s->rx_deadline=esp_timer_get_time()+FLOW_TIMEOUT_US;
    } else {
        close_stream(s,true);
    }
}
static bool retryable(void) { return errno==EAGAIN || errno==EWOULDBLOCK || errno==EINTR; }
static void nonblocking(int fd)
{ configASSERT(fcntl(fd,F_SETFL,fcntl(fd,F_GETFL,0)|O_NONBLOCK)==0); }
static int open_port(int type, uint16_t port)
{
    int fd=socket(AF_INET,type,0);
    configASSERT(fd>=0);
    int one=1;
    setsockopt(fd,SOL_SOCKET,SO_REUSEADDR,&one,sizeof(one));
    struct sockaddr_in addr={.sin_family=AF_INET,.sin_port=htons(port),.sin_addr.s_addr=INADDR_ANY};
    configASSERT(bind(fd,(struct sockaddr *)&addr,sizeof(addr))==0);
    nonblocking(fd);
    return fd;
}
static void accept_clients(int listener)
{
    struct sockaddr_in peer; socklen_t length=sizeof(peer);
    int fd=accept(listener,(struct sockaddr *)&peer,&length);
    if (fd<0) return;
    stream_t *slot=NULL;
    for (int i=0; i<CONFIG_GW_MAX_CLIENTS; ++i)
        if (s_streams[i].fd<0) { slot=&s_streams[i]; break; }
    if (!slot || !s_link || !s_clock_valid) { close(fd); return; }
    nonblocking(fd);
    int one=1; setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&one,sizeof(one));
    if (++s_next_id==0) ++s_next_id;
    *slot=(stream_t){.fd=fd,.id=s_next_id,.deadline=esp_timer_get_time()+FLOW_TIMEOUT_US};
    emit(GW_OPEN,slot->id,NULL,0);
    esp_ip4_addr_t peer_ip={.addr=peer.sin_addr.s_addr};
    ESP_LOGI(TAG,"MQTT stream %lu from " IPSTR,(unsigned long)slot->id,IP2STR(&peer_ip));
}
static void ntp_request(int fd)
{
    uint8_t request[512], response[48];
    struct sockaddr_in peer; socklen_t length=sizeof(peer);
    int n=recvfrom(fd,request,sizeof(request),0,(struct sockaddr *)&peer,&length);
    if (n<0 || !s_link || !s_clock_valid) return;
    struct timeval now; gettimeofday(&now,NULL);
    if (gw_ntp_reply(request,n,(int64_t)now.tv_sec*1000000+now.tv_usec,response))
        sendto(fd,response,sizeof(response),0,(struct sockaddr *)&peer,length);
}
/* Core 0 owns Wi-Fi/TCP/IP, stream state and local NTP. No USB blocking here. */
static void network_task(void *arg)
{
    (void)arg;
    int listener=open_port(SOCK_STREAM,CONFIG_GW_MQTT_PORT);
    configASSERT(listen(listener,CONFIG_GW_MAX_CLIENTS)==0);
    int ntp=open_port(SOCK_DGRAM,123);
    static gw_frame_t frame;
    static uint8_t payload[GW_PAYLOAD_MAX];
    for (int i=0; i<CONFIG_GW_MAX_CLIENTS; ++i) s_streams[i].fd=-1;
    ESP_LOGI(TAG,"Wi-Fi/TCP/NTP task core %d; MQTT 192.168.4.1:%d; NTP UDP123",
             xPortGetCoreID(),CONFIG_GW_MQTT_PORT);
    for (;;) {
        int64_t now=esp_timer_get_time();
        if ((xEventGroupGetBits(s_usb_events)&USB_FAULT) ||
            (s_link && now-s_heartbeat>LINK_TIMEOUT_US)) {
            xEventGroupClearBits(s_usb_events,USB_FAULT);
            xEventGroupSetBits(s_usb_events,USB_RX_RESET);
            if (s_link) ESP_LOGW(TAG,"USB link lost; disconnecting MQTT streams until host handshake");
            reset_link();
        }
        for (int batch=0; batch<QUEUE_FRAMES && xQueueReceive(s_usb_rx,&frame,0)==pdTRUE; ++batch)
            dispatch(&frame);
        accept_clients(listener);
        ntp_request(ntp);
        for (int i=0; i<CONFIG_GW_MAX_CLIENTS; ++i) {
            stream_t *s=&s_streams[i];
            if (s->fd<0) continue;
            if (((!s->opened || s->awaiting_ack) && now>s->deadline) ||
                (s->rx_size && now>s->rx_deadline)) {
                close_stream(s,true); continue;
            }
            if (!s->opened) continue;
            if (s->rx_size) {
                int n=send(s->fd,s->rx+s->rx_sent,s->rx_size-s->rx_sent,0);
                if (n>0) {
                    s->rx_sent+=n;
                    if (s->rx_sent==s->rx_size) {
                        s->rx_size=0;
                        emit(GW_ACK,s->id,NULL,0);
                    }
                } else if (n<0 && !retryable()) { close_stream(s,true); continue; }
            }
            if (!s->awaiting_ack) {
                int n=recv(s->fd,payload,sizeof(payload),0);
                if (n>0) {
                    emit(GW_DATA,s->id,payload,n);
                    s->awaiting_ack=true; s->deadline=now+FLOW_TIMEOUT_US;
                } else if (n==0 || !retryable()) { close_stream(s,true); }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base;
    if (id==WIFI_EVENT_AP_STACONNECTED) {
        wifi_event_ap_staconnected_t *e=data;
        ESP_LOGI(TAG,"Appliance Wi-Fi joined, AID=%d",e->aid);
    } else if (id==WIFI_EVENT_AP_STADISCONNECTED) {
        wifi_event_ap_stadisconnected_t *e=data;
        ESP_LOGI(TAG,"Appliance Wi-Fi left, AID=%d",e->aid);
    }
}
void app_main(void)
{
    size_t passlen=strlen(CONFIG_GW_AP_PASSWORD), ssidlen=strlen(CONFIG_GW_AP_SSID);
    if (!ssidlen || ssidlen>32 || passlen<8 || passlen>63) {
        ESP_LOGE(TAG,"Configure AP SSID and an 8-63 character WPA2 password in projbuild/menuconfig");
        return;
    }
    esp_err_t error=nvs_flash_init();
    if (error==ESP_ERR_NVS_NO_FREE_PAGES || error==ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase()); error=nvs_flash_init();
    }
    ESP_ERROR_CHECK(error);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_t *ap=esp_netif_create_default_wifi_ap(); configASSERT(ap);
    /* A freshly created AP has DHCP_INIT, which is NOT DHCP_STOPPED.
     * set_ip_info requires an explicit stop even before Wi-Fi has started. */
    error=esp_netif_dhcps_stop(ap);
    if (error!=ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED) ESP_ERROR_CHECK(error);
    esp_netif_ip_info_t ip={};
    IP4_ADDR(&ip.ip,192,168,4,1); IP4_ADDR(&ip.gw,192,168,4,1); IP4_ADDR(&ip.netmask,255,255,255,0);
    ESP_ERROR_CHECK(esp_netif_set_ip_info(ap,&ip));
    /* Re-enable DHCP; the default AP-start handler starts leasing addresses. */
    ESP_ERROR_CHECK(esp_netif_dhcps_start(ap));
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,NULL));
    wifi_config_t wifi={.ap={.ssid_len=ssidlen,.channel=CONFIG_GW_AP_CHANNEL,
        .max_connection=CONFIG_GW_MAX_CLIENTS,.authmode=WIFI_AUTH_WPA2_PSK,
        .pmf_cfg={.required=false}}};
    memcpy(wifi.ap.ssid,CONFIG_GW_AP_SSID,ssidlen);
    memcpy(wifi.ap.password,CONFIG_GW_AP_PASSWORD,passlen);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP,&wifi));
    ESP_ERROR_CHECK(esp_wifi_start());
    s_usb_rx=xQueueCreate(QUEUE_FRAMES,sizeof(gw_frame_t));
    s_usb_tx=xQueueCreate(QUEUE_FRAMES,sizeof(gw_frame_t));
    s_usb_events=xEventGroupCreate();
    configASSERT(s_usb_rx && s_usb_tx && s_usb_events);
    configASSERT(xTaskCreatePinnedToCore(serial_task,"gateway_serial",8192,NULL,8,NULL,1)==pdPASS);
    configASSERT(xTaskCreatePinnedToCore(network_task,"gateway_network",8192,NULL,5,NULL,0)==pdPASS);
    ESP_LOGI(TAG,"AP %s, max stations=%d; framed serial data",CONFIG_GW_AP_SSID,CONFIG_GW_MAX_CLIENTS);
}
