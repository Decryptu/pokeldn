/* pokeldn bridge: a second board (XIAO ESP32C5 or XIAO ESP32S3) that carries a radio board's UART host
   link to a TCP port on the network, so pokeldn runs on another machine with
   POKELDN_RADIO=esp32:socket://ADDRESS:PORT. docs/hardware_esp32.md, The network bridge. */
#pragma once

#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "sdkconfig.h"

/* The radio's UART build starts here and the host sends no BAUD over socket://. */
#define BRIDGE_BAUD 921600
#define BRIDGE_DEFAULT_PORT 47811
/* Pins, LED and button: menuconfig's "pokeldn bridge" (main/Kconfig.projbuild). */
#define BRIDGE_UART_TX CONFIG_BRIDGE_UART_TX_GPIO
#define BRIDGE_UART_RX CONFIG_BRIDGE_UART_RX_GPIO

/* Why a host connection ended (bridge.c note_drop). */
typedef enum {
    DROP_NONE,
    DROP_SEND_TIMEOUT,   /* send() to the host waited past SO_SNDTIMEO */
    DROP_SEND_ERROR,     /* send() failed otherwise */
    DROP_CLOSED,         /* the host closed the connection */
    DROP_KEEPALIVE,      /* the host stopped answering TCP keepalive */
    DROP_RESET,          /* recv() failed otherwise, a reset */
    DROP_REPLACED,       /* a newer host connected */
    DROP_REASONS,
} drop_reason_t;

typedef struct {
    atomic_uint radio_bytes, host_bytes;   /* radio to host, host to radio */
    atomic_uint radio_frames;              /* COBS frames from the radio */
    atomic_uint unheard;                   /* radio bytes read with no host connected */
    atomic_uint uart_errors;               /* FIFO overflow, ring full, framing */
    atomic_uint sessions;                  /* host connections accepted */
    atomic_bool host;                      /* a host is connected */
    atomic_uint host_ip;                   /* its IPv4 address, network order */
    atomic_uint host_since_s;              /* uptime when it connected */
    atomic_uint radio_seen_s;              /* uptime of the last radio byte, 0 = none yet */
    atomic_uint drops[DROP_REASONS];       /* host connections ended, by reason */
    atomic_int last_drop;                  /* drop_reason_t of the last one */
    atomic_int last_drop_errno;
    atomic_uint last_drop_s;               /* its uptime, 0 = none yet */
} bridge_stats_t;

extern bridge_stats_t g_stats;

/* The radio's last INFO text (its HELLO reply or boot announcement) and recent LOG lines,
   read from the stream as it passes. */
void bridge_radio_info(char *out, size_t size);
/* Appends the log as a JSON array of strings; returns the bytes written. */
size_t bridge_radio_log_json(char *out, size_t size);
uint16_t bridge_port(void);
void bridge_set_port(uint16_t port);   /* stored; applies after a restart */
/* Radio bytes waiting in the UART ring for the host: Wi-Fi falling behind the radio. */
size_t bridge_uart_backlog(void);

/* The LiPo on the battery pads (battery.c), read once a second. Charging is the voltage's trend:
   no pin reports it. */
typedef struct {
    bool present, charging;
    uint8_t percent;
    uint16_t mv;
} battery_t;

void battery_start(void);
battery_t battery_read(void);

/* The two status pixels (pixels.c): the network, then the link to the host and the radio. */
void pixels_start(void);
void pixels_tick(unsigned tick, unsigned held);   /* every 50 ms; held: ticks BOOT has been down */
bool pixels_present(void);
uint8_t pixels_brightness(void);                  /* percent */
void pixels_set_brightness(uint8_t percent);      /* stored; applies at once */
void pixels_identify(void);                       /* both blink for 5 s */
void pixels_show_battery(void);                   /* both show the charge for 3 s: a short BOOT press */
void pixels_restarting(void);                     /* both white until the restart */

typedef enum { NET_STARTING, NET_CONNECTING, NET_ONLINE, NET_SETUP } net_state_t;

void net_start(void);
net_state_t net_state(void);
/* The configured network's name, the station's address, signal and channel (above 14: 5 GHz). */
void net_station(char *ssid, size_t ssid_size, char *ip, size_t ip_size, int *rssi, int *channel);
/* Whether the chip has 5 GHz (the C5), and whether the station is held to it (net.c set_band). */
bool net_can_5g(void);
bool net_force_5g(void);
void net_set_force_5g(bool force);   /* stored; applies after a restart */
/* The setup access point's name and whether it is up. */
bool net_setup_ap(char *ssid, size_t size);
/* Stores credentials and joins; an empty ssid forgets them and opens setup. */
void net_configure(const char *ssid, const char *password);
/* Scans and writes a JSON array of {ssid, rssi, channel, secure}; returns the bytes written. */
size_t net_scan_json(char *out, size_t size);

void web_start(void);
void captive_start(void);
void captive_stop(void);

/* Escapes text into a JSON string body (no quotes); returns the bytes written. */
size_t json_escape(char *out, size_t size, const char *text, size_t length);
