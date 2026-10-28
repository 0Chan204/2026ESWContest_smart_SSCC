/*
 * ESP32-C6 Wi-Fi CSI Receiver
 *
 * Wi-Fi:
 *   SSID     : HomeVIS-Local
 *   Password : configured locally with menuconfig
 *   Bandwidth: HT20
 *   Channel  : AP channel automatic follow
 *
 * Built-in RGB LED:
 *   Boot / Initial Wi-Fi connection : White  (8, 8, 8)
 *   Wi-Fi disconnected / failed     : Red    (8, 0, 0)
 *   Wi-Fi connected / CSI setup     : Yellow (8, 8, 0)
 *   CSI sensing                     : Green  (0, 8, 0)
 *
 * CSI trigger:
 *   ICMP ping to AP gateway @ 25 Hz
 *
 * CSV output:
 *   local_timestamp,data,rssi,mac,first_word,len
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"

#include "nvs_flash.h"

#include "esp_mac.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_err.h"

#include "rom/ets_sys.h"

#include "lwip/inet.h"
#include "lwip/sockets.h"

#include "ping/ping_sock.h"

#include "esp_csi_gain_ctrl.h"

#include "led_strip.h"

#if !CONFIG_ESP_WIFI_CSI_ENABLED
#error "Enable CONFIG_ESP_WIFI_CSI_ENABLED in menuconfig before building the CSI receiver."
#endif


/* ============================================================
 * Wi-Fi Configuration
 * ============================================================ */

#define WIFI_SSID               CONFIG_CSI_WIFI_SSID
#define WIFI_PASSWORD           CONFIG_CSI_WIFI_PASSWORD

#define WIFI_CONNECTED_BIT      BIT0


/* ============================================================
 * CSI Configuration
 * ============================================================ */

#define CSI_SEND_FREQUENCY_HZ   25

#define CSI_GAIN_CONTROL        1
#define CSI_FORCE_GAIN          0


/* ============================================================
 * RGB LED Configuration
 * ============================================================ */

/*
 * Built-in RGB LED
 *
 * ESP32-C6 DevKit 계열 GPIO8 기준
 */
#define RGB_LED_GPIO            8

/*
 * 모든 색상 활성 채널 값
 *
 * 0 ~ 255 중 8 사용
 */
#define RGB_LEVEL               8


/* ============================================================
 * Global
 * ============================================================ */

static const char *TAG = "c6_csi";

static EventGroupHandle_t s_wifi_event_group = NULL;

static led_strip_handle_t s_rgb_led = NULL;

/*
 * false:
 *   아직 CSI 센싱 시작 전
 *
 * true:
 *   CSI 센싱 시작 완료
 */
static volatile bool s_sensing_started = false;


/* ============================================================
 * RGB LED Initialization
 * ============================================================ */

static void rgb_led_init(void)
{
    led_strip_config_t strip_config = {

        .strip_gpio_num =
            RGB_LED_GPIO,

        .max_leds =
            1,

        .led_model =
            LED_MODEL_WS2812,

        .color_component_format =
            LED_STRIP_COLOR_COMPONENT_FMT_GRB,

        .flags = {
            .invert_out = false
        }
    };


    led_strip_rmt_config_t rmt_config = {

        .clk_src =
            RMT_CLK_SRC_DEFAULT,

        .resolution_hz =
            10 * 1000 * 1000,

        .mem_block_symbols =
            64,

        .flags = {
            .with_dma = false
        }
    };


    ESP_ERROR_CHECK(
        led_strip_new_rmt_device(
            &strip_config,
            &rmt_config,
            &s_rgb_led
        )
    );


    ESP_ERROR_CHECK(
        led_strip_clear(
            s_rgb_led
        )
    );
}


/* ============================================================
 * RGB LED Set
 * ============================================================ */

static void rgb_led_set(
    uint8_t red,
    uint8_t green,
    uint8_t blue
)
{
    if (s_rgb_led == NULL) {
        return;
    }


    ESP_ERROR_CHECK(
        led_strip_set_pixel(
            s_rgb_led,
            0,
            red,
            green,
            blue
        )
    );


    ESP_ERROR_CHECK(
        led_strip_refresh(
            s_rgb_led
        )
    );
}


/* ============================================================
 * RGB LED States
 * ============================================================ */

/*
 * Boot / 최초 Wi-Fi 연결 전
 *
 * White
 * (8, 8, 8)
 */
static void rgb_led_boot(void)
{
    rgb_led_set(
        RGB_LEVEL,
        RGB_LEVEL,
        RGB_LEVEL
    );
}


/*
 * Wi-Fi 연결 성공
 * CSI 수집 시작 전
 *
 * Yellow
 * (8, 8, 0)
 */
static void rgb_led_waiting(void)
{
    rgb_led_set(
        RGB_LEVEL,
        RGB_LEVEL,
        0
    );
}


/*
 * Wi-Fi 연결 실패 / 연결 끊김
 *
 * Red
 * (8, 0, 0)
 */
static void rgb_led_error(void)
{
    rgb_led_set(
        RGB_LEVEL,
        0,
        0
    );
}


/*
 * CSI 센싱 중
 *
 * Green
 * (0, 8, 0)
 */
static void rgb_led_sensing(void)
{
    rgb_led_set(
        0,
        RGB_LEVEL,
        0
    );
}


/* ============================================================
 * Wi-Fi Event Handler
 * ============================================================ */

static void wifi_event_handler(
    void *arg,
    esp_event_base_t event_base,
    int32_t event_id,
    void *event_data
)
{
    /* --------------------------------------------------------
     * Wi-Fi STA 시작
     *
     * 최초 연결 시도 중에는
     * White 상태 유지
     * -------------------------------------------------------- */

    if (
        event_base == WIFI_EVENT &&
        event_id == WIFI_EVENT_STA_START
    ) {

        ESP_LOGI(
            TAG,
            "Connecting to Wi-Fi SSID: %s",
            WIFI_SSID
        );


        esp_wifi_connect();
    }


    /* --------------------------------------------------------
     * Wi-Fi 연결 실패 또는 연결 끊김
     *
     * 언제든 Red
     * -------------------------------------------------------- */

    else if (
        event_base == WIFI_EVENT &&
        event_id == WIFI_EVENT_STA_DISCONNECTED
    ) {

        if (s_wifi_event_group != NULL) {

            xEventGroupClearBits(
                s_wifi_event_group,
                WIFI_CONNECTED_BIT
            );
        }


        /*
         * Wi-Fi 오류
         */
        rgb_led_error();


        ESP_LOGW(
            TAG,
            "Wi-Fi disconnected. Reconnecting..."
        );


        /*
         * 자동 재연결
         *
         * 재연결 중에도 Red 유지
         */
        esp_wifi_connect();
    }


    /* --------------------------------------------------------
     * Wi-Fi 연결 성공
     * DHCP IP 획득
     * -------------------------------------------------------- */

    else if (
        event_base == IP_EVENT &&
        event_id == IP_EVENT_STA_GOT_IP
    ) {

        ip_event_got_ip_t *event =
            (ip_event_got_ip_t *)event_data;


        ESP_LOGI(
            TAG,
            "Got IP: " IPSTR,
            IP2STR(
                &event->ip_info.ip
            )
        );


        /*
         * Wi-Fi 연결 상태 갱신
         */
        if (s_wifi_event_group != NULL) {

            xEventGroupSetBits(
                s_wifi_event_group,
                WIFI_CONNECTED_BIT
            );
        }


        /*
         * 아직 센싱 시작 전이면
         * Yellow
         *
         * 이미 센싱 중이었다가
         * 재연결된 경우 Green
         */
        if (s_sensing_started) {

            rgb_led_sensing();

        } else {

            rgb_led_waiting();
        }
    }
}


/* ============================================================
 * Wi-Fi STA Initialization
 * ============================================================ */

static void wifi_init_sta(void)
{
    const size_t ssid_len = strlen(WIFI_SSID);
    const size_t password_len = strlen(WIFI_PASSWORD);
    if (ssid_len == 0 || ssid_len > 32 || password_len < 8 || password_len > 63) {
        ESP_LOGE(TAG, "Set Wi-Fi SSID (1-32 bytes) and WPA2 password (8-63 bytes) in menuconfig");
        abort();
    }

    /* --------------------------------------------------------
     * Event Group
     * -------------------------------------------------------- */

    s_wifi_event_group =
        xEventGroupCreate();


    if (s_wifi_event_group == NULL) {

        ESP_LOGE(
            TAG,
            "Failed to create Wi-Fi EventGroup"
        );

        abort();
    }


    /* --------------------------------------------------------
     * STA Network Interface
     * -------------------------------------------------------- */

    esp_netif_t *sta_netif =
        esp_netif_create_default_wifi_sta();


    if (sta_netif == NULL) {

        ESP_LOGE(
            TAG,
            "Failed to create Wi-Fi STA interface"
        );

        abort();
    }


    /* --------------------------------------------------------
     * Wi-Fi Driver
     * -------------------------------------------------------- */

    wifi_init_config_t cfg =
        WIFI_INIT_CONFIG_DEFAULT();


    ESP_ERROR_CHECK(
        esp_wifi_init(
            &cfg
        )
    );


    /* --------------------------------------------------------
     * Wi-Fi Event Handler
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_event_handler_register(
            WIFI_EVENT,
            ESP_EVENT_ANY_ID,
            &wifi_event_handler,
            NULL
        )
    );


    /* --------------------------------------------------------
     * IP Event Handler
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_event_handler_register(
            IP_EVENT,
            IP_EVENT_STA_GOT_IP,
            &wifi_event_handler,
            NULL
        )
    );


    /* --------------------------------------------------------
     * Wi-Fi Configuration
     * -------------------------------------------------------- */

    wifi_config_t wifi_config = {

        .sta = {

            .ssid =
                WIFI_SSID,

            .password =
                WIFI_PASSWORD,

            .threshold.authmode =
                WIFI_AUTH_WPA2_PSK,

            .pmf_cfg = {

                .capable =
                    true,

                .required =
                    false
            }
        }
    };


    /* --------------------------------------------------------
     * STA Mode
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_mode(
            WIFI_MODE_STA
        )
    );


    /* --------------------------------------------------------
     * Wi-Fi Config 적용
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_config(
            WIFI_IF_STA,
            &wifi_config
        )
    );


    /* --------------------------------------------------------
     * Wi-Fi Start
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_start()
    );


    ESP_LOGI(
        TAG,
        "Waiting for Wi-Fi connection..."
    );


    /* --------------------------------------------------------
     * Wi-Fi 연결 성공까지 대기
     *
     * 연결 실패 시:
     *   Red
     *
     * 연결 성공 시:
     *   Yellow
     * -------------------------------------------------------- */

    xEventGroupWaitBits(
        s_wifi_event_group,
        WIFI_CONNECTED_BIT,
        pdFALSE,
        pdTRUE,
        portMAX_DELAY
    );


    ESP_LOGI(
        TAG,
        "Connected to Wi-Fi"
    );


    ESP_LOGI(
        TAG,
        "SSID: %s",
        WIFI_SSID
    );


    /* --------------------------------------------------------
     * Wi-Fi Power Save OFF
     *
     * CSI 패킷 수신 안정성 확보
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_ps(
            WIFI_PS_NONE
        )
    );


    ESP_LOGI(
        TAG,
        "Wi-Fi power save disabled"
    );
}


/* ============================================================
 * Wi-Fi Link Configuration
 * ============================================================ */

static esp_err_t wifi_configure_link(void)
{
    uint8_t primary_channel =
        0;


    wifi_second_chan_t secondary_channel =
        WIFI_SECOND_CHAN_NONE;


    /* --------------------------------------------------------
     * 현재 연결된 AP Channel 확인
     *
     * 특정 Channel 강제 없음
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_get_channel(
            &primary_channel,
            &secondary_channel
        )
    );


    ESP_LOGI(
        TAG,
        "Connected Wi-Fi channel: %u",
        primary_channel
    );


    /* --------------------------------------------------------
     * CSI 조건을 위해 HT20 사용
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_bandwidth(
            WIFI_IF_STA,
            WIFI_BW_HT20
        )
    );


    wifi_bandwidth_t bandwidth;


    ESP_ERROR_CHECK(
        esp_wifi_get_bandwidth(
            WIFI_IF_STA,
            &bandwidth
        )
    );


    if (
        bandwidth == WIFI_BW_HT20
    ) {

        ESP_LOGI(
            TAG,
            "Wi-Fi bandwidth: HT20"
        );

    } else {

        ESP_LOGW(
            TAG,
            "Wi-Fi bandwidth is not HT20: %d",
            bandwidth
        );
    }


    return ESP_OK;
}


/* ============================================================
 * CSI RX Callback
 * ============================================================ */

static void wifi_csi_rx_cb(
    void *ctx,
    wifi_csi_info_t *info
)
{
    /* --------------------------------------------------------
     * CSI 유효성 확인
     * -------------------------------------------------------- */

    if (
        info == NULL ||
        info->buf == NULL
    ) {

        return;
    }


    /* --------------------------------------------------------
     * 현재 연결된 AP에서 온 Packet만 사용
     * -------------------------------------------------------- */

    if (
        ctx != NULL &&
        memcmp(
            info->mac,
            ctx,
            6
        ) != 0
    ) {

        return;
    }


    const wifi_pkt_rx_ctrl_t *rx_ctrl =
        &info->rx_ctrl;


    /* --------------------------------------------------------
     * Gain Compensation
     * -------------------------------------------------------- */

    float compensate_gain =
        1.0f;


#if CSI_GAIN_CONTROL

    static uint32_t packet_count =
        0;


    static uint8_t agc_gain =
        0;


    static int8_t fft_gain =
        0;


    static uint8_t agc_gain_baseline =
        0;


    static int8_t fft_gain_baseline =
        0;


    /*
     * 현재 RX Gain 조회
     */
    esp_csi_gain_ctrl_get_rx_gain(
        rx_ctrl,
        &agc_gain,
        &fft_gain
    );


    /*
     * 최초 100 Packet
     *
     * Gain 통계 수집
     */
    if (
        packet_count < 100
    ) {

        esp_csi_gain_ctrl_record_rx_gain(
            agc_gain,
            fft_gain
        );

    }


    /*
     * 100 Packet 수집 완료
     */
    else if (
        packet_count == 100
    ) {

        esp_csi_gain_ctrl_get_rx_gain_baseline(
            &agc_gain_baseline,
            &fft_gain_baseline
        );


        ESP_LOGI(
            TAG,
            "CSI gain calibration completed"
        );


        ESP_LOGI(
            TAG,
            "AGC baseline: %u",
            agc_gain_baseline
        );


        ESP_LOGI(
            TAG,
            "FFT baseline: %d",
            fft_gain_baseline
        );


#if CSI_FORCE_GAIN

        esp_csi_gain_ctrl_set_rx_force_gain(
            agc_gain_baseline,
            fft_gain_baseline
        );

#endif
    }


    /*
     * Gain Compensation 계산
     */
    esp_csi_gain_ctrl_get_gain_compensation(
        &compensate_gain,
        agc_gain,
        fft_gain
    );


    packet_count++;

#endif


    /* ========================================================
     * CSV Header
     * ======================================================== */

    static bool header_printed =
        false;


    if (!header_printed) {

        ets_printf(
            "local_timestamp,data,rssi,mac,first_word,len\n"
        );


        header_printed =
            true;
    }


    /* ========================================================
     * local_timestamp
     * ======================================================== */

    ets_printf(
        "%u,\"[",
        (unsigned int)rx_ctrl->timestamp
    );


    /* ========================================================
     * CSI Data
     * ======================================================== */

    for (
        int i = 0;
        i < info->len;
        i++
    ) {

        if (i != 0) {

            ets_printf(",");
        }


        int16_t csi_value =
            (int16_t)(
                compensate_gain *
                info->buf[i]
            );


        ets_printf(
            "%d",
            csi_value
        );
    }


    /* ========================================================
     * Metadata
     *
     * local_timestamp
     * data
     * rssi
     * mac
     * first_word
     * len
     * ======================================================== */

    ets_printf(
        "]\",%d," MACSTR ",%d,%u\n",

        rx_ctrl->rssi,

        MAC2STR(
            info->mac
        ),

        info->first_word_invalid
            ? 1
            : 0,

        (unsigned int)info->len
    );
}


/* ============================================================
 * CSI Initialization
 * ============================================================ */

static void wifi_csi_init(void)
{
    /*
     * callback ctx에서 BSSID 주소를 사용하므로
     * static으로 유지
     */
    static wifi_ap_record_t ap_info = {
        0
    };


    /* --------------------------------------------------------
     * 현재 연결된 AP 정보
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_sta_get_ap_info(
            &ap_info
        )
    );


    ESP_LOGI(
        TAG,
        "AP SSID: %s",
        (char *)ap_info.ssid
    );


    ESP_LOGI(
        TAG,
        "AP BSSID: " MACSTR,
        MAC2STR(
            ap_info.bssid
        )
    );


    ESP_LOGI(
        TAG,
        "AP primary channel: %d",
        ap_info.primary
    );


    ESP_LOGI(
        TAG,
        "AP RSSI: %d dBm",
        ap_info.rssi
    );


    /* ========================================================
     * ESP32-C6 CSI Configuration
     * ======================================================== */

#if CONFIG_IDF_TARGET_ESP32C6

    wifi_csi_config_t csi_config = {

        /*
         * CSI Enable
         */
        .enable =
            true,


        /*
         * Legacy CSI
         */
        .acquire_csi_legacy =
            true,


        /*
         * 802.11n HT20
         */
        .acquire_csi_ht20 =
            true,


        /*
         * HT40 OFF
         */
        .acquire_csi_ht40 =
            false,


        /*
         * HE / 802.11ax OFF
         */
        .acquire_csi_su =
            false,


        .acquire_csi_mu =
            false,


        .acquire_csi_dcm =
            false,


        /*
         * Beamforming OFF
         */
        .acquire_csi_beamformed =
            false,


        /*
         * HE STBC OFF
         */
        .acquire_csi_he_stbc =
            0,


        /*
         * Default Scaling
         */
        .val_scale_cfg =
            0,


        /*
         * ACK CSI Dump OFF
         */
        .dump_ack_en =
            false,


        .reserved =
            false
    };


#else

#error "This firmware is intended for ESP32-C6."

#endif


    /* --------------------------------------------------------
     * CSI Configuration 적용
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_csi_config(
            &csi_config
        )
    );


    /* --------------------------------------------------------
     * CSI Callback
     *
     * ctx = AP BSSID
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_csi_rx_cb(
            wifi_csi_rx_cb,
            ap_info.bssid
        )
    );


    /* --------------------------------------------------------
     * CSI RX Enable
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_wifi_set_csi(
            true
        )
    );


    ESP_LOGI(
        TAG,
        "CSI enabled"
    );
}


/* ============================================================
 * Gateway Ping
 * ============================================================ */

static esp_err_t wifi_ping_router_start(void)
{
    static esp_ping_handle_t ping_handle =
        NULL;


    esp_ping_config_t ping_config =
        ESP_PING_DEFAULT_CONFIG();


    /* --------------------------------------------------------
     * Infinite Ping
     * -------------------------------------------------------- */

    ping_config.count =
        0;


    /* --------------------------------------------------------
     * 25 Hz
     *
     * 40 ms interval
     * -------------------------------------------------------- */

    ping_config.interval_ms =
        1000 /
        CSI_SEND_FREQUENCY_HZ;


    /* --------------------------------------------------------
     * Ping Task Stack
     * -------------------------------------------------------- */

    ping_config.task_stack_size =
        3072;


    /* --------------------------------------------------------
     * Payload
     * -------------------------------------------------------- */

    ping_config.data_size =
        1;


    /* --------------------------------------------------------
     * STA Interface
     * -------------------------------------------------------- */

    esp_netif_t *netif =
        esp_netif_get_handle_from_ifkey(
            "WIFI_STA_DEF"
        );


    if (netif == NULL) {

        ESP_LOGE(
            TAG,
            "WIFI_STA_DEF interface not found"
        );


        return ESP_FAIL;
    }


    /* --------------------------------------------------------
     * 현재 IP / Gateway
     * -------------------------------------------------------- */

    esp_netif_ip_info_t local_ip = {
        0
    };


    ESP_ERROR_CHECK(
        esp_netif_get_ip_info(
            netif,
            &local_ip
        )
    );


    ESP_LOGI(
        TAG,
        "ESP32 IP: " IPSTR,
        IP2STR(
            &local_ip.ip
        )
    );


    ESP_LOGI(
        TAG,
        "Gateway: " IPSTR,
        IP2STR(
            &local_ip.gw
        )
    );


    /* --------------------------------------------------------
     * Gateway를 Ping Target으로 설정
     * -------------------------------------------------------- */

    ping_config.target_addr.u_addr.ip4.addr =
        ip4_addr_get_u32(
            &local_ip.gw
        );


    ping_config.target_addr.type =
        ESP_IPADDR_TYPE_V4;


    /* --------------------------------------------------------
     * 별도 Ping Callback 없음
     * -------------------------------------------------------- */

    esp_ping_callbacks_t callbacks = {
        0
    };


    /* --------------------------------------------------------
     * Ping Session 생성
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_ping_new_session(
            &ping_config,
            &callbacks,
            &ping_handle
        )
    );


    /* --------------------------------------------------------
     * Ping Start
     * -------------------------------------------------------- */

    ESP_ERROR_CHECK(
        esp_ping_start(
            ping_handle
        )
    );


    ESP_LOGI(
        TAG,
        "Started gateway ping: %d Hz (%d ms)",
        CSI_SEND_FREQUENCY_HZ,
        1000 / CSI_SEND_FREQUENCY_HZ
    );


    return ESP_OK;
}


/* ============================================================
 * Wi-Fi Stable Wait
 *
 * Wi-Fi가 연결된 상태로 30초를 유지해야
 * CSI 수집을 시작합니다.
 *
 * 대기 중 연결이 끊기면:
 *   Red
 *
 * 재연결되면:
 *   Yellow
 *
 * 이후 30초를 다시 계산합니다.
 * ============================================================ */

/* 초기 안정화 대기는 사용하지 않음. 필요 시 다시 활성화할 수 있도록 보존. */
#if 0
static void wifi_wait_stable(
    uint32_t seconds
)
{
    uint32_t stable_seconds =
        0;


    while (
        stable_seconds < seconds
    ) {

        /*
         * 현재 연결 여부 확인
         */
        EventBits_t bits =
            xEventGroupGetBits(
                s_wifi_event_group
            );


        /*
         * 연결되어 있지 않으면
         * 다시 연결될 때까지 대기
         */
        if (
            !(bits & WIFI_CONNECTED_BIT)
        ) {

            stable_seconds =
                0;


            xEventGroupWaitBits(
                s_wifi_event_group,
                WIFI_CONNECTED_BIT,
                pdFALSE,
                pdTRUE,
                portMAX_DELAY
            );


            continue;
        }


        /*
         * 1초 대기
         */
        vTaskDelay(
            pdMS_TO_TICKS(
                1000
            )
        );


        /*
         * 1초 후에도 연결되어 있는지 확인
         */
        bits =
            xEventGroupGetBits(
                s_wifi_event_group
            );


        if (
            bits & WIFI_CONNECTED_BIT
        ) {

            stable_seconds++;

        } else {

            /*
             * 중간에 연결이 끊기면
             * 30초 안정화 시간을 처음부터 다시 시작
             */
            stable_seconds =
                0;
        }
    }
}


#endif

/* ============================================================
 * app_main
 * ============================================================ */

void app_main(void)
{
    /* ========================================================
     * Built-in RGB
     * ======================================================== */

    rgb_led_init();


    /*
     * 전원 인가 직후
     *
     * White
     * (8, 8, 8)
     *
     * Wi-Fi 연결 성공 또는 실패가 발생하기 전까지 유지
     */
    rgb_led_boot();


    /* ========================================================
     * NVS
     * ======================================================== */

    esp_err_t ret =
        nvs_flash_init();


    if (
        ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND
    ) {

        ESP_ERROR_CHECK(
            nvs_flash_erase()
        );


        ESP_ERROR_CHECK(
            nvs_flash_init()
        );
    }


    /* ========================================================
     * TCP/IP Stack
     * ======================================================== */

    ESP_ERROR_CHECK(
        esp_netif_init()
    );


    /* ========================================================
     * Event Loop
     * ======================================================== */

    ESP_ERROR_CHECK(
        esp_event_loop_create_default()
    );


    /* ========================================================
     * Wi-Fi
     *
     * 최초 연결 중:
     *   White
     *
     * 실패:
     *   Red
     *
     * 성공:
     *   Yellow
     * ======================================================== */

    wifi_init_sta();


    /* ========================================================
     * Wi-Fi Link
     *
     * Channel:
     *   AP 자동 추종
     *
     * Bandwidth:
     *   HT20
     * ======================================================== */

    ESP_ERROR_CHECK(
        wifi_configure_link()
    );


    /* 30초 안정화 대기 생략: Wi-Fi 연결 및 링크 설정 후 바로 CSI 수집 시작. */
    // wifi_wait_stable(30);


    /* ========================================================
     * CSI Enable
     * ======================================================== */

    wifi_csi_init();


    /* ========================================================
     * 25 Hz Gateway Ping
     *
     * 여기부터 실제 CSI 수집
     * ======================================================== */

    ESP_ERROR_CHECK(
        wifi_ping_router_start()
    );


    /* ========================================================
     * Sensing State
     * ======================================================== */

    s_sensing_started =
        true;


    /*
     * Green
     * (0, 8, 0)
     */
    rgb_led_sensing();


    /* ========================================================
     * 현재 Channel 확인
     * ======================================================== */

    uint8_t current_channel =
        0;


    wifi_second_chan_t secondary_channel =
        WIFI_SECOND_CHAN_NONE;


    ESP_ERROR_CHECK(
        esp_wifi_get_channel(
            &current_channel,
            &secondary_channel
        )
    );


    /* ========================================================
     * Start Log
     * ======================================================== */

    ESP_LOGI(
        TAG,
        "========================================"
    );


    ESP_LOGI(
        TAG,
        "ESP32-C6 CSI receiver started"
    );


    ESP_LOGI(
        TAG,
        "SSID       : %s",
        WIFI_SSID
    );


    ESP_LOGI(
        TAG,
        "Channel    : %u",
        current_channel
    );


    ESP_LOGI(
        TAG,
        "Bandwidth  : HT20"
    );


    ESP_LOGI(
        TAG,
        "Ping rate  : %d Hz",
        CSI_SEND_FREQUENCY_HZ
    );


    ESP_LOGI(
        TAG,
        "========================================"
    );
}
