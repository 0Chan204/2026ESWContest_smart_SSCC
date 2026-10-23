#pragma once
#include "induction_model.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include <time.h>
#define NET_ONLINE BIT0
#define COMMAND_DEPTH 16
#define ACK_DEPTH 32
typedef struct { induction_command_t command; int64_t received_us; } command_request_t;
typedef enum { ACK_APPLIED, ACK_REJECTED, ACK_FAILED } command_result_t;
typedef struct {
    induction_command_t command;
    induction_state_t state;
    command_result_t result;
    time_t applied_at;
} command_ack_t;
extern QueueHandle_t app_commands, app_acks;
extern EventGroupHandle_t app_network;
induction_state_t app_snapshot(void);
void network_task(void *arg);
