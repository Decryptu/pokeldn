package org.pokeldn.usbprobe;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.*;
import android.hardware.usb.*;
import android.os.Bundle;
import android.util.Log;
import android.view.WindowManager;
import android.widget.*;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.util.concurrent.atomic.AtomicBoolean;

public class MainActivity extends Activity {
    private static final String TAG = "PokeLDNPython";
    private static final String PERMISSION = "org.pokeldn.usbprobe.USB_PERMISSION";
    private UsbManager manager;
    private UsbDevice device;
    private TextView output;
    private volatile boolean destroyed;
    private volatile UsbStream stream;
    private final AtomicBoolean busy = new AtomicBoolean();
    private String operation = "test";
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (device != null && manager.hasPermission(device)) startProbe();
            else report("USB permission denied. Tap Test Python to retry.");
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        manager = (UsbManager)getSystemService(USB_SERVICE);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL); layout.setPadding(32, 90, 32, 60);
        TextView title = new TextView(this);
        title.setText("PokeLDN Python diagnostic"); title.setTextSize(24); layout.addView(title);
        Button test = new Button(this); test.setText("Test Python");
        test.setOnClickListener(v -> { operation = "test"; discover(); }); layout.addView(test);
        Button profile = new Button(this); profile.setText("Profile timing");
        profile.setOnClickListener(v -> { operation = "profile"; discover(); }); layout.addView(profile);
        Button trade = new Button(this); trade.setText("Start FireRed / LeafGreen trade");
        trade.setOnClickListener(v -> { operation = "trade"; discover(); }); layout.addView(trade);
        Button stop = new Button(this); stop.setText("Stop trade");
        stop.setOnClickListener(v -> cancelTrade()); layout.addView(stop);
        ScrollView scroll = new ScrollView(this);
        output = new TextView(this); output.setTextSize(15); output.setTextIsSelectable(true);
        scroll.addView(output); layout.addView(scroll); setContentView(layout);
        if (android.os.Build.VERSION.SDK_INT >= 33)
            registerReceiver(receiver, new IntentFilter(PERMISSION), Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(receiver, new IntentFilter(PERMISSION));
        String mode = getIntent().getStringExtra("mode");
        if ("trade".equals(mode) || "profile".equals(mode) || "replay".equals(mode) || "uplink".equals(mode)) operation = mode;
        discover();
    }

    public void report(String message) {
        Log.i(TAG, message);
        runOnUiThread(() -> { if (!destroyed) output.append(message + "\n\n"); });
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String experiment = intent.getStringExtra("experiment");
        if (busy.get() && experiment != null) {
            Python.getInstance().getModule("android_trade").callAttr("experiment", experiment);
            return;
        }
        if (busy.get()) { report("A worker is already running."); return; }
        setIntent(intent);
        String mode = intent.getStringExtra("mode");
        operation = ("trade".equals(mode) || "profile".equals(mode) || "replay".equals(mode) || "uplink".equals(mode)) ? mode : "test";
        discover();
    }

    private void discover() {
        if (busy.get()) return;
        device = null;
        for (UsbDevice candidate : manager.getDeviceList().values())
            if (Setup.isBoard(candidate.getVendorId(), candidate.getProductId())) { device = candidate; break; }
        if (device == null) { report("No board attached. Check OTG and cable."); return; }
        if (manager.hasPermission(device)) startProbe();
        else {
            report("Please accept Android's USB access prompt.");
            manager.requestPermission(device, PendingIntent.getBroadcast(this, 0,
                new Intent(PERMISSION).setPackage(getPackageName()), PendingIntent.FLAG_IMMUTABLE));
        }
    }

    private void startProbe() {
        if (!busy.compareAndSet(false, true)) return;
        UsbDevice selected = device;
        String mode = operation;
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        new Thread(() -> {
            try {
                report("Starting embedded Python...");
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                stream = new UsbStream(manager, selected);
                String module = "trade".equals(mode) ? "android_trade" :
                    ("profile".equals(mode) ? "android_profile" :
                    ("replay".equals(mode) ? "android_replay" :
                    ("uplink".equals(mode) ? "android_uplink" : "android_probe")));
                Python.getInstance().getModule(module)
                    .callAttr("run", stream, this);
            } catch (Exception error) { report("FAILED: " + error); Log.e(TAG, "Probe failed", error); }
            finally {
                if (stream != null) { stream.close(); stream = null; }
                busy.set(false); report("USB connection closed.");
                runOnUiThread(() -> getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            }
        }, "python-probe").start();
    }

    private void cancelTrade() {
        if (Python.isStarted() && busy.get()) {
            Python.getInstance().getModule("android_trade").callAttr("cancel");
            report("Stopping trade...");
        }
    }

    @Override public void onDestroy() {
        destroyed = true;
        cancelTrade();
        if (stream != null) stream.close();
        unregisterReceiver(receiver);
        super.onDestroy();
    }
}
