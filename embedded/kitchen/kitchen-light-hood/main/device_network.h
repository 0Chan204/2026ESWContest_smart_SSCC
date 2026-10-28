#pragma once

#include "device_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"

#define KLH_NETWORK_ONLINE BIT0

typedef struct {
    klh_device_t device;
    size_t length;
    char payload[KLH_MAX_PAYLOAD + 1];
} klh_request_t;

extern QueueHandle_t klh_requests;
extern EventGroupHandle_t klh_network_events;

void klh_network_task(void *arg);
/* Takes ownership of JSON, even on failure. All messages use QoS 1, retain false. */
bool klh_publish(klh_device_t device, bool ack, cJSON *root);
