#include "sdkconfig.h"
#include "app.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "esp_log.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "freertos/task.h"

#define RX_MAX COMMAND_MAX_BYTES
static const char *TAG="induction_net";
static esp_mqtt_client_handle_t s_mqtt;
static EventGroupHandle_t s_link;
#define WIFI_UP BIT0
static char s_state_topic[160],s_command_topic[160],s_ack_topic[160];
static bool utc(time_t value,char out[32])
{
    struct tm tm;
    return value>=1704067200 && gmtime_r(&value,&tm) &&
        strftime(out,32,"%Y-%m-%dT%H:%M:%SZ",&tm)>0;
}
static bool decode(const char *body,size_t size,induction_command_t *command)
{
    const char *end=NULL;
    cJSON *root=cJSON_ParseWithLengthOpts(body,size,&end,false);
    if (!root) return false;
    while (end<body+size && (*end==' ' || *end=='\r' || *end=='\n' || *end=='\t')) end++;
    const cJSON *id=cJSON_GetObjectItemCaseSensitive(root,"commandId");
    const cJSON *burner=cJSON_GetObjectItemCaseSensitive(root,"burnerId");
    const cJSON *type=cJSON_GetObjectItemCaseSensitive(root,"type");
    const cJSON *level=cJSON_GetObjectItemCaseSensitive(root,"level");
    const cJSON *issued=cJSON_GetObjectItemCaseSensitive(root,"issuedAt");
    bool envelope=cJSON_IsObject(root) && end==body+size && cJSON_IsString(id) && strlen(id->valuestring)<COMMAND_ID_SIZE;
    if (envelope) {
        memset(command,0,sizeof(*command));
        snprintf(command->id,sizeof(command->id),"%s",id->valuestring);
        command->type=(command_type_t)99; /* Identifiable invalid commands receive a rejected ACK. */
        bool ok=cJSON_IsString(burner) && !strcmp(burner->valuestring,CONFIG_INDUCTION_BURNER_ID) &&
            cJSON_IsString(type) && cJSON_IsString(issued) && issued->valuestring[0];
        bool has_level=level && !cJSON_IsNull(level);
        if (has_level && (!cJSON_IsNumber(level) || !isfinite(level->valuedouble) ||
            floor(level->valuedouble)!=level->valuedouble || level->valuedouble<1 || level->valuedouble>9)) ok=false;
        if (ok) {
            if (!strcmp(type->valuestring,"turn_on")) command->type=CMD_ON;
            else if (!strcmp(type->valuestring,"turn_off")) command->type=CMD_OFF;
            else if (!strcmp(type->valuestring,"set_level") && has_level) command->type=CMD_LEVEL;
            if (has_level) command->level=level->valueint;
        }
    }
    cJSON_Delete(root);
    return envelope;
}
static cJSON *burner_json(const induction_state_t *s)
{
    cJSON *b=cJSON_CreateObject();
    if (!b) return NULL;
    if (!cJSON_AddStringToObject(b,"burnerId",CONFIG_INDUCTION_BURNER_ID) ||
        !cJSON_AddStringToObject(b,"deviceState",induction_mode_name(s->mode)) ||
        !cJSON_AddNumberToObject(b,"level",s->level) ||
        !cJSON_AddNumberToObject(b,"temperature",s->temperature) ||
        !cJSON_AddNumberToObject(b,"activeSec",s->active_sec)) {
        cJSON_Delete(b); return NULL;
    }
    return b;
}
static bool send_json(const char *topic,cJSON *root,bool telemetry)
{
    if (!root) return false;
    char *body=cJSON_PrintUnformatted(root);
    bool ok=false;
    /* Bound network backlog; never accumulate old telemetry indefinitely. */
    /* ACKs must not be suppressed by the telemetry backlog threshold. */
    if (body && (!telemetry || esp_mqtt_client_get_outbox_size(s_mqtt)<8192))
        ok=esp_mqtt_client_enqueue(s_mqtt,topic,body,0,1,false,true)>=0;
    cJSON_free(body);
    cJSON_Delete(root);
    return ok;
}
static bool send_state(const induction_state_t *s)
{
    char timestamp[32];
    if (!utc(time(NULL),timestamp)) return false;
    cJSON *root=cJSON_CreateObject(),*burners=cJSON_CreateArray(),*b=burner_json(s),*last=cJSON_CreateObject();
    if (!root || !burners || !b || !last) {
        cJSON_Delete(root); cJSON_Delete(burners); cJSON_Delete(b); cJSON_Delete(last); return false;
    }
    cJSON_AddItemToArray(burners,b);
    cJSON_AddItemToObject(root,"burners",burners);
    cJSON_AddItemToObject(root,"lastControl",last);
    bool ok=cJSON_AddStringToObject(root,"reportedAt",timestamp) &&
        cJSON_AddStringToObject(root,"alarm",s->alarm ? "on":"off") &&
        cJSON_AddStringToObject(last,"publisher",s->publisher);
    if (ok && !strcmp(s->publisher,"api"))
        ok=cJSON_AddStringToObject(last,"commandId",s->command_id)!=NULL;
    if (!ok) { cJSON_Delete(root); return false; }
    return send_json(s_state_topic,root,true);
}
static bool send_ack(const command_ack_t *ack)
{
    char timestamp[32];
    if (!utc(ack->applied_at,timestamp)) return false;
    cJSON *root=cJSON_CreateObject(),*burner=burner_json(&ack->state);
    if (!root || !burner) { cJSON_Delete(root); cJSON_Delete(burner); return false; }
    cJSON_AddItemToObject(root,"burnerState",burner);
    if (!cJSON_AddStringToObject(root,"commandId",ack->command.id) ||
        !cJSON_AddStringToObject(root,"result",ack->result==ACK_APPLIED ? "applied":ack->result==ACK_REJECTED ? "rejected":"failed") ||
        !cJSON_AddStringToObject(root,"appliedAt",timestamp)) {
        cJSON_Delete(root); return false;
    }
    return send_json(s_ack_topic,root,false);
}
/* MQTT callbacks are serialized. Keep the large reply off the MQTT task stack. */
static void command_error(const induction_command_t *command,command_result_t result)
{
    static command_ack_t ack;
    memset(&ack,0,sizeof(ack));
    ack.command=*command;
    ack.state=app_snapshot();
    ack.result=result;
    ack.applied_at=time(NULL);
    if (!send_ack(&ack))
        ESP_LOGE(TAG,"Unable to enqueue command error ACK (transport or memory failure)");
}
static void mqtt_event(void *arg,esp_event_base_t base,int32_t id,void *data)
{
    esp_mqtt_event_handle_t e=data;
    static char rx[RX_MAX+1];
    static int used,total;
    static bool accepting;
    if (id==MQTT_EVENT_CONNECTED) {
        /* Mark ready only after command subscription is acknowledged. */
        esp_mqtt_client_subscribe(s_mqtt,s_command_topic,1);
    } else if (id==MQTT_EVENT_SUBSCRIBED) {
        xEventGroupSetBits(app_network,NET_ONLINE);
    } else if (id==MQTT_EVENT_DISCONNECTED) {
        xEventGroupClearBits(app_network,NET_ONLINE);
        accepting=false;
    } else if (id==MQTT_EVENT_DATA) {
        if (e->current_data_offset==0) {
            used=0; total=e->total_data_len;
            accepting=e->topic && e->topic_len==(int)strlen(s_command_topic) &&
                !memcmp(e->topic,s_command_topic,e->topic_len) && total>0 && total<=RX_MAX && !e->retain;
        }
        if (!accepting) return;
        if (e->current_data_offset!=used || e->data_len<0 || e->data_len>total-used) {
            accepting=false; return;
        }
        memcpy(rx+used,e->data,e->data_len); used+=e->data_len;
        if (used==total) {
            rx[used]=0; accepting=false;
            static command_request_t request;
            memset(&request,0,sizeof(request));
            request.received_us=esp_timer_get_time();
            if (!decode(rx,used,&request.command)) ESP_LOGW(TAG,"Malformed command ignored");
            else if (request.command.type>CMD_LEVEL)
                command_error(&request.command,ACK_REJECTED);
            else if (xQueueSend(app_commands,&request,0)!=pdTRUE)
                command_error(&request.command,ACK_FAILED);
        }
    }
}
static void wifi_event(void *arg,esp_event_base_t base,int32_t id,void *data)
{
    if (base==IP_EVENT && id==IP_EVENT_STA_GOT_IP) xEventGroupSetBits(s_link,WIFI_UP);
    else if (base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_link,WIFI_UP);
        xEventGroupClearBits(app_network,NET_ONLINE);
    }
}
static esp_err_t init_network(void)
{
    esp_err_t err=nvs_flash_init();
    if (err==ESP_ERR_NVS_NO_FREE_PAGES || err==ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase()); err=nvs_flash_init();
    }
    if (err!=ESP_OK) return err;
#define TRY(call) do { err=(call); if(err!=ESP_OK) return err; } while(0)
    TRY(esp_netif_init()); TRY(esp_event_loop_create_default());
    if (!esp_netif_create_default_wifi_sta()) return ESP_ERR_NO_MEM;
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    TRY(esp_wifi_init(&init));
    TRY(esp_event_handler_register(WIFI_EVENT,WIFI_EVENT_STA_DISCONNECTED,wifi_event,NULL));
    TRY(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    wifi_config_t wifi={0};
    if (strlen(CONFIG_INDUCTION_WIFI_SSID)>32 || strlen(CONFIG_INDUCTION_WIFI_PASSWORD)>63)
        return ESP_ERR_INVALID_ARG;
    memcpy(wifi.sta.ssid,CONFIG_INDUCTION_WIFI_SSID,strlen(CONFIG_INDUCTION_WIFI_SSID));
    memcpy(wifi.sta.password,CONFIG_INDUCTION_WIFI_PASSWORD,strlen(CONFIG_INDUCTION_WIFI_PASSWORD));
    wifi.sta.threshold.authmode=CONFIG_INDUCTION_WIFI_PASSWORD[0] ? WIFI_AUTH_WPA2_PSK:WIFI_AUTH_OPEN;
    TRY(esp_wifi_set_storage(WIFI_STORAGE_RAM)); TRY(esp_wifi_set_mode(WIFI_MODE_STA));
    TRY(esp_wifi_set_config(WIFI_IF_STA,&wifi));
    esp_sntp_config_t sntp=ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_INDUCTION_NTP_SERVER);
    TRY(esp_netif_sntp_init(&sntp)); TRY(esp_wifi_start());
    TRY(esp_wifi_set_ps(WIFI_PS_NONE)); /* Prefer control responsiveness over power saving. */
    return ESP_OK;
#undef TRY
}
void network_task(void *arg)
{
    if (!CONFIG_INDUCTION_WIFI_SSID[0] || !CONFIG_INDUCTION_MQTT_URI[0]) {
        ESP_LOGW(TAG,"Configure Wi-Fi/MQTT in menuconfig; local controls remain active");
        vTaskDelete(NULL); return;
    }
    snprintf(s_state_topic,sizeof(s_state_topic),"%s/state",CONFIG_INDUCTION_TOPIC_PREFIX);
    snprintf(s_command_topic,sizeof(s_command_topic),"%s/command",CONFIG_INDUCTION_TOPIC_PREFIX);
    snprintf(s_ack_topic,sizeof(s_ack_topic),"%s/ack",CONFIG_INDUCTION_TOPIC_PREFIX);
    s_link=xEventGroupCreate(); configASSERT(s_link);
    esp_err_t err=init_network();
    if (err!=ESP_OK) { ESP_LOGE(TAG,"Network init: %s",esp_err_to_name(err)); vTaskDelete(NULL); return; }
    int64_t reconnect_at=0,publish_at=0;
    uint32_t published_revision=UINT32_MAX;
    bool was_online=false;
    for (;;) {
        int64_t now=esp_timer_get_time();
        if (!(xEventGroupGetBits(s_link)&WIFI_UP) && now>=reconnect_at) {
            esp_wifi_connect(); reconnect_at=now+5000000;
        }
        char timestamp[32];
        /* Local operation never waits for the clock. Remote commands begin only with valid UTC. */
        if (!s_mqtt && (xEventGroupGetBits(s_link)&WIFI_UP) && utc(time(NULL),timestamp)) {
            esp_mqtt_client_config_t config={.broker.address.uri=CONFIG_INDUCTION_MQTT_URI,
                .credentials.client_id=CONFIG_INDUCTION_DEVICE_ID,
                .credentials.username=CONFIG_INDUCTION_MQTT_USERNAME[0] ? CONFIG_INDUCTION_MQTT_USERNAME:NULL,
                .credentials.authentication.password=CONFIG_INDUCTION_MQTT_PASSWORD[0] ? CONFIG_INDUCTION_MQTT_PASSWORD:NULL,
                .network.reconnect_timeout_ms=5000,.buffer.size=1280,
                .task.priority=5};
            s_mqtt=esp_mqtt_client_init(&config);
            if (s_mqtt) {
                ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt,ESP_EVENT_ANY_ID,mqtt_event,NULL));
                ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt));
            }
        }
        bool online=(xEventGroupGetBits(app_network)&NET_ONLINE)!=0;
        if (online) {
            if (!was_online) publish_at=0;
            static command_ack_t ack;
            if (xQueuePeek(app_acks,&ack,0)==pdTRUE && send_ack(&ack))
                xQueueReceive(app_acks,&ack,0);
            induction_state_t s=app_snapshot();
            if ((now>=publish_at || s.revision!=published_revision) && send_state(&s)) {
                published_revision=s.revision; publish_at=now+3000000;
            }
        }
        was_online=online;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
