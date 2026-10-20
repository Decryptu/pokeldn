package org.pokeldn.usbprobe;

import android.hardware.usb.*;
import java.io.IOException;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

/** The board's serial link over Android's USB host API: Espressif's native USB (CDC-ACM), or a classic
 *  ESP32's CP210x bridge through its vendor requests [Linux drivers/usb/serial/cp210x.c]. */
public final class UsbStream implements AutoCloseable {
    private static final int CP210X_OUT = 0x41;   /* vendor request to the interface */
    private static final int CP210X_IFC_ENABLE = 0x00, CP210X_SET_LINE_CTL = 0x03, CP210X_SET_MHS = 0x07,
        CP210X_SET_BAUDRATE = 0x1e;
    private final boolean cp210x;
    private final UsbDeviceConnection connection;
    private final UsbInterface control, data;
    private final UsbEndpoint input, output;
    private volatile boolean closed;
    private volatile IOException readFailure;
    private final ArrayBlockingQueue<byte[]> incoming = new ArrayBlockingQueue<>(256);
    private Thread reader;
    private Thread writer;
    private volatile boolean queuedWrites;
    private volatile IOException writeFailure;
    private final ArrayBlockingQueue<byte[]> outgoing = new ArrayBlockingQueue<>(1024);
    private final Object writeProgress = new Object();
    private long enqueuedBytes, sentBytes;
    private byte[] remainder = new byte[0];

    public UsbStream(UsbManager manager, UsbDevice device) throws IOException {
        cp210x = Setup.isCp210x(device.getVendorId(), device.getProductId());
        UsbInterface ctl = null, dat = null;
        for (int i = 0; i < device.getInterfaceCount(); i++) {
            UsbInterface iface = device.getInterface(i);
            if (cp210x && i == 0) ctl = dat = iface;    // one vendor interface: requests and bulk data
            if (!cp210x && iface.getInterfaceClass() == 2) ctl = iface;
            if (!cp210x && iface.getInterfaceClass() == 10) dat = iface;
        }
        if (ctl == null || dat == null) throw new IOException(cp210x ? "Missing CP210x interface" : "Missing CDC interfaces");
        control = ctl; data = dat;
        UsbEndpoint in = null, out = null;
        for (int i = 0; i < data.getEndpointCount(); i++) {
            UsbEndpoint endpoint = data.getEndpoint(i);
            if (endpoint.getType() != UsbConstants.USB_ENDPOINT_XFER_BULK) continue;
            if (endpoint.getDirection() == UsbConstants.USB_DIR_IN) in = endpoint;
            else out = endpoint;
        }
        if (in == null || out == null) throw new IOException("Missing bulk endpoints");
        input = in; output = out;
        connection = manager.openDevice(device);
        if (connection == null) throw new IOException("USB open failed");
        try {
            if (!connection.claimInterface(control, true) || data != control && !connection.claimInterface(data, true))
                throw new IOException("USB interface claim failed");
            // 8N1 (and the CP210x's UART switched on), then DTR and RTS low: a classic board's
            // auto-reset circuit leaves EN and IO0 high, the chip running.
            if (cp210x && (connection.controlTransfer(CP210X_OUT, CP210X_IFC_ENABLE, 1, control.getId(), null, 0, 1000) < 0
                    || connection.controlTransfer(CP210X_OUT, CP210X_SET_LINE_CTL, 0x0800, control.getId(), null, 0, 1000) < 0))
                throw new IOException("CP210x setup failed");
            setBaud(115200);
            setLines(false, false);
        } catch (IOException error) { close(); throw error; }
        reader = new Thread(this::receiveLoop, "android-usb-reader");
        reader.start();
        writer = new Thread(this::writeLoop, "android-usb-writer");
        writer.start();
    }

    private void receiveLoop() {
        UsbRequest request = new UsbRequest();
        try {
            if (!request.initialize(connection, input)) throw new IOException("USB request init failed");
            ByteBuffer buffer = ByteBuffer.allocateDirect(16384);
            while (!closed) {
                buffer.clear();
                if (!request.queue(buffer)) throw new IOException("USB request queue failed");
                UsbRequest result = connection.requestWait();
                if (closed) break;
                if (result == null) throw new IOException("USB receive failed");
                int count = buffer.position();
                if (count == 0) continue;
                byte[] bytes = new byte[count];
                buffer.flip(); buffer.get(bytes);
                if (!incoming.offer(bytes)) throw new IOException("Android USB receive queue overflow");
            }
        } catch (Exception error) {
            if (!closed) readFailure = new IOException("USB reader: " + error, error);
        } finally { request.cancel(); request.close(); }
    }

    public synchronized byte[] read(int size) throws IOException {
        if (closed) throw new IOException("USB stream closed");
        if (readFailure != null) throw readFailure;
        try {
            byte[] bytes = remainder.length > 0 ? remainder : incoming.poll(20, TimeUnit.MILLISECONDS);
            if (bytes == null) return new byte[0];
            int count = Math.min(size, bytes.length);
            remainder = Arrays.copyOfRange(bytes, count, bytes.length);
            return Arrays.copyOf(bytes, count);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IOException(error);
        }
    }

    /** Bytes received and not yet read. */
    public synchronized int available() {
        int count = remainder.length;
        for (byte[] chunk : incoming) count += chunk.length;
        return count;
    }

    /** CDC SET_CONTROL_LINE_STATE: bit 0 DTR, bit 1 RTS. The native USB peripheral resets the chip on
     *  the sequence esptool sends (ESP-IDF, USB Serial/JTAG controller). */
    public void setLines(boolean dtr, boolean rts) throws IOException {
        int value = (dtr ? 1 : 0) | (rts ? 2 : 0);
        if (cp210x) {   // SET_MHS: the high byte says which lines the low byte writes
            if (connection.controlTransfer(CP210X_OUT, CP210X_SET_MHS, value | 0x300, control.getId(), null, 0, 1000) < 0)
                throw new IOException("CP210x line state failed");
            return;
        }
        if (connection.controlTransfer(0x21, 0x22, value, control.getId(), null, 0, 1000) < 0)
            throw new IOException("CDC line state failed");
    }

    public void setBaud(int baud) throws IOException {
        byte[] rate = {(byte)baud, (byte)(baud >> 8), (byte)(baud >> 16), (byte)(baud >> 24)};
        if (cp210x) {
            if (connection.controlTransfer(CP210X_OUT, CP210X_SET_BAUDRATE, 0, control.getId(), rate, 4, 1000) != 4)
                throw new IOException("CP210x baud rate failed");
            return;
        }
        byte[] coding = {rate[0], rate[1], rate[2], rate[3], 0, 0, 8};
        if (connection.controlTransfer(0x21, 0x20, 0, control.getId(), coding, 7, 1000) != 7)
            throw new IOException("CDC line coding failed");
    }

    public boolean isClosed() { return closed || readFailure != null || writeFailure != null; }

    public int write(byte[] bytes) throws IOException {
        if (!queuedWrites) return writeNow(bytes);
        if (closed) throw new IOException("USB stream closed");
        if (writeFailure != null) throw writeFailure;
        synchronized (writeProgress) {
            if (!outgoing.offer(bytes)) throw new IOException("USB write queue overflow");
            enqueuedBytes += bytes.length;
        }
        return bytes.length;
    }

    public void setQueuedWrites(boolean enabled) throws IOException {
        if (!flushWrites(10000)) throw new IOException("USB write flush timeout");
        queuedWrites = enabled;
    }

    public boolean flushWrites(long timeoutMs) throws IOException {
        long deadline = System.nanoTime() + timeoutMs * 1000000;
        synchronized (writeProgress) {
            long target = enqueuedBytes;
            while (sentBytes < target) {
                if (writeFailure != null) throw writeFailure;
                long left = deadline - System.nanoTime();
                if (left <= 0) return false;
                try { TimeUnit.NANOSECONDS.timedWait(writeProgress, left); }
                catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IOException(error); }
            }
        }
        return true;
    }

    private void writeLoop() {
        try {
            while (!closed) {
                byte[] first = outgoing.take();
                ByteArrayOutputStream batch = new ByteArrayOutputStream(4096);
                batch.write(first, 0, first.length);
                long deadline = System.nanoTime() + 1000000;
                while (batch.size() < 4096) {
                    long left = deadline - System.nanoTime();
                    byte[] next = outgoing.poll(Math.max(0, left), TimeUnit.NANOSECONDS);
                    if (next == null) break;
                    batch.write(next, 0, next.length);
                }
                byte[] bytes = batch.toByteArray();
                writeNow(bytes);
                synchronized (writeProgress) {
                    sentBytes += bytes.length;
                    writeProgress.notifyAll();
                }
            }
        } catch (Exception error) {
            if (!closed) writeFailure = new IOException("USB writer: " + error, error);
            synchronized (writeProgress) { writeProgress.notifyAll(); }
        }
    }

    private int writeNow(byte[] bytes) throws IOException {
        if (closed) throw new IOException("USB stream closed");
        int at = 0;
        while (at < bytes.length) {
            int count = connection.bulkTransfer(output, bytes, at, bytes.length - at, 1000);
            if (count <= 0) throw new IOException("USB write failed at " + at);
            at += count;
        }
        return at;
    }

    @Override public synchronized void close() {
        if (closed) return;
        closed = true;
        if (writer != null) writer.interrupt();
        if (cp210x) connection.controlTransfer(CP210X_OUT, CP210X_IFC_ENABLE, 0, control.getId(), null, 0, 100);
        connection.releaseInterface(data);
        if (control != data) connection.releaseInterface(control);
        connection.close();
    }
}
