#pragma once

#include "device_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"

#define TLF_NETWORK_ONLINE BIT0

typedef struct {
    tlf_device_t device;
    size_t length;
    char payload[TLF_MAX_PAYLOAD + 1];
} tlf_request_t;

extern QueueHandle_t tlf_requests;
extern EventGroupHandle_t tlf_network_events;

void tlf_network_task(void *arg);
/* Takes ownership of JSON, even on failure. All messages use QoS 1, retain false. */
bool tlf_publish(tlf_device_t device, bool ack, cJSON *root);
