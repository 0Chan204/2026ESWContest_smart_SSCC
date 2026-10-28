#pragma once

#include "water_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"

#define WP_NETWORK_ONLINE BIT0

typedef struct {
    int64_t received_us;
    size_t length;
    char payload[WP_MAX_PAYLOAD + 1];
} wp_request_t;

extern QueueHandle_t wp_requests;
extern EventGroupHandle_t wp_network_events;

void wp_network_task(void *arg);
/* Takes ownership of JSON, even on failure. All messages use QoS 1, retain false. */
bool wp_publish(bool ack, cJSON *root);
