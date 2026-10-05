#!/usr/bin/env python3
"""Decode an ESP32 SNIFF trace from a retail LDN session.

The console derives its CCMP key directly from the encrypted LDN advertisement (there is no
four-way WPA handshake).  This tool finds and decrypts that advertisement with prod.keys, derives
the data key, decrypts 802.11 data frames, unpacks QoS A-MSDUs, and writes UDP/Pia messages as
JSONL for the existing protocol-analysis workflow.
"""
import argparse
import json
import os
import struct
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

import ldn
from ldn import wlan

from pokeldn import sv
from pokeldn.ldn import pia6, reliable5


RX_SNIFF = 0x8C
LDN_ACTION = bytes.fromhex("7f0022aa04000101")


def trace_frames(path):
    with open(path, "r", encoding="ascii") as f:
        for line in f:
            fields = line.split()
            if len(fields) != 4 or fields[1] != "<" or int(fields[2], 16) != RX_SNIFF:
                continue
            payload = bytes.fromhex(fields[3])
            if len(payload) >= 5:
                yield float(fields[0]), payload[5:]


def frame_control(frame):
    return int.from_bytes(frame[:2], "little") if len(frame) >= 2 else 0


def find_network(path, prod_keys):
    derivation = ldn.KeyDerivation(ldn.load_keys(prod_keys), 1)
    for _at, frame in trace_frames(path):
        fc = frame_control(frame)
        if ((fc >> 2) & 3, (fc >> 4) & 15) != (0, 13) or len(frame) < 24:
            continue
        action = frame[24:]
        if not action.startswith(LDN_ACTION):
            continue
        advert = ldn.AdvertisementFrame(derivation, 1)
        try:
            advert.decode(action)
        except Exception:
            continue
        info = ldn.NetworkInfo(1)
        info.address = wlan.MACAddress(frame[10:16])
        info.channel = 0
        info.band = 2
        info.parse_advertisement(advert)
        return info, derivation
    raise RuntimeError("no decryptable LDN advertisement found in trace")


def decrypt_dot11(frame, key):
    """Return (plaintext MSDU, A-MSDU flag, transmitter, sequence, tid), or None."""
    fc = frame_control(frame)
    ftype, subtype = (fc >> 2) & 3, (fc >> 4) & 15
    if ftype != 2 or subtype not in (0, 8) or len(frame) < 24:
        return None
    qos = subtype == 8
    header_len = 24 + (2 if qos else 0)
    if len(frame) < header_len + 8:
        return None
    tid = frame[24] & 0x0F if qos else 0
    amsdu = bool(qos and (frame[24] & 0x80))
    # DataFrame deliberately rejects A-MSDUs.  The CCMP AAD masks QoS control to the TID, so
    # clearing only the A-MSDU-present bit lets its proven decoder authenticate the outer frame.
    decoded = bytearray(frame)
    if amsdu:
        decoded[24] &= 0x7F
    data = wlan.DataFrame()
    try:
        data.decode(bytes(decoded))
        data.decrypt(key)
    except Exception:
        return None
    seq = int.from_bytes(frame[22:24], "little") >> 4
    return data.payload, amsdu, frame[10:16], seq, tid


def msdus(payload, amsdu):
    if not amsdu:
        yield payload
        return
    offset = 0
    while offset + 14 <= len(payload):
        size = int.from_bytes(payload[offset + 12:offset + 14], "big")
        end = offset + 14 + size
        if size == 0 or end > len(payload):
            return
        yield payload[offset + 14:end]
        offset = (end + 3) & ~3


def ipv4_udp(msdu):
    if len(msdu) < 8 or msdu[:6] != bytes.fromhex("aaaa03000000"):
        return None
    if int.from_bytes(msdu[6:8], "big") != 0x0800:
        return None
    packet = msdu[8:]
    if len(packet) < 20 or packet[0] >> 4 != 4 or packet[9] != 17:
        return None
    ihl = (packet[0] & 15) * 4
    if ihl < 20 or len(packet) < ihl + 8:
        return None
    total = min(int.from_bytes(packet[2:4], "big"), len(packet))
    udp = packet[ihl:total]
    length = int.from_bytes(udp[4:6], "big")
    if length < 8:
        return None
    ip = lambda b: ".".join(str(x) for x in b)
    return (ip(packet[12:16]), ip(packet[16:20]),
            int.from_bytes(udp[:2], "big"), int.from_bytes(udp[2:4], "big"),
            udp[8:min(length, len(udp))])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("trace")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--records-out", help="also extract the host's 0x81:0 identity record set")
    args = ap.parse_args()

    network, derivation = find_network(args.trace, os.path.expanduser(args.keys))
    ccmp_key = derivation.derive_data_key(network.server_random, sv.PASSPHRASE)
    session = sv.session_keys(network.ssid)
    host_mac = bytes(network.address).hex(":")
    print(f"[decode] ssid={network.ssid.hex()} host={host_mac} "
          f"scene={network.scene_id} players={network.num_participants}/{network.max_participants}")

    frames = decrypted = udp_count = pia_count = auth_count = data_count = 0
    protocols = {}
    seen_wifi = set()
    host_records = {}
    host_record_order = []
    with open(args.out, "w", encoding="utf-8") as out:
        out.write(json.dumps({"rec": "network", "ssid": network.ssid.hex(),
                              "host_mac": host_mac, "server_random": network.server_random.hex(),
                              "application_data": network.application_data.hex()}) + "\n")
        for at, frame in trace_frames(args.trace):
            frames += 1
            decoded = decrypt_dot11(frame, ccmp_key)
            if decoded is None:
                continue
            payload, amsdu, transmitter, seq, tid = decoded
            # Drop only 802.11 retry copies; Pia-level retransmissions use a fresh Wi-Fi sequence.
            wifi_id = (transmitter, seq, tid)
            if wifi_id in seen_wifi:
                continue
            seen_wifi.add(wifi_id)
            decrypted += 1
            for msdu in msdus(payload, amsdu):
                parsed = ipv4_udp(msdu)
                if parsed is None:
                    continue
                src, dst, sport, dport, datagram = parsed
                udp_count += 1
                row = {"rec": "udp", "t": at, "src": src, "dst": dst,
                       "sport": sport, "dport": dport, "hex": datagram.hex()}
                if not pia6.is_pia6(datagram):
                    out.write(json.dumps(row) + "\n")
                    continue
                pia_count += 1
                header, plain, footer = pia6.parse_packet(
                    session.session_key, src, session.network_id, datagram)
                row.update(rec="pia", src_var=header.src_var, dst_var=header.dst_var,
                           packet_id=header.packet_id, authenticated=plain is not None,
                           footer=footer)
                out.write(json.dumps(row) + "\n")
                if plain is None:
                    continue
                auth_count += 1
                try:
                    messages = list(pia6.parse_messages(plain))
                except Exception as exc:
                    out.write(json.dumps({"rec": "parse_error", "t": at, "src": src,
                                          "error": str(exc), "plain": plain.hex()}) + "\n")
                    continue
                for message in messages:
                    protocols[message.protocol] = protocols.get(message.protocol, 0) + 1
                    msgrow = {"rec": "msg", "t": at, "src": src, "dst": dst,
                              "src_var": header.src_var, "dst_var": header.dst_var,
                              "protocol": message.protocol, "port": message.port,
                              "flags": message.message_flags, "payload": message.payload.hex()}
                    out.write(json.dumps(msgrow) + "\n")
                    if message.protocol not in (0x7C, 0x80, 0x81):
                        continue
                    try:
                        reliable = reliable5.parse(message.payload)
                    except ValueError:
                        continue
                    if not reliable["flags"] & reliable5.FLAG_APPLICATION_DATA:
                        continue
                    data_count += 1
                    if (args.records_out and src.endswith(".1")
                            and message.protocol == 0x81 and message.port == 0
                            and reliable["sequence_id"] not in host_records):
                        host_records[reliable["sequence_id"]] = reliable["payload"]
                        host_record_order.append(reliable["sequence_id"])
                    out.write(json.dumps({"rec": "data", "t": at, "src": src, "dst": dst,
                                          "protocol": message.protocol, "port": message.port,
                                          "seq": reliable["sequence_id"],
                                          "reliable_flags": reliable["flags"],
                                          "payload": reliable["payload"].hex()}) + "\n")

    if args.records_out:
        os.makedirs(args.records_out, exist_ok=True)
        for sequence, payload in host_records.items():
            with open(os.path.join(args.records_out, f"{sequence:03d}.bin"), "wb") as f:
                f.write(payload)
        with open(os.path.join(args.records_out, "order"), "w", encoding="ascii") as f:
            f.writelines(f"{sequence}\n" for sequence in host_record_order)
        print(f"[decode] extracted {len(host_records)} host identity records -> "
              f"{args.records_out}")

    summary = " ".join(f"0x{k:02x}={v}" for k, v in sorted(protocols.items()))
    print(f"[decode] air={frames} decrypted={decrypted} udp={udp_count} "
          f"pia={pia_count} authenticated={auth_count} data={data_count}")
    print(f"[decode] protocols: {summary or 'none'}")
    print(f"[decode] wrote {args.out}")


if __name__ == "__main__":
    main()
