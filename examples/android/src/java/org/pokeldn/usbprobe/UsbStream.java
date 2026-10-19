package org.pokeldn.usbprobe;

import android.hardware.usb.*;
import com.hoho.android.usbserial.driver.UsbSerialDriver;
import com.hoho.android.usbserial.driver.UsbSerialPort;
import com.hoho.android.usbserial.driver.UsbSerialProber;
import java.io.IOException;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

public final class UsbStream implements AutoCloseable {
    private UsbDeviceConnection connection;
    private UsbInterface control, data;
    private UsbEndpoint input, output;
    private UsbSerialPort serialPort;
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
        if (Setup.backend(device.getVendorId(), device.getProductId()) == Setup.Backend.USB_SERIAL) {
            openSerial(manager, device);
            reader = new Thread(this::receiveSerialLoop, "android-usb-reader");
            reader.start();
            writer = new Thread(this::writeLoop, "android-usb-writer");
            writer.start();
            return;
        }
        UsbInterface ctl = null, dat = null;
        for (int i = 0; i < device.getInterfaceCount(); i++) {
            UsbInterface iface = device.getInterface(i);
            if (iface.getInterfaceClass() == 2) ctl = iface;
            if (iface.getInterfaceClass() == 10) dat = iface;
        }
        if (ctl == null || dat == null) throw new IOException("Missing CDC interfaces");
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
            if (!connection.claimInterface(control, true) || !connection.claimInterface(data, true))
                throw new IOException("USB interface claim failed");
            byte[] coding = {0, (byte)0xc2, 1, 0, 0, 0, 8};
            if (connection.controlTransfer(0x21, 0x20, 0, control.getId(), coding, 7, 1000) != 7)
                throw new IOException("CDC line coding failed");
            if (connection.controlTransfer(0x21, 0x22, 0, control.getId(), null, 0, 1000) < 0)
                throw new IOException("CDC line state failed");
        } catch (IOException error) { close(); throw error; }
        reader = new Thread(this::receiveLoop, "android-usb-reader");
        reader.start();
        writer = new Thread(this::writeLoop, "android-usb-writer");
        writer.start();
    }

    private void openSerial(UsbManager manager, UsbDevice device) throws IOException {
        UsbSerialDriver driver = UsbSerialProber.getDefaultProber().probeDevice(device);
        if (driver == null || driver.getPorts().isEmpty()) throw new IOException("Missing USB serial driver");
        UsbDeviceConnection opened = manager.openDevice(device);
        if (opened == null) throw new IOException("USB open failed");
        UsbSerialPort port = driver.getPorts().get(0);
        try {
            port.open(opened);
            port.setParameters(115200, UsbSerialPort.DATABITS_8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE);
            port.setFlowControl(UsbSerialPort.FlowControl.NONE);
            EnumSet<UsbSerialPort.ControlLine> lines = port.getSupportedControlLines();
            if (lines.contains(UsbSerialPort.ControlLine.DTR)) port.setDTR(false);
            if (lines.contains(UsbSerialPort.ControlLine.RTS)) port.setRTS(false);
            connection = opened;
            serialPort = port;
        } catch (Exception error) {
            try { if (port.isOpen()) port.close(); } catch (Exception ignored) { }
            opened.close();
            throw error instanceof IOException ? (IOException)error : new IOException(error);
        }
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

    private void receiveSerialLoop() {
        byte[] buffer = new byte[16384];
        try {
            while (!closed) {
                int count = serialPort.read(buffer, 100);
                if (count > 0 && !incoming.offer(Arrays.copyOf(buffer, count)))
                    throw new IOException("Android USB receive queue overflow");
            }
        } catch (Exception error) {
            if (!closed) readFailure = new IOException("USB reader: " + error, error);
        }
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
        if (serialPort != null) {
            EnumSet<UsbSerialPort.ControlLine> lines = serialPort.getSupportedControlLines();
            if (lines.contains(UsbSerialPort.ControlLine.DTR)) serialPort.setDTR(dtr);
            if (lines.contains(UsbSerialPort.ControlLine.RTS)) serialPort.setRTS(rts);
            return;
        }
        int value = (dtr ? 1 : 0) | (rts ? 2 : 0);
        if (connection.controlTransfer(0x21, 0x22, value, control.getId(), null, 0, 1000) < 0)
            throw new IOException("CDC line state failed");
    }

    public void setBaud(int baud) throws IOException {
        if (serialPort != null) {
            serialPort.setParameters(baud, UsbSerialPort.DATABITS_8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE);
            return;
        }
        byte[] coding = {(byte)baud, (byte)(baud >> 8), (byte)(baud >> 16), (byte)(baud >> 24), 0, 0, 8};
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
        if (serialPort != null) {
            serialPort.write(bytes, 1000);
            return bytes.length;
        }
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
        if (serialPort != null) {
            try { serialPort.close(); } catch (IOException ignored) { }
        } else {
            connection.releaseInterface(data);
            connection.releaseInterface(control);
        }
        connection.close();
    }
}
