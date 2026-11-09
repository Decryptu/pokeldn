/* Captive DNS while the setup access point is up: every A query answers 192.168.4.1, so a phone
   that joins POKELDN-BRIDGE-XXXX opens the setup page by itself. */
#include "bridge.h"

#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

static const char *TAG = "captive";
/* lwIP must not close a socket another task waits on: the task polls `s_wanted` each second and
   closes its own socket. */
static atomic_bool s_wanted, s_running;

static void dns_task(void *arg)
{
    const int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    const struct sockaddr_in address = {
        .sin_family = AF_INET, .sin_port = htons(53), .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    const struct timeval timeout = {.tv_sec = 1};
    if (s < 0 || bind(s, (const struct sockaddr *)&address, sizeof(address))) {
        ESP_LOGE(TAG, "cannot bind port 53");
        if (s >= 0) close(s);
        atomic_store(&s_running, false);
        vTaskDelete(NULL);
    }
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    static uint8_t packet[512];
    while (atomic_load(&s_wanted)) {
        struct sockaddr_in from;
        socklen_t from_len = sizeof(from);
        const int n = recvfrom(s, packet, sizeof(packet) - 16, 0, (struct sockaddr *)&from, &from_len);
        if (n < 12 || (packet[2] & 0x80) || packet[4] != 0 || packet[5] != 1) continue;   /* one question */
        size_t at = 12;
        while (at < (size_t)n && packet[at]) at += packet[at] + 1;
        if (at + 5 > (size_t)n) continue;
        const bool a_query = packet[at + 1] == 0 && packet[at + 2] == 1;
        size_t length = at + 5;
        packet[2] = 0x81;   /* response, recursion desired */
        packet[3] = 0x80;   /* recursion available, no error */
        packet[6] = 0;
        packet[7] = a_query;
        memset(packet + 8, 0, 4);
        if (a_query) {
            static const uint8_t answer[] = {
                0xc0, 0x0c, 0, 1, 0, 1, 0, 0, 0, 60, 0, 4, 192, 168, 4, 1,
            };
            memcpy(packet + length, answer, sizeof(answer));
            length += sizeof(answer);
        }
        sendto(s, packet, length, 0, (struct sockaddr *)&from, from_len);
    }
    close(s);
    atomic_store(&s_running, false);
    /* Started again while this one was leaving: captive_start saw it running and left it to us. */
    if (atomic_load(&s_wanted) && !atomic_exchange(&s_running, true))
        xTaskCreate(dns_task, "captive", 3072, NULL, 3, NULL);
    vTaskDelete(NULL);
}

void captive_start(void)
{
    atomic_store(&s_wanted, true);
    if (atomic_exchange(&s_running, true)) return;   /* still running: it keeps going */
    xTaskCreate(dns_task, "captive", 3072, NULL, 3, NULL);
}

void captive_stop(void) { atomic_store(&s_wanted, false); }
