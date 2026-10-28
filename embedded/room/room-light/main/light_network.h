#pragma once

#include "light_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"

#define RL_NETWORK_ONLINE BIT0

typedef struct {
    size_t length;
    char payload[RL_MAX_PAYLOAD + 1];
} rl_request_t;

extern QueueHandle_t rl_requests;
extern EventGroupHandle_t rl_network_events;

void rl_network_task(void *arg);
/* Takes ownership of JSON, even on failure. All messages use QoS 1, retain false. */
bool rl_publish(bool ack, cJSON *root);
