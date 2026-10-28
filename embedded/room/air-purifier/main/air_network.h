#pragma once

#include "air_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"

#define AP_NETWORK_ONLINE BIT0

typedef struct {
    size_t length;
    char payload[AP_MAX_PAYLOAD + 1];
} ap_request_t;

extern QueueHandle_t ap_requests;
extern EventGroupHandle_t ap_network_events;

void ap_network_task(void *arg);
/* Takes ownership of JSON, even on failure. All messages use QoS 1, retain false. */
bool ap_publish(bool ack, cJSON *root);
