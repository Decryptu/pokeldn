package org.pokeldn.usbprobe;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.*;
import android.hardware.usb.*;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import android.view.WindowManager;
import java.io.*;
import java.util.ArrayList;
import java.util.concurrent.SynchronousQueue;

/** What the Python side (pokeldn.app.android) asks of Android: the board's USB state and stream,
 *  Settings, saving a file the player picks a place for, keeping the screen on during a run. */
public final class Bridge {
    private static final String PERMISSION = "org.pokeldn.usbprobe.BRIDGE_USB_PERMISSION";
    private static final int SAVE = 11, OPEN = 12, CREATE = 13;
    private static final SynchronousQueue<Object> answers = new SynchronousQueue<>();
    private static Activity activity;
    private static UsbManager manager;
    private static volatile boolean denied;
    private static volatile int changes;
    private static boolean serviceStarted;
    private static File saving;

    private static final BroadcastReceiver events = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (PERMISSION.equals(intent.getAction()))
                denied = !intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false);
            changes++;
        }
    };

    static void attach(Activity owner) {
        activity = owner;
        manager = (UsbManager)owner.getSystemService(Context.USB_SERVICE);
        IntentFilter filter = new IntentFilter(PERMISSION);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
        filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if (Build.VERSION.SDK_INT >= 33) owner.registerReceiver(events, filter, Context.RECEIVER_NOT_EXPORTED);
        else owner.registerReceiver(events, filter);
    }

    static void refresh() { changes++; }

    /** Bumped by every plug, unplug, USB prompt answer and return to the app: the Python side re-reads on a change. */
    public static int changes() { return changes; }

    private static UsbDevice board() {
        if (manager == null) return null;
        for (UsbDevice device : manager.getDeviceList().values())
            if (Setup.isBoard(device.getVendorId(), device.getProductId())) return device;
        return null;
    }

    private static boolean bridgeChip() {
        if (manager == null) return false;
        for (UsbDevice device : manager.getDeviceList().values())
            if (Setup.isBridge(device.getVendorId())) return true;
        return false;
    }

    /** "missing", "bridge", "permission", "denied" or "ready", by docs/gui.md's table up to the handshake. */
    public static String usbState() {
        UsbDevice device = board();
        if (device == null) return bridgeChip() ? "bridge" : "missing";
        if (manager.hasPermission(device)) { denied = false; return "ready"; }
        return denied ? "denied" : "permission";
    }

    public static String guidance(String state) {
        Setup.State s = "bridge".equals(state) ? Setup.State.UNSUPPORTED_BRIDGE :
            "permission".equals(state) ? Setup.State.NEEDS_PERMISSION :
            "denied".equals(state) ? Setup.State.PERMISSION_DENIED : Setup.State.NO_DEVICE;
        return Setup.guidance(s, Build.MANUFACTURER, null);
    }

    public static String deviceName() {
        UsbDevice device = board();
        if (device == null) return "";
        String product = device.getProductName();
        if (product != null) return product;
        return Setup.isCp210x(device.getVendorId(), device.getProductId()) ? "ESP32 (CP210x)" : "ESP32 (native USB)";
    }

    public static int deviceVendorId() { UsbDevice device = board(); return device == null ? 0 : device.getVendorId(); }
    public static int deviceProductId() { UsbDevice device = board(); return device == null ? 0 : device.getProductId(); }

    public static void askPermission() {
        UsbDevice device = board();
        if (device == null) return;
        activity.runOnUiThread(() -> manager.requestPermission(device, PendingIntent.getBroadcast(activity, 0,
            new Intent(PERMISSION).setPackage(activity.getPackageName()), PendingIntent.FLAG_MUTABLE)));
    }

    public static UsbStream open() throws IOException {
        UsbDevice device = board();
        if (device == null) throw new IOException("No board is plugged in.");
        if (!manager.hasPermission(device)) throw new IOException("USB access to the board is not allowed.");
        return new UsbStream(manager, device);
    }

    public static void openSettings() {
        activity.startActivity(new Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }

    public static void keepAwake(boolean on) {
        activity.runOnUiThread(() -> {
            if (on) activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            else activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        });
        // Android 14 grants a connected-device foreground service only with USB access to a device, and
        // crashes an app whose foreground start is refused: no board, no service (an online-only run).
        boolean service = on && "ready".equals(usbState());
        if (service == serviceStarted) return;
        serviceStarted = service;
        Intent intent = new Intent(activity, RunService.class);
        if (!service) intent.setAction(RunService.STOP);
        try {
            if (Build.VERSION.SDK_INT >= 26) activity.startForegroundService(intent);
            else activity.startService(intent);
        } catch (RuntimeException error) { Log.e("PokeLDN", "Foreground service", error); }
    }

    /** Asks where to put a copy of `path`; Android's picker names it `name`. */
    public static void saveAs(String path, String name, String type) {
        saving = new File(path);
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType(type == null || type.isEmpty() ? "application/octet-stream" : type).putExtra(Intent.EXTRA_TITLE, name);
        activity.runOnUiThread(() -> activity.startActivityForResult(intent, SAVE));
    }

    /** Hands `path` to another app (Files, a messenger) through Android's share sheet. */
    public static void share(String path, String type) {
        Uri uri = Files.uri(activity, new File(path));
        Intent intent = new Intent(Intent.ACTION_SEND).setType(type == null || type.isEmpty() ? "application/octet-stream" : type)
            .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        activity.runOnUiThread(() -> activity.startActivity(Intent.createChooser(intent, null)));
    }

    /** Blocks the calling (Python) thread on Android's file picker; each chosen document is copied
     *  into the app's own files (a chosen prod.keys must outlast a cache clear), since a web page's
     *  picker gives no paths. Returns their paths. */
    public static String[] pickFiles(boolean multiple) throws InterruptedException {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple);
        activity.runOnUiThread(() -> activity.startActivityForResult(intent, OPEN));
        Object answer = answers.take();
        if (!(answer instanceof Intent)) return new String[0];
        Intent data = (Intent)answer;
        ArrayList<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null)
            for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri());
        else if (data.getData() != null) uris.add(data.getData());
        File folder = new File(activity.getFilesDir(), "picked/" + System.nanoTime());
        folder.mkdirs();
        ArrayList<String> paths = new ArrayList<>();
        for (Uri uri : uris) {
            File target = new File(folder, displayName(uri));
            try (InputStream in = activity.getContentResolver().openInputStream(uri); OutputStream out = new FileOutputStream(target)) {
                copy(in, out);
                paths.add(target.getAbsolutePath());
            } catch (IOException error) { Log.e("PokeLDN", "Pick failed", error); }
        }
        return paths.toArray(new String[0]);
    }

    /** Blocks on Android's "save as" picker; returns the chosen document's address, or "" if cancelled. */
    public static String createDocument(String name) throws InterruptedException {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType("application/octet-stream").putExtra(Intent.EXTRA_TITLE, name);
        activity.runOnUiThread(() -> activity.startActivityForResult(intent, CREATE));
        Object answer = answers.take();
        return answer instanceof Intent && ((Intent)answer).getData() != null ? ((Intent)answer).getData().toString() : "";
    }

    public static void copyToDocument(String path, String uri) throws IOException {
        try (InputStream in = new FileInputStream(path);
             OutputStream out = activity.getContentResolver().openOutputStream(Uri.parse(uri), "wt")) {
            copy(in, out);
        }
    }

    private static String displayName(Uri uri) {
        String name = null;
        try (android.database.Cursor cursor = activity.getContentResolver().query(uri,
                new String[] {android.provider.OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
        } catch (Exception ignored) { }
        if (name == null || name.isEmpty()) name = uri.getLastPathSegment();
        return name == null ? "file" : name.replace('/', '_');
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buffer = new byte[65536];
        int count;
        while ((count = in.read(buffer)) > 0) out.write(buffer, 0, count);
    }

    static boolean onResult(int request, int result, Intent data) {
        if (request == OPEN || request == CREATE) {
            answers.offer(result == Activity.RESULT_OK && data != null ? data : Boolean.FALSE);
            return true;
        }
        return finishSave(request, result, data);
    }

    static boolean finishSave(int request, int result, Intent data) {
        if (request != SAVE) return false;
        File source = saving;
        saving = null;
        if (result != Activity.RESULT_OK || data == null || data.getData() == null || source == null) return true;
        new Thread(() -> {
            try (InputStream in = new FileInputStream(source);
                 OutputStream out = activity.getContentResolver().openOutputStream(data.getData())) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = in.read(buffer)) > 0) out.write(buffer, 0, count);
            } catch (IOException error) { Log.e("PokeLDN", "Save failed", error); }
        }, "save").start();
        return true;
    }

    private Bridge() {}
}
