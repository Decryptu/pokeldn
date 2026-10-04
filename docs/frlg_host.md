---
title: Host implementation
parent: FireRed and LeafGreen
nav_order: 7
---

# Host implementation

`bin/frlg_trade_host.py` is the FireRed/LeafGreen Direct Corner leader: a Switch joins the host's
LDN network, Pia establishes the peer session, and Reliable carries an emulated parent RFU link
ending in the leader-side trade state machine. `bin/frlg_mg_host.py` reuses everything below the
activity.

## Components and ownership

| component | owns |
|---|---|
| `TradeRunConfig` | immutable run configuration: `TrainerProfile`, `TradePlan`, `LdnConfig`, `HostOptions` or `JoinerOptions` |
| `HostApplication` | resource ordering: validation, transport startup, beacon injection, event loop, interruption, cleanup; activity hooks supply messages and persistence, so trade and Mystery Gift share the loop |
| `HostTransport` | the LDN AP, virtual interfaces, participant events, UDP :12345; no Pia parsing |
| `HostPeerProtocol` | one peer's Pia state: Net, Session acceptance, RTT, packet ids, nonce selection, encryption, framing, Reliable batching; emits `OutboundDatagram` |
| `HostSession` | Reliable + `RFULeader` + the activity engine (`engine=` picks trade or Mystery Gift); no socket, the boundary the offline end-to-end tests use |
| `HostTradeEngine` | leader room entry, party and card exchange, selection, confirmation, animation and save barriers, cancel, room exit, close grace; `HostTradeTiming` names the frame counts |
| `BeaconInjector` | its raw monitor socket and worker thread |

Datagrams flow Switch, `HostTransport`, `HostPeerProtocol`, `HostSession`, `RFULeader`,
`HostTradeEngine` (child command row in, parent row out) and back. Timer deadlines come from the
peer protocol, so Net/Session retries, RTT probes, retransmission and the ~59.727 Hz tick do not
depend on a polling delay.

## Startup and session establishment

1. The CLI hands `TradeRunConfig` to `HostApplication`, which starts an inactive Direct Corner
   network and the periodic beacons.
2. The Switch joins; `on_participant_joined()` sends a Pia Net connection request, retried until ACK.
3. The Switch answers with the Net ACK and a Session join request; the host sends a Session update
   and a unicast join response (a diagnostic setting reverses the pair), and the Switch acks.
4. RTT and Reliable/RFU traffic start, and the application-data property is set active.

Malformed Pia, bad padding, failed authentication, incomplete Reliable tiling and mismatched Session
identities are logged and ignored. A Session request is accepted only when its constant id, Pia
variables, source IP and encrypted header agree with the current LDN peer.

## Trade and room-exit lifecycle

```mermaid
stateDiagram-v2
    [*] --> PlayerExchange
    PlayerExchange --> RoomEntry: LinkPlayer and trainer card
    RoomEntry --> PartyExchange: seat route and entry barriers
    PartyExchange --> Selection: party, mail, ribbons
    Selection --> Confirmation: Switch selects; leader offers configured slot
    Confirmation --> Animation: both confirm
    Animation --> Save: trade committed
    Save --> PartyExchange: another configured trade
    Save --> MenuExit: final party refresh
    MenuExit --> RoomExit: both cancel; five-second field wait
    RoomExit --> CloseGrace: Switch confirms room exit
    CloseGrace --> Disconnect: fifteen seconds of peer traffic
    Disconnect --> [*]
```

After the final trade the host waits for the Switch trade menu; the player selects CANCEL and
confirms YES, and the host answers with `BOTH_CANCEL_TRADE` at once. The host finishes the standby
barriers, waits five seconds before leaving the room unless the Switch leaves first, and keeps
normal peer traffic for fifteen seconds after the Switch confirms close (`READY_CLOSE_LINK`), then
queues the RFU disconnect. It answers the console's Session leave request with type 4
([frlg_link.md](frlg_link.md), Leaving the Pia session). An LDN leave event stops peer output at
once.

## Shutdown and cleanup

After the disconnect: save the received Pokemon if one exists, stop and join the beacon worker,
close sockets and the network, clean the LDN vifs. The same cleanup runs on normal completion,
`KeyboardInterrupt`, startup failure after partial allocation, and beacon-worker failure. Saving a
received Pokemon is independent of capture logging.

Every host, trade, battle and Mystery Gift alike, stops when the console leaves LDN
(`HostApplication.run`): at once when no close was confirmed, after a 2 s settle
(`HOST_CLOSE_SETTLE_SECONDS`) when it was. `--end-on-success` stops a Mystery Gift host once a
successful delivery's disconnect is sent, without waiting for the console to leave; its `--idle-timeout`
stops it after that many seconds without Switch traffic.

## Trainer profile propagation

`pokeldn.config.DEFAULT_TRAINER` is the default identity. Each CLI derives an immutable per-run
`TrainerProfile` (`--ot`, `--version`, decimal `--id TID[:SID]`), validates Gen III names and ranges,
and derives every view from it:

| view | carries |
|---|---|
| LDN discovery | name and public TID |
| Pia Session | UTF-8 participant name |
| LinkPlayer | `SID << 16 \| TID`, version, language, gender and progress flags; Gen III name |
| trainer card | Gen III name; the host pads with `0xFF`, joiners keep native `0x00` |

## Failure handling

- Preflight rejects a radio without AP support.
- On a Linux Wi-Fi card the AP must mark the station `NL80211_STA_FLAG_AUTHORIZED` after LDN
  authentication. Driver profiles and flags are on [Adapters](hardware_adapters.md).
- Transport or beacon-thread failure aborts the run and unwinds what was created.
- An unexpected participant leave halts output. After a room-close confirmation, a participant that
  disappears from LDN ends the run after a 2 s settle (`HOST_CLOSE_SETTLE_SECONDS`) rather than at
  once; the fifteen-second grace runs to its end only while the participant stays.
- Output is written only for a complete received Pokemon; input `.pk3`/`.ek3` files are never
  modified.

## Extending the host

Add behaviour at the lowest layer that understands it: settings in the run configuration, OS and
network in the application or transport, Pia in `HostPeerProtocol`, RFU in `RFULeader`, Direct
Corner decisions in `HostTradeEngine`. Test each boundary on its emitted datagrams, payloads, frames
or command rows.

The host serves one Switch. More peers need a `HostPeerProtocol` each (own Pia variables, nonces,
packet ids) and a game-level RFU policy; raising the LDN participant limit is not enough.

## Unresolved

- Whether the console needs the fifteen-second close grace is unmeasured
  (`HostTradeTiming.post_client_close_grace_frames`); it spans the console's fade and warp after
  `READY_CLOSE_LINK`.

## Source map

| source | responsibility |
|---|---|
| `bin/frlg_trade_host.py` | CLI, configuration, entry point |
| `pokeldn/frlg/host_cli.py` | shared host CLI options |
| `pokeldn/frlg/link/host_app.py` | `HostApplication` |
| `pokeldn/frlg/config.py` | trainer, trade plan, Mystery Gift payload, LDN, role and run configuration |
| `pokeldn/frlg/link/trade_runtime.py` | CLI logging, party loading, slot parsing, output saving |
| `pokeldn/frlg/link/host_beacon.py` | captured trade beacon, discovery mutation, `BeaconInjector` |
| `pokeldn/host_support.py` | OS-facing support (sudo-aware key-path resolution) |
| `pokeldn/ldn/transport.py` | `HostTransport` |
| `pokeldn/ldn/host_pia.py` | Pia framing, `HostPeerProtocol` |
| `pokeldn/frlg/link/host_session.py` | `HostSession` |
| `pokeldn/ldn/reliable.py` | Reliable |
| `pokeldn/gba/rfu_leader.py` | `RFULeader`: parent framing, NI/UNI handshake, echo table |
| `pokeldn/frlg/link/host_trade.py` | `HostTradeEngine`, `HostTradeTiming` |
| `pokeldn/frlg/link/linkplayer.py` | LinkPlayer and trainer-card encoders |
| `pokeldn/ldn/ldntrace.py` | optional JSONL diagnostics |
